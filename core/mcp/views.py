"""Remote MCP transport for Continuity — Phase 0 (no OAuth yet).

A hand-rolled Streamable-HTTP / JSON-RPC 2.0 endpoint mounted at ``/mcp/``.
Speaks the minimum MCP a client needs to discover and call tools:

- ``initialize``               → protocol handshake
- ``notifications/initialized``→ accepted silently (notification)
- ``ping``                     → ``{}``
- ``tools/list``               → tools allowed for the user's plan (policy layer)
- ``tools/call``               → run a tool, return its result as text content

Reuses the existing pipeline so there is **one** auth + business-logic path:
- ``authenticate_request`` (Supabase Bearer JWT + rate-limit) → ``request.user_id``
- ``core.mcp.policy.mcp_tools_for`` / ``mcp_call`` → per-plan gating + dispatch
- ``core.services.interactions`` → counts a ``connector`` interaction per call

Phase 0 limitations (see docs/mcp-connector/PLAN.md):
- **Static Bearer auth only** — OAuth 2.1 / DCR lands in Phase 1.
- **POST + application/json only** — the optional GET SSE server-stream of
  Streamable HTTP is not implemented (returns 405). initialize/tools work fine
  over POST.
- **Stateless** — no ``Mcp-Session-Id``; each request authenticates on its own.
"""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from core.services import interactions

from . import jsonrpc
from .adapter import tool_to_mcp
from .authz import authenticate_mcp
from .policy import mcp_call, mcp_tools_for

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "Continuity", "version": "0.1.0"}

# Sent once in the `initialize` response. The client reads it as guidance on how
# to use this server efficiently, so the model follows the fast path instead of
# probing tools one by one. Keep it short and high-signal.
SERVER_INSTRUCTIONS = (
    "Continuity is the user's personal productivity workspace (projects, tasks, "
    "ideas, categories, routines, project notes, and Quick Notes — Notion-style "
    "notebook notes with sections).\n\n"
    "Be efficient — do NOT call tools speculatively or one-by-one to explore:\n"
    "1. For 'how am I doing / what's pending' questions, call `get_dashboard_summary` "
    "ONCE; it usually has enough to answer.\n"
    "2. To find something by topic across everything, call `search(query, kind?)` ONCE "
    "(it covers projects, tasks, ideas, project notes, and Quick Notes). `search` "
    "returns short snippets only.\n"
    "3. To read FULL content, call the matching detail tool with the id from search: "
    "`get_quick_note(id)` for a Quick Note's full sections/body, `get_project_detail(id)` "
    "for a project. Don't rely on search snippets for full text.\n"
    "4. Use `list_*` tools only when the user wants a filtered list.\n\n"
    "Plan gating: free users can read/search and adjust project priority; creating, "
    "editing and deleting require a Pro/Studio plan and will return an error otherwise. "
    "Deletions are irreversible — confirm with the user first."
)


@method_decorator(csrf_exempt, name="dispatch")
class McpView(View):
    def get(self, request: HttpRequest):
        # Optional Streamable-HTTP GET (server→client SSE) not implemented in
        # the spike. initialize/tools/call all work over POST.
        resp = HttpResponse(status=405)
        resp["Allow"] = "POST"
        return resp

    def post(self, request: HttpRequest):
        early = authenticate_mcp(request)
        if early is not None:
            return early

        # `request.mcp_plan` was resolved by authenticate_mcp (drives tool gating).
        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return JsonResponse(
                jsonrpc.error(None, jsonrpc.PARSE_ERROR, "Parse error"),
                status=400,
            )

        # JSON-RPC batch (a list of messages).
        if isinstance(payload, list):
            responses = [
                r for r in (self._handle(request, m) for m in payload) if r is not None
            ]
            if not responses:
                return HttpResponse(status=202)  # all notifications
            return JsonResponse(responses, safe=False)

        if not isinstance(payload, dict):
            return JsonResponse(
                jsonrpc.error(None, jsonrpc.INVALID_REQUEST, "Invalid Request"),
                status=400,
            )

        result = self._handle(request, payload)
        if result is None:
            return HttpResponse(status=202)  # notification — no body
        return JsonResponse(result)

    # ---- dispatch ----

    def _handle(self, request: HttpRequest, message) -> dict | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            req_id = message.get("id") if isinstance(message, dict) else None
            return jsonrpc.error(req_id, jsonrpc.INVALID_REQUEST, "Invalid Request")

        # Notifications (no `id`) must never get a reply.
        if jsonrpc.is_notification(message):
            return None

        req_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        try:
            if method == "initialize":
                return jsonrpc.success(req_id, self._initialize(params))
            if method == "ping":
                return jsonrpc.success(req_id, {})
            if method == "tools/list":
                return jsonrpc.success(req_id, self._tools_list(request))
            if method == "tools/call":
                return self._tools_call(request, req_id, params)
        except Exception:  # noqa: BLE001 — never 500 the transport
            logger.exception("MCP method %s failed", method)
            return jsonrpc.error(req_id, jsonrpc.INTERNAL_ERROR, "Internal error")

        return jsonrpc.error(
            req_id, jsonrpc.METHOD_NOT_FOUND, f"Method not found: {method}"
        )

    # ---- methods ----

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        version = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else DEFAULT_PROTOCOL_VERSION
        )
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": SERVER_INSTRUCTIONS,
        }

    def _tools_list(self, request: HttpRequest) -> dict:
        plan = request.mcp_plan  # type: ignore[attr-defined]
        return {"tools": [tool_to_mcp(t) for t in mcp_tools_for(plan)]}

    def _tools_call(self, request: HttpRequest, req_id, params: dict) -> dict:
        name = params.get("name")
        if not name or not isinstance(name, str):
            return jsonrpc.error(req_id, jsonrpc.INVALID_PARAMS, "Missing tool name")
        arguments = params.get("arguments") or {}
        plan = request.mcp_plan  # type: ignore[attr-defined]

        result = mcp_call(plan, name, request.user_id, arguments)
        is_error = isinstance(result, dict) and "error" in result
        if not is_error:
            # Count a successful connector tool call (source = /mcp/ path).
            interactions.record_from_request(request)

        return jsonrpc.success(
            req_id,
            {
                "content": [
                    {"type": "text", "text": json.dumps(result, default=str)}
                ],
                "isError": is_error,
            },
        )

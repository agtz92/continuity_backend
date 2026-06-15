"""Plan/capability policy for the MCP connector.

Single source of truth for what the **connector** exposes (`tools/list`) and
allows (`tools/call`), per plan. Deliberately independent from the in-app
assistant gating (`plan_required` + `tools.call()` in
`core/assistant/tools/__init__.py`) so the two channels can have different
policies without coupling.

Desired scope (see `docs/mcp-connector/PLAN.md` §8):

- ``free`` / ``basic`` : read-only **+** adjust priority (`set_project_priority`).
- ``pro`` / ``studio`` / ``admin`` : full create / modify / delete.

Enforcement is server-side and never trusts the model:

- ``mcp_tools_for(plan)``  → filters what is advertised in ``tools/list``.
- ``mcp_call(plan, ...)``  → re-checks the policy before running the handler.
  This is the real guarantee: even a tool the model was never shown is
  rejected here. ``plan`` and ``user_id`` always come from the server (token
  + ``AccountProfile``), never from tool ``args``.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.assistant.tools import Tool, all_tools, get_tool

# Per-plan capabilities EXPOSED BY THE CONNECTOR. `allow_extra` lists
# individual mutating tools allowed despite `writes=False` — this is how the
# basic/free tier gets the narrow priority tool without unlocking other writes.
MCP_TOOL_POLICY: dict[str, dict[str, Any]] = {
    "free":   {"reads": True, "writes": False, "allow_extra": {"set_project_priority"}},
    "basic":  {"reads": True, "writes": False, "allow_extra": {"set_project_priority"}},
    "pro":    {"reads": True, "writes": True, "allow_extra": set()},
    "studio": {"reads": True, "writes": True, "allow_extra": set()},
    "admin":  {"reads": True, "writes": True, "allow_extra": set()},
}

# Unknown / missing plans fall back to the most restrictive tier.
_DEFAULT_PLAN = "free"


def _policy_for(plan: str) -> dict[str, Any]:
    return MCP_TOOL_POLICY.get(plan, MCP_TOOL_POLICY[_DEFAULT_PLAN])


def mcp_tool_allowed(plan: str, tool: Tool) -> bool:
    """Whether `tool` is exposed to `plan` over the connector."""
    pol = _policy_for(plan)
    if tool.name in pol.get("allow_extra", set()):
        return True
    if tool.mutates:
        return bool(pol.get("writes"))
    return bool(pol.get("reads"))


def mcp_tools_for(plan: str) -> list[Tool]:
    """Tools the connector advertises in ``tools/list`` for this plan."""
    return [t for t in all_tools() if mcp_tool_allowed(plan, t)]


def mcp_allows(plan: str, name: str) -> bool:
    """Whether a tool name may be invoked by `plan` over the connector."""
    t = get_tool(name)
    return t is not None and mcp_tool_allowed(plan, t)


def mcp_call(plan: str, name: str, user_id: uuid.UUID, args: dict | None) -> dict:
    """Connector dispatch: policy gate (per plan) then run the handler.

    The enforcement point for ``tools/call``. ``plan`` and ``user_id`` are
    server-supplied; anything in ``args`` (including a forged ``user_id``) is
    ignored for scoping — the handler always scopes by the ``user_id``
    argument, not by ``args``.
    """
    t = get_tool(name)
    if t is None:
        return {"error": f"Unknown tool: {name}"}
    if not mcp_tool_allowed(plan, t):
        return {
            "error": (
                f"Tool '{name}' is not available on the '{plan}' plan "
                f"via the connector."
            )
        }
    return t.handler(user_id, args or {})

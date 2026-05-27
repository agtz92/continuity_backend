"""HTTP entrypoints for the assistant.

Routes (mounted under `/api/assistant/`):

- POST `/chat/`           — JSON in, Server-Sent-Events out.
- POST `/cancel/`         — set a cache flag the streaming view checks.
- GET  `/conversations/`  — list the user's conversations.
- GET  `/conversations/<id>/messages/` — full history for one conversation.
- GET  `/usage/`          — current daily / monthly usage snapshot.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Iterable

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from core.auth import authenticate_request

from . import anthropic_client, prompts, quotas
from .anthropic_client import AssistantConfigError
from .models import Conversation, Message, MessageRole

logger = logging.getLogger(__name__)


def _auth(request: HttpRequest, *, method: str = "POST"):
    """Run JWT + rate-limit pipeline, scoped to the assistant groups."""
    return authenticate_request(
        request,
        ip_group="assistant:ip",
        ip_rate=settings.ASSISTANT_RATE_LIMIT_IP,
        user_group="assistant:user",
        user_rate=settings.ASSISTANT_RATE_LIMIT_USER,
        method=method,
    )


def _burst_limited(request: HttpRequest) -> bool:
    """Second rate-limit pass for short bursts (e.g. 5/10s)."""
    from django_ratelimit.core import is_ratelimited

    return is_ratelimited(
        request=request,
        group="assistant:burst",
        key=lambda _g, r: f"u:{getattr(r, 'user_id', '')}",
        rate=settings.ASSISTANT_RATE_LIMIT_BURST,
        method="POST",
        increment=True,
    )


def _cancel_key(conv_id: uuid.UUID) -> str:
    return f"assistant:cancel:{conv_id}"


def _format_sse(kind: str, payload: Any) -> bytes:
    """One SSE frame: `event: <kind>\\ndata: <json>\\n\\n`."""
    body = json.dumps(payload, separators=(",", ":"))
    return f"event: {kind}\ndata: {body}\n\n".encode("utf-8")


def _json_error(message: str, status: int = 400, **extra) -> JsonResponse:
    return JsonResponse({"error": message, **extra}, status=status)


# ---------- POST /chat/ (SSE) ----------


@method_decorator(csrf_exempt, name="dispatch")
class ChatView(View):
    http_method_names = ["post"]

    def post(self, request: HttpRequest):
        early = _auth(request)
        if early is not None:
            return early
        if _burst_limited(request):
            return _json_error("Rate limit exceeded", status=429)

        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return _json_error("Invalid JSON body")

        content = (body.get("content") or "").strip()
        max_chars = settings.ASSISTANT_MAX_INPUT_CHARS
        if not content:
            return _json_error("Empty content")
        if len(content) > max_chars:
            return _json_error(
                f"Message too long (max {max_chars} chars)", status=413
            )

        user_id = request.user_id

        try:
            quota_snapshot = quotas.check(user_id)
        except quotas.QuotaExceeded as e:
            return _json_error(
                "Quota exceeded",
                status=429,
                kind=e.kind,
                reset_at=e.reset_at.isoformat(),
            )

        conv_id_raw = body.get("conversation_id")
        if conv_id_raw:
            try:
                conv = Conversation.objects.get(
                    id=conv_id_raw, user_id=user_id, archived=False
                )
            except Conversation.DoesNotExist:
                return _json_error("Conversation not found", status=404)
        else:
            conv = Conversation.objects.create(
                user_id=user_id, title=_derive_title(content)
            )

        # Persist the user turn upfront so on-disconnect we don't lose it.
        user_msg = Message.objects.create(
            conversation=conv,
            role=MessageRole.USER,
            content=[{"type": "text", "text": content}],
        )

        now = timezone.now()
        plan = quota_snapshot.plan

        try:
            system_blocks = prompts.build_system_blocks(
                user_id, plan=plan, now=now
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to build system blocks")
            return _json_error(f"Failed to prepare context: {e}", status=500)

        history_messages = prompts.build_messages(conv, content)
        # `deep_mode` is an explicit, per-message opt-in to the costlier
        # Sonnet model. It only has an effect for studio and admin plans
        # (see select_model); for free/pro this flag is a no-op. Even for
        # the eligible plans it's bounded by a daily cap — once that's hit
        # we silently fall back to Haiku so a user can't route every chat
        # through Sonnet.
        deep_mode = bool(body.get("deep_mode"))
        if deep_mode and plan in ("studio", "admin") and not quotas.deep_allowed(user_id):
            deep_mode = False
        model = prompts.select_model(plan, deep_mode=deep_mode)
        used_deep = plan in ("studio", "admin") and deep_mode
        max_tokens = (
            settings.ASSISTANT_MAX_TOKENS_OUT_WRITE
            if plan in ("pro", "studio", "admin")
            else settings.ASSISTANT_MAX_TOKENS_OUT
        )

        cancel_key = _cancel_key(conv.id)

        def event_stream() -> Iterable[bytes]:
            yield _format_sse(
                "meta",
                {
                    "conversation_id": str(conv.id),
                    "user_message_id": str(user_msg.id),
                    "model": model,
                    "plan": plan,
                    "messages_remaining_today": (
                        None
                        if quota_snapshot.daily_message_cap is None
                        else max(
                            0,
                            quota_snapshot.daily_message_cap
                            - quota_snapshot.messages_sent_today
                            - 1,
                        )
                    ),
                },
            )

            from .anthropic_client import TurnResult as _TurnResult

            result: _TurnResult | None = None
            try:
                for item in anthropic_client.run_turn_iter(
                    user_id=user_id,
                    system_blocks=system_blocks,
                    messages=history_messages,
                    model=model,
                    max_tokens=max_tokens,
                    plan=plan,
                    is_cancelled=lambda: bool(cache.get(cancel_key)),
                ):
                    if isinstance(item, _TurnResult):
                        result = item
                        continue
                    # Tuple (kind, payload) — forward to browser immediately
                    # so the user sees text appear as the model writes it.
                    kind, payload = item
                    yield _format_sse(kind, payload)
            except AssistantConfigError as e:
                logger.error("Assistant config error: %s", e)
                yield _format_sse(
                    "error",
                    {"message": str(e), "code": "config"},
                )
                yield _format_sse("done", {"ok": False})
                return
            except Exception as e:  # noqa: BLE001
                logger.exception("Assistant run_turn failed")
                msg = _humanize_anthropic_error(e)
                yield _format_sse("error", {"message": msg})
                yield _format_sse("done", {"ok": False})
                return

            if result is None:
                # Defensive — generator exited without a TurnResult.
                yield _format_sse("error", {"message": "no result"})
                yield _format_sse("done", {"ok": False})
                return

            # Persist all turns in chronological order so the next
            # request can replay the conversation without orphaning
            # tool_use / tool_result blocks. Usage totals are attached
            # only to the final assistant turn (the one with end_turn).
            assistant_indices = [
                i for i, m in enumerate(result.appended) if m.kind == "assistant"
            ]
            final_assistant_idx = assistant_indices[-1] if assistant_indices else None
            for i, msg in enumerate(result.appended):
                if msg.kind == "assistant":
                    is_final = i == final_assistant_idx
                    Message.objects.create(
                        conversation=conv,
                        role=MessageRole.ASSISTANT,
                        content=msg.content,
                        model=model,
                        stop_reason=result.final_stop_reason if is_final else "",
                        tokens_in=(
                            result.total_usage.tokens_in if is_final else 0
                        ),
                        tokens_out=(
                            result.total_usage.tokens_out if is_final else 0
                        ),
                        cache_read_in=(
                            result.total_usage.cache_read_in if is_final else 0
                        ),
                        cache_creation_in=(
                            result.total_usage.cache_creation_in if is_final else 0
                        ),
                    )
                else:  # "tool"
                    Message.objects.create(
                        conversation=conv,
                        role=MessageRole.TOOL,
                        content=msg.content,
                    )

            quotas.record(
                user_id,
                tokens_in=result.total_usage.tokens_in,
                tokens_out=result.total_usage.tokens_out,
                cache_read_in=result.total_usage.cache_read_in,
                deep=used_deep,
            )

            cache.delete(cancel_key)
            conv.save(update_fields=["updated_at"])

            yield _format_sse(
                "done",
                {
                    "ok": True,
                    "stop_reason": result.final_stop_reason,
                    "conversation_id": str(conv.id),
                },
            )

        response = StreamingHttpResponse(
            event_stream(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


# ---------- POST /cancel/ ----------


@method_decorator(csrf_exempt, name="dispatch")
class CancelView(View):
    http_method_names = ["post"]

    def post(self, request: HttpRequest):
        early = _auth(request)
        if early is not None:
            return early
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return _json_error("Invalid JSON")
        conv_id = body.get("conversation_id")
        if not conv_id:
            return _json_error("Missing conversation_id")
        if not Conversation.objects.filter(
            id=conv_id, user_id=request.user_id
        ).exists():
            return _json_error("Conversation not found", status=404)
        cache.set(_cancel_key(uuid.UUID(str(conv_id))), 1, 60)
        return JsonResponse({"ok": True})


# ---------- GET /conversations/ ----------


@method_decorator(csrf_exempt, name="dispatch")
class ConversationsView(View):
    http_method_names = ["get"]

    def get(self, request: HttpRequest):
        early = _auth(request, method="GET")
        if early is not None:
            return early
        rows = Conversation.objects.filter(
            user_id=request.user_id, archived=False
        ).order_by("-updated_at")[:50]
        return JsonResponse(
            {
                "conversations": [
                    {
                        "id": str(c.id),
                        "title": c.title,
                        "updated_at": c.updated_at.isoformat(),
                    }
                    for c in rows
                ]
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class ConversationMessagesView(View):
    http_method_names = ["get"]

    def get(self, request: HttpRequest, conv_id: str):
        early = _auth(request, method="GET")
        if early is not None:
            return early
        try:
            conv = Conversation.objects.get(id=conv_id, user_id=request.user_id)
        except Conversation.DoesNotExist:
            return _json_error("Not found", status=404)
        msgs = list(Message.objects.filter(conversation=conv).order_by("created"))
        return JsonResponse(
            {
                "id": str(conv.id),
                "title": conv.title,
                "messages": [
                    {
                        "id": str(m.id),
                        "role": m.role,
                        "content": m.content,
                        "model": m.model,
                        "created": m.created.isoformat(),
                    }
                    for m in msgs
                ],
            }
        )


# ---------- GET /usage/ ----------


@method_decorator(csrf_exempt, name="dispatch")
class UsageView(View):
    http_method_names = ["get"]

    def get(self, request: HttpRequest):
        early = _auth(request, method="GET")
        if early is not None:
            return early
        snap = quotas.get_usage(request.user_id)
        profile = quotas.get_or_create_profile(request.user_id)
        from core.billing.plans import period_for_price

        return JsonResponse(
            {
                "plan": snap.plan,
                "messages_sent_today": snap.messages_sent_today,
                "daily_message_cap": snap.daily_message_cap,
                "tokens_used_month": snap.tokens_used_month,
                "monthly_token_cap": snap.monthly_token_cap,
                "reset_at": snap.reset_at.isoformat(),
                "is_billing_exempt": profile.is_billing_exempt,
                "has_subscription": bool(profile.stripe_subscription_id),
                "plan_renews_at": (
                    profile.plan_renews_at.isoformat()
                    if profile.plan_renews_at
                    else None
                ),
                "had_retention_offer": profile.had_retention_offer,
                "subscription_period": period_for_price(profile.stripe_price_id),
                "cancel_at_period_end": profile.cancel_at_period_end,
            }
        )


# ---------- GET /healthz/ ----------


@method_decorator(csrf_exempt, name="dispatch")
class HealthView(View):
    """Diagnostic endpoint — verifies the API key is wired without leaking it.

    Reports prefix + length only, plus the configured model name. Useful
    to debug "is my Render env var actually set?" without ever logging
    the key. JWT-gated like everything else; admin-only.
    """

    http_method_names = ["get"]

    def get(self, request: HttpRequest):
        early = _auth(request, method="GET")
        if early is not None:
            return early
        from .quotas import get_or_create_profile

        profile = get_or_create_profile(request.user_id)
        if profile.plan != "admin":
            return _json_error("admin only", status=403)

        from django.conf import settings as dj

        key = (getattr(dj, "ANTHROPIC_API_KEY", "") or "").strip()
        return JsonResponse(
            {
                "model": getattr(dj, "ASSISTANT_MODEL_FAST", ""),
                "anthropic_key_present": bool(key),
                "anthropic_key_length": len(key),
                "anthropic_key_prefix": key[:10] if key else "",
                "anthropic_key_starts_with_sk_ant": key.startswith("sk-ant-"),
            }
        )


# ---------- helpers ----------


def _derive_title(content: str) -> str:
    first_line = content.strip().splitlines()[0] if content.strip() else "Conversation"
    return first_line[:80]


def _humanize_anthropic_error(e: Exception) -> str:
    """Translate Anthropic SDK errors into actionable messages.

    Anthropic's `AuthenticationError` (HTTP 401) means the key is being
    sent but rejected — almost always a revoked or wrong key. Surfacing
    the underlying str makes that visible in the UI instead of an
    opaque 500.
    """
    name = type(e).__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return (
            "Anthropic rejected the API key (HTTP 401/403). The key may be "
            "revoked, mis-pasted, or pointing at the wrong workspace. "
            "Update ANTHROPIC_API_KEY on the server and retry."
        )
    if name == "RateLimitError":
        return "Anthropic rate-limited the request. Try again shortly."
    if name == "APIConnectionError":
        return "Could not reach Anthropic. Check the backend's outbound network."
    return f"{name}: {e}"

"""HTTP endpoints owned by the notifications module.

`telegram_webhook` is what Telegram POSTs to whenever a user sends our bot a
message. We only care about `/start <token>` for the link-verification flow:
match the token to a NotificationLink, store the chat_id, mark verified.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import NotificationLink
from .providers.telegram import TelegramProvider

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_webhook(request, secret: str):
    if secret != getattr(settings, "TELEGRAM_WEBHOOK_SECRET", ""):
        return HttpResponse(status=403)

    # Telegram sends a header `X-Telegram-Bot-Api-Secret-Token` if we set one
    # via setWebhook. We carry our own secret in the URL too as belt-and-braces.
    header_secret = request.META.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
    expected = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    if header_secret and expected and header_secret != expected:
        return HttpResponse(status=403)

    try:
        update = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id or not text.startswith("/start"):
        return JsonResponse({"ok": True})  # ignore non-start messages

    parts = text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) > 1 else ""

    if not token:
        _safe_send(chat_id, "Hi! Open Continuity → Settings → Notifications and click *Connect Telegram* to link this chat.")
        return JsonResponse({"ok": True})

    now = timezone.now()
    link = NotificationLink.objects.filter(
        link_token=token, channel="telegram"
    ).first()

    if link is None:
        _safe_send(chat_id, "Sorry, that link is invalid.")
        return JsonResponse({"ok": True})

    if link.link_token_expires and link.link_token_expires < now:
        _safe_send(chat_id, "That link has expired. Please request a new one in Continuity.")
        return JsonResponse({"ok": True})

    link.external_id = str(chat_id)
    link.verified_at = now
    link.link_token = ""
    link.link_token_expires = None
    link.save(
        update_fields=[
            "external_id",
            "verified_at",
            "link_token",
            "link_token_expires",
        ]
    )

    _safe_send(
        chat_id,
        "✅ Connected. You'll receive your weekly digest and alerts here.",
    )
    return JsonResponse({"ok": True})


def _safe_send(chat_id, text: str) -> None:
    try:
        provider = TelegramProvider()
        provider.send(str(chat_id), _md_safe(text))
    except Exception as e:
        log.warning("telegram_webhook reply failed: %s", e)


def _md_safe(text: str) -> str:
    """Escape MarkdownV2 reserved chars in a plain-text reply."""
    from .providers.telegram import md_escape

    return md_escape(text)

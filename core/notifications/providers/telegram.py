from __future__ import annotations

import logging
from typing import Optional

import requests
from django.conf import settings

from .base import DeliveryResult, NotificationProvider, ProviderError

log = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_DEFAULT_TIMEOUT = 10  # seconds


class TelegramProvider(NotificationProvider):
    channel = "telegram"

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not self.token:
            raise ProviderError("TELEGRAM_BOT_TOKEN is not configured")

    def _api(self, method: str) -> str:
        return f"{_API_BASE}/bot{self.token}/{method}"

    def send(self, external_id: str, body: str, *, kind: Optional[str] = None) -> DeliveryResult:
        try:
            r = requests.post(
                self._api("sendMessage"),
                json={
                    "chat_id": external_id,
                    "text": body,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            log.warning("telegram.send transport error: %s", e)
            return DeliveryResult(success=False, error=f"transport: {e}")

        if r.status_code == 200 and r.json().get("ok"):
            mid = str(r.json().get("result", {}).get("message_id", ""))
            return DeliveryResult(success=True, external_message_id=mid)

        # Telegram returns descriptive errors in JSON
        try:
            detail = r.json().get("description", r.text)
        except ValueError:
            detail = r.text
        log.warning("telegram.send api error %s: %s", r.status_code, detail)
        return DeliveryResult(success=False, error=f"telegram {r.status_code}: {detail}")

    def set_webhook(self, url: str, secret_token: str) -> dict:
        """Register the webhook URL with Telegram. Idempotent."""
        r = requests.post(
            self._api("setWebhook"),
            json={
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message"],
            },
            timeout=_DEFAULT_TIMEOUT,
        )
        return r.json()

    def delete_webhook(self) -> dict:
        r = requests.post(self._api("deleteWebhook"), timeout=_DEFAULT_TIMEOUT)
        return r.json()


# Telegram MarkdownV2 reserves these characters; they must be backslash-escaped
# anywhere they appear OUTSIDE of formatting tokens. Used by builders.
_MD_RESERVED = r"_*[]()~`>#+-=|{}.!"


def md_escape(text: str) -> str:
    """Escape MarkdownV2 special characters for safe inline insertion."""
    out = []
    for ch in text:
        if ch in _MD_RESERVED:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)

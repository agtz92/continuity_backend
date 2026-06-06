"""Expo push provider.

Sends to the Expo Push API (https://exp.host/--/api/v2/push/send) over plain
HTTP with `requests` — no extra SDK dependency, mirroring the Telegram provider.

`external_id` is an `ExponentPushToken[...]`. The notification `body` is the same
MarkdownV2 blob the other channels receive, so we strip the Telegram markup to
plain text and split the first line into the push title.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

import requests

from .base import DeliveryResult, InlineButton, NotificationProvider

log = logging.getLogger(__name__)

_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_DEFAULT_TIMEOUT = 10  # seconds
_TITLE_MAX = 100
_BODY_MAX = 1500


def _md_to_plain(text: str) -> str:
    """Strip Telegram MarkdownV2 markup so the push reads as plain text."""
    # Unescape any backslash-escaped char (MarkdownV2 only escapes its reserved set).
    out = re.sub(r"\\(.)", r"\1", text)
    # Drop the remaining formatting markers we use in builders.
    return out.replace("*", "").replace("`", "")


def _split_title_body(body: str) -> tuple[str, str]:
    plain = _md_to_plain(body).strip()
    lines = plain.split("\n")
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    if not first:
        return ("Continuity", "")
    idx = next(i for i, ln in enumerate(lines) if ln.strip())
    rest = "\n".join(lines[idx + 1:]).strip()
    if not rest:
        # Single meaningful line → use it as the body under the app name.
        return ("Continuity", first[:_BODY_MAX])
    return (first[:_TITLE_MAX], rest[:_BODY_MAX])


class ExpoProvider(NotificationProvider):
    channel = "expo"

    def send(
        self,
        external_id: str,
        body: str,
        *,
        kind: Optional[str] = None,
        buttons: Optional[Sequence[InlineButton]] = None,
    ) -> DeliveryResult:
        title, message = _split_title_body(body)
        payload = {
            "to": external_id,
            "title": title,
            "body": message,
            "sound": "default",
            # The mobile app's routeFromNotification reads `data` on tap. Today is
            # the right landing for digests/reminders/announcements in the MVP.
            "data": {"path": "/today", "kind": kind or ""},
        }
        try:
            r = requests.post(
                _PUSH_URL,
                json=[payload],
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            log.warning("expo.send transport error: %s", e)
            return DeliveryResult(success=False, error=f"transport: {e}")

        try:
            data = r.json().get("data", [])
        except ValueError:
            return DeliveryResult(success=False, error=f"expo {r.status_code}: {r.text[:200]}")

        ticket = data[0] if isinstance(data, list) and data else {}
        if r.status_code == 200 and ticket.get("status") == "ok":
            return DeliveryResult(success=True, external_message_id=str(ticket.get("id", "")))

        # Surface Expo's error code (e.g. DeviceNotRegistered) so the dispatcher
        # can prune dead tokens.
        detail = ticket.get("message") or r.text[:200]
        code = (ticket.get("details") or {}).get("error", "")
        err = f"{code}: {detail}" if code else f"expo {r.status_code}: {detail}"
        log.warning("expo.send failed: %s", err)
        return DeliveryResult(success=False, error=err)

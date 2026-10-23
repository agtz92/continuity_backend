"""Expo push provider.

Sends to the Expo Push API (https://exp.host/--/api/v2/push/send) over plain
HTTP with `requests` — no extra SDK dependency, mirroring the Telegram provider.

`external_id` is an `ExponentPushToken[...]`. Builders hand us a `PushContent`
(short title + one or two lines, deep link, action category), so the push never
carries the long Telegram digest. Senders that don't build one (manual/admin
messages) fall back to the old path: strip the MarkdownV2 markup, first line as
title, the rest trimmed to `_FALLBACK_BODY_MAX`.

Android channels: Expo drops a push whose `channelId` the device hasn't created,
and the channels are created by the app's JS. So `channelId` is only sent when
`EXPO_PUSH_ANDROID_CHANNELS` is on — flip it once the app version that creates
them is out.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

import requests
from django.conf import settings

from .base import DeliveryResult, InlineButton, NotificationProvider, PushContent

log = logging.getLogger(__name__)

_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_DEFAULT_TIMEOUT = 10  # seconds
_TITLE_MAX = 100
_BODY_MAX = 240
# Fallback bodies (no PushContent) are cut hard: the lock screen shows ~2 lines.
_FALLBACK_BODY_MAX = 180


def _md_to_plain(text: str) -> str:
    """Strip Telegram MarkdownV2 markup so the push reads as plain text."""
    # Unescape any backslash-escaped char (MarkdownV2 only escapes its reserved set).
    out = re.sub(r"\\(.)", r"\1", text)
    # Links render as their label: "[Ver dashboard](https://…)" -> "Ver dashboard".
    out = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", out)
    # Drop the remaining formatting markers we use in builders.
    return out.replace("*", "").replace("`", "")


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


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
        return ("Continuity", _clip(first, _FALLBACK_BODY_MAX))
    return (_clip(first, _TITLE_MAX), _clip(rest, _FALLBACK_BODY_MAX))


def build_payload(
    external_id: str, body: str, *, kind: Optional[str], push: Optional[PushContent]
) -> dict:
    """The Expo message for one device. Pure, so tests can assert on it."""
    if push is None:
        title, message = _split_title_body(body)
        push = PushContent(title=title, body=message)
    payload: dict = {
        "to": external_id,
        "title": _clip(push.title, _TITLE_MAX),
        "body": _clip(push.body, _BODY_MAX),
        # The mobile app's routeFromNotification reads `data` on tap, and the
        # action handler reads `taskIds` from it.
        "data": {**push.data, "path": push.path, "kind": kind or ""},
    }
    if push.quiet:
        payload["interruptionLevel"] = "passive"
    else:
        payload["sound"] = "default"
    if push.category:
        payload["categoryId"] = push.category
    if push.android_channel and getattr(settings, "EXPO_PUSH_ANDROID_CHANNELS", False):
        payload["channelId"] = push.android_channel
    return payload


class ExpoProvider(NotificationProvider):
    channel = "expo"

    def send(
        self,
        external_id: str,
        body: str,
        *,
        kind: Optional[str] = None,
        buttons: Optional[Sequence[InlineButton]] = None,
        push: Optional[PushContent] = None,
    ) -> DeliveryResult:
        payload = build_payload(external_id, body, kind=kind, push=push)
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

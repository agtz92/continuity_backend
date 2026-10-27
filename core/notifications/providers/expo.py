"""Expo push provider.

Sends to the Expo Push API (https://exp.host/--/api/v2/push/send) over plain
HTTP with `requests` — no extra SDK dependency.

`external_id` is an `ExponentPushToken[...]`. Every sender hands us a
`PushContent` (short title + one or two lines, deep link, action category).

Android channels: Expo drops a push whose `channelId` the device hasn't created,
and the channels are created by the app's JS. So `channelId` is only sent when
`EXPO_PUSH_ANDROID_CHANNELS` is on — flip it once the app version that creates
them is out.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests
from django.conf import settings

from .base import DeliveryResult, NotificationProvider, PushContent

log = logging.getLogger(__name__)

_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_DEFAULT_TIMEOUT = 10  # seconds
_TITLE_MAX = 100
_BODY_MAX = 240


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_payload(external_id: str, push: PushContent, *, kind: Optional[str]) -> dict:
    """The Expo message for one device. Pure, so tests can assert on it."""
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
        push: PushContent,
        *,
        kind: Optional[str] = None,
    ) -> DeliveryResult:
        payload = build_payload(external_id, push, kind=kind)
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

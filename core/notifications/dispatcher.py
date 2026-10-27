"""Outbox dispatcher.

`enqueue()` is the single entry point. It UPSERTs a Notification row keyed by
(user_id, channel, kind, dedupe_key); already-SENT events are skipped, which
makes the cron idempotent. Then it sends the push to every device the user
registered and updates the row's status.

Push (Expo) is the only channel: Telegram was removed in 2026-10 and WhatsApp
never shipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List
import uuid as _uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Channel,
    ExpoPushToken,
    Notification,
    NotificationKind,
    NotificationSettings,
    NotificationStatus,
)
from .providers import get_provider
from .providers.base import ProviderError, PushContent

log = logging.getLogger(__name__)


@dataclass
class EnqueueResult:
    enqueued: int
    sent: int
    skipped: int
    failed: int


def enqueue(
    *,
    user_id: _uuid.UUID,
    kind: str,
    dedupe_key: str,
    push: PushContent,
) -> EnqueueResult:
    """Create (or reuse) the outbox row and push it to the user's devices.

    - No devices, or push turned off → nothing happens (no row).
    - A row already SENT for this (kind, dedupe_key) → skipped.
    - Otherwise every device gets it; the row is SENT if any delivery worked.
    """
    if kind not in NotificationKind.values:
        raise ValueError(f"Unknown kind: {kind}")

    targets = _expo_targets(user_id)
    if not targets:
        log.info("notifications.enqueue: no push devices for user=%s", user_id)
        return EnqueueResult(0, 0, 0, 0)

    notif, created = _upsert_notification(
        user_id=user_id,
        channel=Channel.EXPO.value,
        kind=kind,
        dedupe_key=dedupe_key,
        # What the phone actually showed.
        body=f"{push.title}\n{push.body}".strip(),
    )
    if not created and notif.status == NotificationStatus.SENT:
        return EnqueueResult(0, 0, 1, 0)

    notif.attempts = (notif.attempts or 0) + 1
    try:
        provider = get_provider(Channel.EXPO.value)
    except ProviderError as e:
        notif.status = NotificationStatus.FAILED
        notif.error = str(e)
        notif.save(update_fields=["status", "error", "attempts"])
        return EnqueueResult(1, 0, 0, 1)

    any_ok = False
    last_error = ""
    msg_id = ""
    for tok in targets:
        result = provider.send(tok.token, push, kind=notif.kind)
        if result.success:
            any_ok = True
            msg_id = result.external_message_id or msg_id
        else:
            last_error = result.error
            # Expo says the token is dead — prune it so we stop retrying.
            if "DeviceNotRegistered" in (result.error or ""):
                tok.delete()

    if any_ok:
        notif.status = NotificationStatus.SENT
        notif.external_message_id = msg_id
        notif.error = ""
        notif.sent_at = timezone.now()
        notif.save(
            update_fields=[
                "status",
                "external_message_id",
                "error",
                "sent_at",
                "attempts",
            ]
        )
        log.info("notifications.sent user=%s channel=expo kind=%s", user_id, kind)
        return EnqueueResult(1, 1, 0, 0)

    notif.status = NotificationStatus.FAILED
    notif.error = (last_error or "no tokens delivered")[:500]
    notif.save(update_fields=["status", "error", "attempts"])
    log.warning(
        "notifications.failed user=%s channel=expo kind=%s err=%s",
        user_id,
        kind,
        last_error,
    )
    return EnqueueResult(1, 0, 0, 1)


def push_recipients():
    """User ids that can receive a push right now: at least one registered
    device and push not turned off. Crons filter by this before building
    anything, so users without the app don't cost an analytics run."""
    off = NotificationSettings.objects.filter(push_enabled=False).values("user_id")
    return (
        ExpoPushToken.objects.exclude(user_id__in=off)
        .values_list("user_id", flat=True)
        .distinct()
    )


def _expo_targets(user_id: _uuid.UUID) -> List[ExpoPushToken]:
    """The user's push tokens, or [] if they've disabled push. A missing
    settings row means push is on (the model default)."""
    s = (
        NotificationSettings.objects.filter(user_id=user_id)
        .only("user_id", "push_enabled")
        .first()
    )
    if s is not None and not s.push_enabled:
        return []
    return list(ExpoPushToken.objects.filter(user_id=user_id))


def _upsert_notification(
    *, user_id: _uuid.UUID, channel: str, kind: str, dedupe_key: str, body: str
) -> tuple[Notification, bool]:
    """Idempotent insert. Returns (instance, created)."""
    try:
        with transaction.atomic():
            return (
                Notification.objects.create(
                    user_id=user_id,
                    channel=channel,
                    kind=kind,
                    dedupe_key=dedupe_key,
                    body=body,
                ),
                True,
            )
    except IntegrityError:
        return (
            Notification.objects.get(
                user_id=user_id, channel=channel, kind=kind, dedupe_key=dedupe_key
            ),
            False,
        )

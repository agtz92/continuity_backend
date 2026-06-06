"""Outbox dispatcher.

`enqueue()` is the single entry point. It UPSERTs a Notification row keyed by
(user_id, channel, kind, dedupe_key); already-SENT events are skipped, which
makes the cron idempotent. Then it tries to send via the channel's provider
and updates the row's status. In Fase 5 we'll wrap the send in an async task —
the caller's contract does not change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence
import uuid as _uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Channel,
    ExpoPushToken,
    Notification,
    NotificationKind,
    NotificationLink,
    NotificationSettings,
    NotificationStatus,
)
from .providers import get_provider
from .providers.base import InlineButton, ProviderError

log = logging.getLogger(__name__)


@dataclass
class EnqueueResult:
    enqueued: int
    sent: int
    skipped: int
    failed: int


def _verified_links(user_id: _uuid.UUID, channels: Iterable[str]) -> List[NotificationLink]:
    return list(
        NotificationLink.objects.filter(
            user_id=user_id,
            channel__in=list(channels),
            verified_at__isnull=False,
        )
    )


def enqueue(
    *,
    user_id: _uuid.UUID,
    kind: str,
    dedupe_key: str,
    body: str,
    channels: Iterable[str] = (),
    buttons: Optional[Sequence[InlineButton]] = None,
) -> EnqueueResult:
    """Create (or reuse) outbox rows and attempt delivery.

    - If `channels` is empty, fan out to every verified link the user has.
    - If a row already exists with status=SENT, it's a no-op (skipped).
    - Otherwise we attempt delivery and update the row to SENT or FAILED.
    - `buttons` (optional) render as a Telegram inline keyboard; other channels
      degrade gracefully (the persisted `body` is unchanged either way).
    """
    if kind not in NotificationKind.values:
        raise ValueError(f"Unknown kind: {kind}")

    requested = list(channels) if channels else [c for c, _ in Channel.choices]

    enq = sent = skipped = failed = 0

    # Link-based channels (Telegram, WhatsApp). Expo has no NotificationLink row,
    # so it never matches the link query — it's handled separately below.
    link_channels = [c for c in requested if c != Channel.EXPO.value]
    links = _verified_links(user_id, link_channels) if link_channels else []

    for link in links:
        notif, created = _upsert_notification(
            user_id=user_id,
            channel=link.channel,
            kind=kind,
            dedupe_key=dedupe_key,
            body=body,
        )
        if not created and notif.status == NotificationStatus.SENT:
            skipped += 1
            continue

        enq += 1
        ok = _attempt_send(notif, link, buttons=buttons)
        if ok:
            sent += 1
        else:
            failed += 1

    # Expo push (token-based). One outbox row per logical event; fans out to all
    # of the user's registered devices.
    if Channel.EXPO.value in requested:
        e = _enqueue_expo(
            user_id=user_id,
            kind=kind,
            dedupe_key=dedupe_key,
            body=body,
            buttons=buttons,
        )
        enq += e.enqueued
        sent += e.sent
        skipped += e.skipped
        failed += e.failed

    if enq == 0 and skipped == 0:
        log.info("notifications.enqueue: no reachable channels for user=%s", user_id)

    return EnqueueResult(enqueued=enq, sent=sent, skipped=skipped, failed=failed)


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


def _enqueue_expo(
    *,
    user_id: _uuid.UUID,
    kind: str,
    dedupe_key: str,
    body: str,
    buttons: Optional[Sequence[InlineButton]] = None,
) -> EnqueueResult:
    targets = _expo_targets(user_id)
    if not targets:
        return EnqueueResult(0, 0, 0, 0)

    notif, created = _upsert_notification(
        user_id=user_id,
        channel=Channel.EXPO.value,
        kind=kind,
        dedupe_key=dedupe_key,
        body=body,
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
        result = provider.send(tok.token, notif.body, kind=notif.kind, buttons=buttons)
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


def _attempt_send(
    notif: Notification,
    link: NotificationLink,
    *,
    buttons: Optional[Sequence[InlineButton]] = None,
) -> bool:
    notif.attempts = (notif.attempts or 0) + 1
    try:
        provider = get_provider(notif.channel)
    except ProviderError as e:
        notif.status = NotificationStatus.FAILED
        notif.error = str(e)
        notif.save(update_fields=["status", "error", "attempts"])
        return False

    result = provider.send(link.external_id, notif.body, kind=notif.kind, buttons=buttons)
    if result.success:
        notif.status = NotificationStatus.SENT
        notif.external_message_id = result.external_message_id
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
        log.info(
            "notifications.sent user=%s channel=%s kind=%s",
            notif.user_id,
            notif.channel,
            notif.kind,
        )
        return True

    notif.status = NotificationStatus.FAILED
    notif.error = result.error[:500]
    notif.save(update_fields=["status", "error", "attempts"])
    log.warning(
        "notifications.failed user=%s channel=%s kind=%s err=%s",
        notif.user_id,
        notif.channel,
        notif.kind,
        result.error,
    )
    return False

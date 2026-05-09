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
from typing import Iterable, List
import uuid as _uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Channel,
    Notification,
    NotificationKind,
    NotificationLink,
    NotificationStatus,
)
from .providers import get_provider
from .providers.base import ProviderError

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
) -> EnqueueResult:
    """Create (or reuse) outbox rows and attempt delivery.

    - If `channels` is empty, fan out to every verified link the user has.
    - If a row already exists with status=SENT, it's a no-op (skipped).
    - Otherwise we attempt delivery and update the row to SENT or FAILED.
    """
    if kind not in NotificationKind.values:
        raise ValueError(f"Unknown kind: {kind}")

    links = _verified_links(user_id, channels) if channels else _verified_links(
        user_id, [c for c, _ in Channel.choices]
    )
    if not links:
        log.info("notifications.enqueue: no verified links for user=%s", user_id)
        return EnqueueResult(0, 0, 0, 0)

    enq = sent = skipped = failed = 0

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
        ok = _attempt_send(notif, link)
        if ok:
            sent += 1
        else:
            failed += 1

    return EnqueueResult(enqueued=enq, sent=sent, skipped=skipped, failed=failed)


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


def _attempt_send(notif: Notification, link: NotificationLink) -> bool:
    notif.attempts = (notif.attempts or 0) + 1
    try:
        provider = get_provider(notif.channel)
    except ProviderError as e:
        notif.status = NotificationStatus.FAILED
        notif.error = str(e)
        notif.save(update_fields=["status", "error", "attempts"])
        return False

    result = provider.send(link.external_id, notif.body, kind=notif.kind)
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

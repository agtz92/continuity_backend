"""Per-user, per-source interaction metrics.

Records and queries `InteractionDay` counters. An "interaction" is one
**action with effect**, bucketed by channel:

- ``web`` / ``mobile`` : a GraphQL mutation or an assistant message, tagged
  by the ``X-Continuity-Client`` request header.
- ``connector``        : a Claude-connector tool call (path ``/mcp/``).

Privacy by design: only counts are stored — never content, query text, IPs
or user-agents. Recording is **best-effort**: a metrics failure must never
break the user's request.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Iterable

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from core.models import InteractionDay, InteractionSource

logger = logging.getLogger(__name__)

WEB = InteractionSource.WEB.value
MOBILE = InteractionSource.MOBILE.value
CONNECTOR = InteractionSource.CONNECTOR.value
UNKNOWN = InteractionSource.UNKNOWN.value
_VALID_SOURCES = {WEB, MOBILE, CONNECTOR, UNKNOWN}

# Clients set this header so the server can attribute interactions to a
# channel. It is used ONLY to bucket a counter — never for authz.
_CLIENT_HEADER = "HTTP_X_CONTINUITY_CLIENT"


def source_from_request(request) -> str:
    """Classify the channel a request came from (server-derived)."""
    path = getattr(request, "path", "") or ""
    if path.startswith("/mcp") or path.startswith("/api/mcp"):
        return CONNECTOR
    meta = getattr(request, "META", {}) or {}
    client = (meta.get(_CLIENT_HEADER, "") or "").strip().lower()
    if client in (WEB, MOBILE):
        return client
    return UNKNOWN


def record_interaction(
    user_id: uuid.UUID | None, source: str, *, count: int = 1
) -> None:
    """Increment today's counter for ``(user_id, source)``. Best-effort:
    swallows and logs any error so metrics never break a request."""
    if not user_id or count <= 0:
        return
    if source not in _VALID_SOURCES:
        source = UNKNOWN
    try:
        today = timezone.now().date()
        with transaction.atomic():
            row, _ = InteractionDay.objects.get_or_create(
                user_id=user_id, date=today, source=source
            )
            InteractionDay.objects.filter(pk=row.pk).update(count=F("count") + count)
    except Exception:  # noqa: BLE001 — metrics are best-effort
        logger.exception(
            "record_interaction failed (user=%s source=%s)", user_id, source
        )


def record_from_request(request, *, count: int = 1) -> None:
    """Derive source from the request and record for its authenticated user."""
    user_id = getattr(request, "user_id", None)
    if user_id:
        record_interaction(user_id, source_from_request(request), count=count)


def _since(days: int) -> dt.date:
    return timezone.now().date() - dt.timedelta(days=max(1, days) - 1)


def interactions_by_source(user_id: uuid.UUID, *, days: int = 30) -> dict[str, int]:
    """Totals per source over the last ``days`` days (inclusive of today)."""
    rows = (
        InteractionDay.objects.filter(user_id=user_id, date__gte=_since(days))
        .values("source")
        .annotate(total=Sum("count"))
    )
    return {r["source"]: int(r["total"] or 0) for r in rows}


def interactions_total(user_id: uuid.UUID, *, days: int = 30) -> int:
    return sum(interactions_by_source(user_id, days=days).values())


def bulk_interactions_total(
    user_ids: Iterable[uuid.UUID], *, days: int = 30
) -> dict[uuid.UUID, int]:
    """One query → ``{user_id: total}`` over the last ``days`` days. For the
    admin list view (avoids N+1)."""
    ids = list(user_ids)
    if not ids:
        return {}
    rows = (
        InteractionDay.objects.filter(user_id__in=ids, date__gte=_since(days))
        .values("user_id")
        .annotate(total=Sum("count"))
        .values_list("user_id", "total")
    )
    return {uid: int(total or 0) for uid, total in rows}

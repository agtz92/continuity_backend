"""User-facing management of MCP connector connections.

A "connection" is one OAuth client (e.g. Claude) the user has authorized, as
evidenced by at least one live (non-revoked, unexpired) refresh token. Lets the
user see and revoke connections from settings.
"""

from __future__ import annotations

import uuid

from django.db.models import Min
from django.utils import timezone

from core.models import OAuthClient, OAuthConnectionEvent, OAuthRefreshToken


def _client_name(client_id: str) -> str:
    return (
        OAuthClient.objects.filter(client_id=client_id)
        .values_list("client_name", flat=True)
        .first()
        or ""
    )


def log_event(user_id: uuid.UUID, client_id: str, event: str) -> None:
    """Append a connection audit event (best-effort)."""
    try:
        OAuthConnectionEvent.objects.create(
            user_id=user_id,
            client_id=client_id,
            client_name=_client_name(client_id),
            event=event,
        )
    except Exception:  # noqa: BLE001 — audit must never break the flow
        pass


def list_connections(user_id: uuid.UUID) -> list[dict]:
    """Active connections for a user, oldest first."""
    now = timezone.now()
    rows = (
        OAuthRefreshToken.objects.filter(
            user_id=user_id, revoked_at__isnull=True, expires_at__gt=now
        )
        .values("client_id", "client__client_name")
        .annotate(connected_at=Min("created"))
        .order_by("connected_at")
    )
    return [
        {
            "client_id": r["client_id"],
            "client_name": r["client__client_name"] or "",
            "connected_at": r["connected_at"],
        }
        for r in rows
    ]


def revoke_connection(
    user_id: uuid.UUID, client_id: str, *, by_admin: bool = False
) -> int:
    """Revoke all live refresh tokens for (user, client). Returns count revoked.

    Access tokens are stateless JWTs and remain valid until they expire (≤ the
    access TTL); revoking the refresh token stops the client from minting new
    ones, so access is fully cut within one TTL window.
    """
    n = OAuthRefreshToken.objects.filter(
        user_id=user_id, client_id=client_id, revoked_at__isnull=True
    ).update(revoked_at=timezone.now())
    if n:
        log_event(
            user_id,
            client_id,
            OAuthConnectionEvent.Event.ADMIN_REVOKED
            if by_admin
            else OAuthConnectionEvent.Event.REVOKED,
        )
    return n


# ---- admin (across users) ----


def list_all_connections(*, limit: int = 50) -> list[dict]:
    """Active connections across all users, most-recent first (admin view)."""
    now = timezone.now()
    rows = (
        OAuthRefreshToken.objects.filter(revoked_at__isnull=True, expires_at__gt=now)
        .values("user_id", "client_id", "client__client_name")
        .annotate(connected_at=Min("created"))
        .order_by("-connected_at")[: max(1, min(limit, 200))]
    )
    return [
        {
            "user_id": r["user_id"],
            "client_id": r["client_id"],
            "client_name": r["client__client_name"] or "",
            "connected_at": r["connected_at"],
        }
        for r in rows
    ]


def recent_events(*, limit: int = 50) -> list[OAuthConnectionEvent]:
    """Most recent audit events across all users (admin view)."""
    return list(OAuthConnectionEvent.objects.all()[: max(1, min(limit, 200))])


def connection_stats() -> dict:
    """Aggregate counts for the admin dashboard."""
    now = timezone.now()
    live = OAuthRefreshToken.objects.filter(revoked_at__isnull=True, expires_at__gt=now)
    by_client: dict[str, int] = {}
    for cid, cname in live.values_list("client_id", "client__client_name"):
        key = cname or cid
        by_client[key] = by_client.get(key, 0) + 1
    return {
        "active_connections": live.values("user_id", "client_id").distinct().count(),
        "distinct_users": live.values("user_id").distinct().count(),
        "by_client": by_client,
    }

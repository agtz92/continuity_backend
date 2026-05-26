"""Thin wrapper over the Supabase Auth admin REST API.

Uses the service role key — never expose this to the frontend.

Supabase pages users at /auth/v1/admin/users?page=N&per_page=K. The
shape returned is documented at
https://supabase.com/docs/reference/javascript/auth-admin-listusers.
We only depend on a small subset of fields.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class SupabaseAdminError(Exception):
    """Raised when the Supabase admin API returns a non-2xx response."""


@dataclass
class SupabaseUser:
    id: uuid.UUID
    email: str
    created_at: Optional[str]
    last_sign_in_at: Optional[str]
    email_confirmed_at: Optional[str]
    phone: str = ""
    banned_until: Optional[str] = None


@dataclass
class SupabaseUserPage:
    users: list[SupabaseUser]
    total: int  # total may be missing from older Supabase versions
    page: int
    per_page: int


def _auth_headers() -> dict:
    key = getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    if not settings.SUPABASE_URL or not key:
        raise SupabaseAdminError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured"
        )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }


def _parse_user(raw: dict) -> SupabaseUser:
    return SupabaseUser(
        id=uuid.UUID(raw["id"]),
        email=raw.get("email", "") or "",
        created_at=raw.get("created_at"),
        last_sign_in_at=raw.get("last_sign_in_at"),
        email_confirmed_at=raw.get("email_confirmed_at"),
        phone=raw.get("phone", "") or "",
        banned_until=raw.get("banned_until"),
    )


def list_users(page: int = 1, per_page: int = 50) -> SupabaseUserPage:
    page = max(1, page)
    per_page = max(1, min(per_page, 1000))
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    resp = requests.get(
        url,
        headers=_auth_headers(),
        params={"page": page, "per_page": per_page},
        timeout=15,
    )
    if resp.status_code != 200:
        raise SupabaseAdminError(
            f"Supabase admin API list_users {resp.status_code}: {resp.text}"
        )
    body = resp.json() if resp.text else {}
    raw_users = body.get("users") if isinstance(body, dict) else body
    if not isinstance(raw_users, list):
        raw_users = []
    return SupabaseUserPage(
        users=[_parse_user(u) for u in raw_users],
        total=int(body.get("total", len(raw_users)))
        if isinstance(body, dict)
        else len(raw_users),
        page=page,
        per_page=per_page,
    )


def get_user(user_id: uuid.UUID) -> Optional[SupabaseUser]:
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}"
    resp = requests.get(url, headers=_auth_headers(), timeout=10)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise SupabaseAdminError(
            f"Supabase admin API get_user {resp.status_code}: {resp.text}"
        )
    body = resp.json()
    return _parse_user(body.get("user", body) if isinstance(body, dict) else body)


def fetch_all_users() -> list[SupabaseUser]:
    """Return every Supabase auth user by walking the admin API pages.

    The /auth/v1/admin/users endpoint doesn't return a reliable total in
    the JSON body, so we paginate at max per_page (1000) until a short
    page is returned. A 50-page safety cap (~50k users) prevents runaway
    requests if the response shape ever changes.
    """
    PER_PAGE = 1000
    MAX_PAGES = 50
    out: list[SupabaseUser] = []
    for page in range(1, MAX_PAGES + 1):
        result = list_users(page=page, per_page=PER_PAGE)
        out.extend(result.users)
        if len(result.users) < PER_PAGE:
            return out
    return out


def count_users() -> int:
    """Count all Supabase auth users (see fetch_all_users for caveats)."""
    return len(fetch_all_users())


def get_users_map(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, SupabaseUser]:
    """Fetch many users by id. Falls back to per-id requests because
    Supabase's admin API doesn't expose a bulk lookup-by-id endpoint.
    Keep input small (≤ 50) for reasonable latency.
    """
    out: dict[uuid.UUID, SupabaseUser] = {}
    for uid in user_ids:
        try:
            user = get_user(uid)
        except SupabaseAdminError as e:
            logger.warning("Failed to fetch Supabase user %s: %s", uid, e)
            continue
        if user is not None:
            out[uid] = user
    return out

"""Token + PKCE primitives for the MCP OAuth server.

- Access tokens: stateless JWTs signed with ``MCP_OAUTH_SIGNING_KEY`` (HS256),
  ``sub`` = Supabase user UUID, so ``/mcp/`` can validate them with our key and
  reuse the same per-user scoping as everything else.
- Refresh tokens / authorization codes: opaque random strings; only their
  sha256 hash is stored.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid

import jwt
from django.conf import settings
from django.utils import timezone

ACCESS_TYP = "at+jwt"


def _signing_key() -> str:
    return settings.MCP_OAUTH_SIGNING_KEY


# ---- opaque tokens (codes, refresh) ----


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---- access JWT ----


def mint_access_token(
    *, user_id, client_id: str, scope: str, issuer: str, resource: str
) -> tuple[str, int]:
    ttl = int(settings.MCP_OAUTH_ACCESS_TTL)
    now = timezone.now()
    iat = int(now.timestamp())
    payload = {
        "iss": issuer,
        "sub": str(user_id),
        "aud": resource,
        "client_id": client_id,
        "scope": scope,
        "typ": ACCESS_TYP,
        "iat": iat,
        "exp": iat + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _signing_key(), algorithm="HS256"), ttl


def user_id_from_access_token(token: str):
    """Return the user UUID for a valid MCP access token, else None.

    Never raises — used in the request auth path.
    """
    try:
        claims = jwt.decode(
            token,
            _signing_key(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub"], "verify_aud": False},
        )
    except Exception:  # noqa: BLE001 — any failure → not our token
        return None
    if claims.get("typ") != ACCESS_TYP:
        return None
    sub = claims.get("sub")
    try:
        return uuid.UUID(sub) if sub else None
    except (ValueError, TypeError):
        return None


# ---- PKCE ----


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """OAuth 2.1 requires S256. `plain` is rejected."""
    if not code_verifier or not code_challenge:
        return False
    if method != "S256":
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, code_challenge)

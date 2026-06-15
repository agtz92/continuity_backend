"""Authentication for the /mcp/ transport.

Accepts an **MCP OAuth access token** (Fase 1, primary) and falls back to a raw
**Supabase JWT** (Fase 0 dev path). On failure returns 401 with a
``WWW-Authenticate`` header pointing at the protected-resource metadata so an
MCP client (Claude) can discover the OAuth server and start the flow.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django_ratelimit.core import is_ratelimited

from core.assistant.quotas import get_or_create_profile
from core.auth import JWTAuthError, _ip_key, _user_key, verify_supabase_jwt
from core.mcp.oauth.tokens import user_id_from_access_token


def _bearer(request) -> str | None:
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    return token or None


def _www_authenticate(request) -> str:
    issuer = request.build_absolute_uri("/").rstrip("/")
    metadata = f"{issuer}/.well-known/oauth-protected-resource"
    return f'Bearer resource_metadata="{metadata}"'


def _unauthorized(request) -> HttpResponse:
    resp = JsonResponse(
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Unauthorized"}},
        status=401,
    )
    resp["WWW-Authenticate"] = _www_authenticate(request)
    return resp


def _rate_limited() -> JsonResponse:
    return JsonResponse(
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "Rate limit exceeded"}},
        status=429,
    )


def authenticate_mcp(request):
    """Return None on success (sets ``request.user_id``), else a response."""
    if is_ratelimited(
        request=request,
        group="mcp:ip",
        key=_ip_key,
        rate=settings.MCP_RATE_LIMIT_IP,
        method="POST",
        increment=True,
    ):
        return _rate_limited()

    token = _bearer(request)
    if not token:
        return _unauthorized(request)

    # 1) Our MCP OAuth access token (primary path).
    user_id = user_id_from_access_token(token)
    # 2) Dev fallback: a raw Supabase JWT (Fase 0 / local testing).
    if user_id is None:
        try:
            claims = verify_supabase_jwt(token)
            sub = claims.get("sub")
            user_id = uuid.UUID(sub) if sub else None
        except (JWTAuthError, ValueError, TypeError):
            user_id = None

    if user_id is None:
        return _unauthorized(request)

    request.user_id = user_id

    # Resolve the plan once (also drives tool gating in McpView) and apply the
    # per-plan user rate limit. The connector's cost is OUR infra, so higher
    # plans get more throughput; unknown plans fall back to the global default.
    plan = get_or_create_profile(user_id).plan
    request.mcp_plan = plan  # type: ignore[attr-defined]
    user_rate = settings.MCP_RATE_LIMIT_BY_PLAN.get(plan, settings.MCP_RATE_LIMIT_USER)

    if is_ratelimited(
        request=request,
        group="mcp:user",
        key=_user_key,
        rate=user_rate,
        method="POST",
        increment=True,
    ):
        return _rate_limited()

    return None

"""OAuth 2.1 endpoints for the MCP connector.

Discovery (RFC 8414 / 9728), Dynamic Client Registration (RFC 7591),
authorization (PKCE, delegated login via the Supabase frontend) and token
(auth-code + refresh) endpoints. Public clients only.
"""

from __future__ import annotations

import json
import logging
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from datetime import timedelta

from core.auth import JWTAuthError, verify_supabase_jwt
from core.models import (
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthConnectionEvent,
    OAuthRefreshToken,
)
from core.services import mcp_connections as mcp_connections_svc

from . import tokens

logger = logging.getLogger(__name__)

SCOPES_SUPPORTED = ["continuity:read", "continuity:write"]
DEFAULT_SCOPE = " ".join(SCOPES_SUPPORTED)


def _issuer(request: HttpRequest) -> str:
    return request.build_absolute_uri("/").rstrip("/")


def _resource(request: HttpRequest) -> str:
    return f"{_issuer(request)}/mcp/"


# --------------------------------------------------------------------------
# Discovery metadata
# --------------------------------------------------------------------------


def protected_resource_metadata(request: HttpRequest):
    """RFC 9728 — tells the client which authorization server protects /mcp/."""
    issuer = _issuer(request)
    return JsonResponse(
        {
            "resource": _resource(request),
            "authorization_servers": [issuer],
            "scopes_supported": SCOPES_SUPPORTED,
            "bearer_methods_supported": ["header"],
        }
    )


def authorization_server_metadata(request: HttpRequest):
    """RFC 8414 — endpoint discovery for the authorization server."""
    issuer = _issuer(request)
    return JsonResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": SCOPES_SUPPORTED,
        }
    )


# --------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# --------------------------------------------------------------------------


def register(request: HttpRequest):
    if request.method != "POST":
        return _err(405, "method_not_allowed")
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return _err(400, "invalid_request", "Body must be JSON")

    redirect_uris = body.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _err(400, "invalid_redirect_uri", "redirect_uris required")
    for uri in redirect_uris:
        if not isinstance(uri, str) or not uri.startswith(("http://", "https://")):
            return _err(400, "invalid_redirect_uri", f"Bad redirect_uri: {uri}")

    client = OAuthClient.objects.create(
        client_id="mcp_" + secrets.token_hex(16),
        client_name=str(body.get("client_name", ""))[:255],
        redirect_uris=redirect_uris,
        token_endpoint_auth_method="none",
    )
    return JsonResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": int(client.created.timestamp()),
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status=201,
    )


# --------------------------------------------------------------------------
# Authorization endpoint (PKCE) — delegates login to the frontend
# --------------------------------------------------------------------------


def authorize(request: HttpRequest):
    p = request.GET
    client_id = p.get("client_id", "")
    redirect_uri = p.get("redirect_uri", "")

    client = OAuthClient.objects.filter(client_id=client_id).first()
    # If the client or redirect_uri is invalid we must NOT redirect (open
    # redirect risk) — render a plain error instead.
    if client is None:
        return _err(400, "invalid_client", "Unknown client_id")
    if redirect_uri not in (client.redirect_uris or []):
        return _err(400, "invalid_request", "redirect_uri not registered")

    # From here, errors can safely redirect back to the (validated) redirect_uri.
    if p.get("response_type") != "code":
        return _redirect_error(redirect_uri, "unsupported_response_type", p.get("state"))
    if not p.get("code_challenge") or p.get("code_challenge_method") != "S256":
        return _redirect_error(redirect_uri, "invalid_request", p.get("state"))

    # Hand off to the frontend consent page (Supabase login + approve).
    consent_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": p.get("code_challenge"),
        "code_challenge_method": "S256",
        "scope": p.get("scope") or DEFAULT_SCOPE,
        "state": p.get("state") or "",
        "client_name": client.client_name,
    }
    consent_url = (
        f"{settings.FRONTEND_BASE_URL.rstrip('/')}/oauth/consent?"
        + urlencode(consent_params)
    )
    return HttpResponseRedirect(consent_url)


def approve(request: HttpRequest):
    """Called by the frontend consent page with a Supabase Bearer token.

    Mints an authorization code bound to the authenticated Supabase user and
    returns the URL to redirect the browser back to the client.
    """
    if request.method != "POST":
        return _err(405, "method_not_allowed")

    user_id = _supabase_user(request)
    if user_id is None:
        return _err(401, "unauthorized", "Valid Supabase session required")

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return _err(400, "invalid_request", "Body must be JSON")

    client_id = body.get("client_id", "")
    redirect_uri = body.get("redirect_uri", "")
    code_challenge = body.get("code_challenge", "")
    method = body.get("code_challenge_method", "S256")
    scope = body.get("scope") or DEFAULT_SCOPE
    state = body.get("state") or ""

    client = OAuthClient.objects.filter(client_id=client_id).first()
    if client is None or redirect_uri not in (client.redirect_uris or []):
        return _err(400, "invalid_request", "Unknown client or redirect_uri")
    if not code_challenge or method != "S256":
        return _err(400, "invalid_request", "PKCE S256 required")

    raw_code = tokens.new_opaque_token()
    OAuthAuthorizationCode.objects.create(
        code_hash=tokens.hash_token(raw_code),
        client=client,
        user_id=user_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method="S256",
        scope=scope,
        expires_at=timezone.now() + timedelta(seconds=int(settings.MCP_OAUTH_CODE_TTL)),
    )
    sep = "&" if "?" in redirect_uri else "?"
    redirect_to = redirect_uri + sep + urlencode({"code": raw_code, "state": state})
    return JsonResponse({"redirect_to": redirect_to})


# --------------------------------------------------------------------------
# Token endpoint
# --------------------------------------------------------------------------


def token(request: HttpRequest):
    if request.method != "POST":
        return _err(405, "method_not_allowed")
    params = _form_or_json(request)
    grant_type = params.get("grant_type")

    if grant_type == "authorization_code":
        return _grant_authorization_code(request, params)
    if grant_type == "refresh_token":
        return _grant_refresh_token(request, params)
    return _err(400, "unsupported_grant_type")


def _grant_authorization_code(request: HttpRequest, params) -> JsonResponse:
    code = params.get("code", "")
    redirect_uri = params.get("redirect_uri", "")
    client_id = params.get("client_id", "")
    code_verifier = params.get("code_verifier", "")

    row = OAuthAuthorizationCode.objects.filter(
        code_hash=tokens.hash_token(code)
    ).select_related("client").first()
    if row is None:
        return _err(400, "invalid_grant", "Unknown code")
    if row.consumed_at is not None:
        return _err(400, "invalid_grant", "Code already used")
    if row.expires_at < timezone.now():
        return _err(400, "invalid_grant", "Code expired")
    if row.client_id != client_id:
        return _err(400, "invalid_grant", "Client mismatch")
    if row.redirect_uri != redirect_uri:
        return _err(400, "invalid_grant", "redirect_uri mismatch")
    if not tokens.verify_pkce(code_verifier, row.code_challenge, row.code_challenge_method):
        return _err(400, "invalid_grant", "PKCE verification failed")

    row.consumed_at = timezone.now()
    row.save(update_fields=["consumed_at"])

    mcp_connections_svc.log_event(
        row.user_id, client_id, OAuthConnectionEvent.Event.AUTHORIZED
    )
    return _issue_tokens(request, client_id=client_id, user_id=row.user_id, scope=row.scope)


def _grant_refresh_token(request: HttpRequest, params) -> JsonResponse:
    raw = params.get("refresh_token", "")
    client_id = params.get("client_id", "")
    row = OAuthRefreshToken.objects.filter(token_hash=tokens.hash_token(raw)).first()
    if row is None or row.revoked_at is not None:
        return _err(400, "invalid_grant", "Invalid refresh token")
    if row.expires_at < timezone.now():
        return _err(400, "invalid_grant", "Refresh token expired")
    if row.client_id != client_id:
        return _err(400, "invalid_grant", "Client mismatch")

    # Rotate: revoke the old refresh token before issuing a new one.
    row.revoked_at = timezone.now()
    row.save(update_fields=["revoked_at"])
    mcp_connections_svc.log_event(
        row.user_id, client_id, OAuthConnectionEvent.Event.TOKEN_REFRESHED
    )
    return _issue_tokens(request, client_id=client_id, user_id=row.user_id, scope=row.scope)


def _issue_tokens(request, *, client_id, user_id, scope) -> JsonResponse:
    access, ttl = tokens.mint_access_token(
        user_id=user_id,
        client_id=client_id,
        scope=scope,
        issuer=_issuer(request),
        resource=_resource(request),
    )
    raw_refresh = tokens.new_opaque_token()
    OAuthRefreshToken.objects.create(
        token_hash=tokens.hash_token(raw_refresh),
        client_id=client_id,
        user_id=user_id,
        scope=scope,
        expires_at=timezone.now() + timedelta(seconds=int(settings.MCP_OAUTH_REFRESH_TTL)),
    )
    return JsonResponse(
        {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ttl,
            "refresh_token": raw_refresh,
            "scope": scope,
        }
    )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _supabase_user(request: HttpRequest):
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        claims = verify_supabase_jwt(auth.split(" ", 1)[1].strip())
    except JWTAuthError:
        return None
    sub = claims.get("sub")
    import uuid

    try:
        return uuid.UUID(sub) if sub else None
    except (ValueError, TypeError):
        return None


def _form_or_json(request: HttpRequest):
    ctype = request.content_type or ""
    if "application/json" in ctype:
        try:
            return json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST


def _err(status: int, error: str, description: str | None = None) -> JsonResponse:
    payload = {"error": error}
    if description:
        payload["error_description"] = description
    return JsonResponse(payload, status=status)


def _redirect_error(redirect_uri: str, error: str, state) -> HttpResponse:
    sep = "&" if "?" in redirect_uri else "?"
    q = {"error": error}
    if state:
        q["state"] = state
    return HttpResponseRedirect(redirect_uri + sep + urlencode(q))

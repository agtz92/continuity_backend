"""Tests for the MCP OAuth 2.1 authorization server (Fase 1).

Covers discovery metadata, dynamic client registration, the authorize→consent
redirect, the approve (code minting), the token endpoint (auth-code + refresh),
and the security edges: PKCE enforcement, code replay, refresh rotation, and
that the issued access token actually authenticates at /mcp/.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from django.conf import settings as django_settings
from django.test import Client

from core import auth as auth_module

REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture(autouse=True)
def _force_test_auth_settings(settings, monkeypatch):
    settings.SUPABASE_URL = ""
    settings.SUPABASE_JWT_SECRET = "test-jwt-secret"
    settings.FRONTEND_BASE_URL = "https://app.example.com"
    monkeypatch.setattr(auth_module, "_jwks_client", None)


@pytest.fixture
def http():
    return Client()


def _supabase_jwt(user_id):
    return jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 3600,
        },
        django_settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _register(http, redirect_uri=REDIRECT_URI):
    resp = http.post(
        "/oauth/register",
        data=json.dumps({"client_name": "Claude", "redirect_uris": [redirect_uri]}),
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["client_id"]


def _do_consent(http, user_id, redirect_uri=REDIRECT_URI):
    """register + approve → returns (client_id, code, verifier, redirect_uri)."""
    client_id = _register(http, redirect_uri)
    verifier, challenge = _pkce()
    resp = http.post(
        "/oauth/authorize/approve",
        data=json.dumps(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "xyz",
                "scope": "continuity:read continuity:write",
            }
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_supabase_jwt(user_id)}",
    )
    assert resp.status_code == 200, resp.content
    q = parse_qs(urlparse(resp.json()["redirect_to"]).query)
    assert q["state"] == ["xyz"]
    return client_id, q["code"][0], verifier, redirect_uri


def _exchange(http, code, verifier, client_id, redirect_uri=REDIRECT_URI):
    return http.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_protected_resource_metadata(http):
    d = http.get("/.well-known/oauth-protected-resource").json()
    assert d["resource"].endswith("/mcp/")
    assert d["authorization_servers"]


@pytest.mark.django_db
def test_authorization_server_metadata(http):
    d = http.get("/.well-known/oauth-authorization-server").json()
    assert d["code_challenge_methods_supported"] == ["S256"]
    assert "authorization_code" in d["grant_types_supported"]
    assert "refresh_token" in d["grant_types_supported"]
    assert d["registration_endpoint"].endswith("/oauth/register")
    assert d["token_endpoint_auth_methods_supported"] == ["none"]


# --------------------------------------------------------------------------
# Dynamic Client Registration
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_register_returns_client_id(http):
    resp = http.post(
        "/oauth/register",
        data=json.dumps({"client_name": "Claude", "redirect_uris": [REDIRECT_URI]}),
        content_type="application/json",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"].startswith("mcp_")
    assert body["redirect_uris"] == [REDIRECT_URI]
    assert body["token_endpoint_auth_method"] == "none"


@pytest.mark.django_db
def test_register_requires_redirect_uris(http):
    resp = http.post(
        "/oauth/register",
        data=json.dumps({"client_name": "x"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_register_rejects_non_http_redirect(http):
    resp = http.post(
        "/oauth/register",
        data=json.dumps({"redirect_uris": ["javascript:alert(1)"]}),
        content_type="application/json",
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# Authorize
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_authorize_redirects_to_consent(http):
    client_id = _register(http)
    _v, challenge = _pkce()
    resp = http.get(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s1",
        },
    )
    assert resp.status_code == 302
    loc = resp["Location"]
    assert loc.startswith("https://app.example.com/oauth/consent?")
    q = parse_qs(urlparse(loc).query)
    assert q["client_id"] == [client_id]
    assert q["code_challenge"] == [challenge]


@pytest.mark.django_db
def test_authorize_unknown_client_does_not_redirect(http):
    resp = http.get(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": "mcp_nope",
            "redirect_uri": REDIRECT_URI,
            "code_challenge": "x",
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_authorize_unregistered_redirect_uri_rejected(http):
    client_id = _register(http)
    resp = http.get(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://evil.example/cb",
            "code_challenge": "x",
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_authorize_rejects_non_s256(http):
    client_id = _register(http)
    resp = http.get(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": "x",
            "code_challenge_method": "plain",
            "state": "s9",
        },
    )
    # valid redirect_uri → error comes back as a redirect to the client
    assert resp.status_code == 302
    q = parse_qs(urlparse(resp["Location"]).query)
    assert q["error"] == ["invalid_request"]


# --------------------------------------------------------------------------
# Approve (code minting) — requires Supabase login
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_approve_requires_supabase_auth(http):
    client_id = _register(http)
    _v, challenge = _pkce()
    resp = http.post(
        "/oauth/authorize/approve",
        data=json.dumps(
            {
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Token endpoint
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_authorization_code_flow(http, user_a):
    client_id, code, verifier, redirect_uri = _do_consent(http, user_a)
    resp = _exchange(http, code, verifier, client_id, redirect_uri)
    assert resp.status_code == 200, resp.content
    tok = resp.json()
    assert tok["token_type"] == "Bearer"
    assert tok["access_token"]
    assert tok["refresh_token"]
    assert tok["expires_in"] > 0


@pytest.mark.django_db
def test_access_token_authenticates_at_mcp(http, user_a, make_project):
    make_project(user_a, name="Alpha")
    client_id, code, verifier, redirect_uri = _do_consent(http, user_a)
    access = _exchange(http, code, verifier, client_id, redirect_uri).json()["access_token"]

    resp = http.post(
        "/mcp/",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert resp.status_code == 200
    assert "tools" in resp.json()["result"]


@pytest.mark.django_db
def test_code_replay_rejected(http, user_a):
    client_id, code, verifier, redirect_uri = _do_consent(http, user_a)
    assert _exchange(http, code, verifier, client_id, redirect_uri).status_code == 200
    resp = _exchange(http, code, verifier, client_id, redirect_uri)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


@pytest.mark.django_db
def test_pkce_mismatch_rejected(http, user_a):
    client_id, code, _verifier, redirect_uri = _do_consent(http, user_a)
    resp = _exchange(http, code, "totally-wrong-verifier", client_id, redirect_uri)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


@pytest.mark.django_db
def test_redirect_uri_mismatch_rejected(http, user_a):
    client_id, code, verifier, _redirect = _do_consent(http, user_a)
    resp = _exchange(http, code, verifier, client_id, "https://claude.ai/other")
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


@pytest.mark.django_db
def test_refresh_token_rotation(http, user_a):
    client_id, code, verifier, redirect_uri = _do_consent(http, user_a)
    refresh = _exchange(http, code, verifier, client_id, redirect_uri).json()["refresh_token"]

    resp = http.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        },
    )
    assert resp.status_code == 200
    rotated = resp.json()
    assert rotated["access_token"]
    assert rotated["refresh_token"] != refresh

    # Old refresh token is now revoked → reuse fails.
    reuse = http.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        },
    )
    assert reuse.status_code == 400
    assert reuse.json()["error"] == "invalid_grant"


@pytest.mark.django_db
def test_authorized_and_refresh_events_logged(http, user_a):
    from core.models import OAuthConnectionEvent

    client_id, code, verifier, redirect_uri = _do_consent(http, user_a)
    refresh = _exchange(http, code, verifier, client_id, redirect_uri).json()[
        "refresh_token"
    ]
    assert OAuthConnectionEvent.objects.filter(
        user_id=user_a, event="authorized"
    ).count() == 1

    http.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        },
    )
    assert OAuthConnectionEvent.objects.filter(
        user_id=user_a, event="token_refreshed"
    ).count() == 1


@pytest.mark.django_db
def test_unsupported_grant_type(http):
    resp = http.post("/oauth/token", data={"grant_type": "password"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "unsupported_grant_type"


# --------------------------------------------------------------------------
# /mcp/ advertises OAuth on 401
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_mcp_unauthorized_advertises_oauth(http):
    resp = http.post(
        "/mcp/",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert "resource_metadata" in resp["WWW-Authenticate"]

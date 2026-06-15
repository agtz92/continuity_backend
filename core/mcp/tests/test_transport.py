"""End-to-end tests for the MCP transport view (`/mcp/`).

Exercises the JSON-RPC surface over real HTTP (Django test Client) with a
signed Supabase JWT, and confirms the policy layer + interaction metrics are
wired through the transport.
"""

from __future__ import annotations

import datetime as dt
import json

import jwt
import pytest
from django.conf import settings as django_settings
from django.test import Client

from core import auth as auth_module
from core.models import InteractionDay


@pytest.fixture(autouse=True)
def _force_test_auth_settings(settings, monkeypatch):
    # Pin HS256 fallback auth (a dev .env SUPABASE_URL would push to JWKS).
    settings.SUPABASE_URL = ""
    settings.SUPABASE_JWT_SECRET = "test-jwt-secret"
    monkeypatch.setattr(auth_module, "_jwks_client", None)


def _make_jwt(user_id):
    return jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 3600,
        },
        django_settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def http():
    return Client()


def _rpc(http, token, method, params=None, req_id=1):
    body = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    return http.post(
        "/mcp/",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _tool_call_result(resp) -> tuple[dict, bool]:
    """Parse a tools/call response → (decoded tool result, isError)."""
    result = resp.json()["result"]
    text = result["content"][0]["text"]
    return json.loads(text), result["isError"]


# --------------------------------------------------------------------------
# Auth / method guards
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_requires_auth(http):
    resp = http.post(
        "/mcp/",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        content_type="application/json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_get_not_allowed(http):
    resp = http.get("/mcp/")
    assert resp.status_code == 405
    assert resp["Allow"] == "POST"


# --------------------------------------------------------------------------
# Handshake
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_initialize_echoes_supported_version(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    resp = _rpc(http, _make_jwt(user_a), "initialize", {"protocolVersion": "2025-06-18"})
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "Continuity"
    assert "tools" in result["capabilities"]


@pytest.mark.django_db
def test_initialize_falls_back_on_unknown_version(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    resp = _rpc(http, _make_jwt(user_a), "initialize", {"protocolVersion": "1999-01-01"})
    assert resp.json()["result"]["protocolVersion"] == "2025-06-18"


@pytest.mark.django_db
def test_notification_gets_no_reply(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    resp = http.post(
        "/mcp/",
        data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )
    assert resp.status_code == 202
    assert resp.content == b""


@pytest.mark.django_db
def test_ping(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    resp = _rpc(http, _make_jwt(user_a), "ping")
    assert resp.json()["result"] == {}


# --------------------------------------------------------------------------
# tools/list — gated by plan
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_tools_list_free_is_read_plus_priority(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    resp = _rpc(http, _make_jwt(user_a), "tools/list")
    tools = resp.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "list_projects" in names
    assert "set_project_priority" in names
    assert "delete_project" not in names
    assert "create_task" not in names
    # shape: every tool carries an inputSchema + annotations
    sample = next(t for t in tools if t["name"] == "list_projects")
    assert "inputSchema" in sample
    assert sample["annotations"]["readOnlyHint"] is True


@pytest.mark.django_db
def test_tools_list_pro_includes_writes(http, user_a, make_profile):
    make_profile(user_a, plan="pro")
    resp = _rpc(http, _make_jwt(user_a), "tools/list")
    names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert {"create_task", "delete_project", "update_project"} <= names


# --------------------------------------------------------------------------
# tools/call — dispatch + policy + metrics
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_tools_call_success_records_connector_interaction(
    http, user_a, make_profile, make_project
):
    make_profile(user_a, plan="free")
    make_project(user_a, name="Alpha")
    resp = _rpc(
        http, _make_jwt(user_a), "tools/call", {"name": "list_projects", "arguments": {}}
    )
    payload, is_error = _tool_call_result(resp)
    assert is_error is False
    assert any(p["name"] == "Alpha" for p in payload["projects"])
    # A connector interaction was counted.
    row = InteractionDay.objects.get(user_id=user_a, source="connector")
    assert row.count == 1


@pytest.mark.django_db
def test_tools_call_free_write_denied_and_not_counted(
    http, user_a, make_profile, make_project
):
    make_profile(user_a, plan="free")
    p = make_project(user_a)
    resp = _rpc(
        http,
        _make_jwt(user_a),
        "tools/call",
        {"name": "delete_project", "arguments": {"id": str(p.id), "confirm": True}},
    )
    _payload, is_error = _tool_call_result(resp)
    assert is_error is True
    # Denied calls are not counted as interactions.
    assert not InteractionDay.objects.filter(
        user_id=user_a, source="connector"
    ).exists()


@pytest.mark.django_db
def test_tools_call_cross_user_idor(http, user_a, user_b, make_profile, make_project):
    make_profile(user_a, plan="pro")
    pb = make_project(user_b, name="B secret")
    resp = _rpc(
        http,
        _make_jwt(user_a),
        "tools/call",
        {"name": "get_project_detail", "arguments": {"id": str(pb.id)}},
    )
    _payload, is_error = _tool_call_result(resp)
    assert is_error is True


# --------------------------------------------------------------------------
# JSON-RPC error handling
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_unknown_method(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    resp = _rpc(http, _make_jwt(user_a), "drop/tables")
    assert resp.json()["error"]["code"] == -32601


@pytest.mark.django_db
def test_tools_call_missing_name(http, user_a, make_profile):
    make_profile(user_a, plan="pro")
    resp = _rpc(http, _make_jwt(user_a), "tools/call", {"arguments": {}})
    assert resp.json()["error"]["code"] == -32602


@pytest.mark.django_db
def test_per_plan_rate_limit(http, user_a, make_profile, settings):
    from django.core.cache import cache

    cache.clear()
    # Free gets a tiny ceiling; the 2nd call in the window is throttled.
    settings.MCP_RATE_LIMIT_BY_PLAN = {**settings.MCP_RATE_LIMIT_BY_PLAN, "free": "1/m"}
    make_profile(user_a, plan="free")
    token = _make_jwt(user_a)

    assert _rpc(http, token, "ping").status_code == 200
    assert _rpc(http, token, "ping").status_code == 429

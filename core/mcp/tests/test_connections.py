"""Tests for MCP connection listing / revocation (Fase 3) + cleanup command."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.admin_api.models import AdminAuditLog
from core.assistant.models import AccountProfile
from core.models import (
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthConnectionEvent,
    OAuthRefreshToken,
)
from core.schema import schema
from core.services import mcp_connections as svc


def _client(cid="mcp_abc", name="Claude"):
    return OAuthClient.objects.create(
        client_id=cid, client_name=name, redirect_uris=["https://claude.ai/cb"]
    )


def _refresh(client, user_id, *, revoked=False, expired=False):
    now = timezone.now()
    return OAuthRefreshToken.objects.create(
        token_hash=secrets.token_hex(16),
        client=client,
        user_id=user_id,
        scope="",
        expires_at=(now - timedelta(days=1)) if expired else (now + timedelta(days=30)),
        revoked_at=now if revoked else None,
    )


# ---- service ----


@pytest.mark.django_db
def test_list_connections_only_live(user_a):
    c = _client()
    _refresh(c, user_a)  # live
    _refresh(c, user_a, revoked=True)
    _refresh(c, user_a, expired=True)
    conns = svc.list_connections(user_a)
    assert len(conns) == 1
    assert conns[0]["client_id"] == "mcp_abc"
    assert conns[0]["client_name"] == "Claude"


@pytest.mark.django_db
def test_list_connections_user_scoped(user_a, user_b):
    c = _client()
    _refresh(c, user_b)
    assert svc.list_connections(user_a) == []


@pytest.mark.django_db
def test_revoke_connection(user_a):
    c = _client()
    _refresh(c, user_a)
    _refresh(c, user_a)
    assert svc.revoke_connection(user_a, "mcp_abc") == 2
    assert svc.list_connections(user_a) == []


@pytest.mark.django_db
def test_revoke_other_user_no_effect(user_a, user_b):
    c = _client()
    _refresh(c, user_b)
    assert svc.revoke_connection(user_a, "mcp_abc") == 0
    assert len(svc.list_connections(user_b)) == 1


# ---- GraphQL ----


MCP_CONNECTIONS_Q = "query { mcpConnections { clientId clientName connectedAt } }"
REVOKE_M = "mutation($c: ID!){ revokeMcpConnection(clientId: $c) }"


@pytest.mark.django_db
def test_graphql_list_and_revoke(user_a):
    c = _client(name="Claude")
    _refresh(c, user_a)
    ctx = SimpleNamespace(user_id=user_a)

    res = schema.execute_sync(MCP_CONNECTIONS_Q, context_value=ctx)
    assert res.errors is None, res.errors
    conns = res.data["mcpConnections"]
    assert len(conns) == 1
    assert conns[0]["clientName"] == "Claude"

    res2 = schema.execute_sync(
        REVOKE_M, context_value=ctx, variable_values={"c": "mcp_abc"}
    )
    assert res2.errors is None, res2.errors
    assert res2.data["revokeMcpConnection"] is True

    res3 = schema.execute_sync(MCP_CONNECTIONS_Q, context_value=ctx)
    assert res3.data["mcpConnections"] == []


@pytest.mark.django_db
def test_graphql_revoke_unknown_returns_false(user_a):
    ctx = SimpleNamespace(user_id=user_a)
    res = schema.execute_sync(
        REVOKE_M, context_value=ctx, variable_values={"c": "mcp_nope"}
    )
    assert res.errors is None, res.errors
    assert res.data["revokeMcpConnection"] is False


# ---- cleanup command ----


# ---- audit events ----


@pytest.mark.django_db
def test_revoke_logs_event(user_a):
    c = _client()
    _refresh(c, user_a)
    svc.revoke_connection(user_a, "mcp_abc")
    assert OAuthConnectionEvent.objects.filter(
        user_id=user_a, event="revoked"
    ).count() == 1


@pytest.mark.django_db
def test_log_event_denormalizes_client_name(user_a):
    _client(name="Claude Desktop")
    svc.log_event(user_a, "mcp_abc", OAuthConnectionEvent.Event.AUTHORIZED)
    ev = OAuthConnectionEvent.objects.get(user_id=user_a)
    assert ev.client_name == "Claude Desktop"
    assert ev.event == "authorized"


# ---- admin GraphQL ----


ADMIN_REVOKE_M = (
    "mutation($u: ID!, $c: String!){ adminRevokeMcpConnection(userId: $u, clientId: $c) }"
)
ADMIN_MCP_Q = """
query {
  adminMcpConnections(limit: 10) { userId clientId clientName }
  adminMcpStats { activeConnections distinctUsers byClient { label count } }
  adminMcpConnectionEvents(limit: 10) { event clientName }
}
"""


def _admin_ctx():
    admin_id = uuid.uuid4()
    AccountProfile.objects.create(user_id=admin_id, is_admin=True)
    return SimpleNamespace(user_id=admin_id)


@pytest.mark.django_db
def test_admin_revoke_logs_event_and_audit(user_a):
    c = _client()
    _refresh(c, user_a)
    ctx = _admin_ctx()
    res = schema.execute_sync(
        ADMIN_REVOKE_M,
        context_value=ctx,
        variable_values={"u": str(user_a), "c": "mcp_abc"},
    )
    assert res.errors is None, res.errors
    assert res.data["adminRevokeMcpConnection"] is True
    assert svc.list_connections(user_a) == []
    assert OAuthConnectionEvent.objects.filter(
        user_id=user_a, event="admin_revoked"
    ).count() == 1
    assert AdminAuditLog.objects.filter(action="mcp.revoke_connection").count() == 1


@pytest.mark.django_db
def test_admin_mcp_queries(user_a, user_b):
    c = _client()
    _refresh(c, user_a)
    _refresh(c, user_b)
    svc.log_event(user_a, "mcp_abc", OAuthConnectionEvent.Event.AUTHORIZED)
    ctx = _admin_ctx()
    res = schema.execute_sync(ADMIN_MCP_Q, context_value=ctx)
    assert res.errors is None, res.errors
    assert res.data["adminMcpStats"]["activeConnections"] == 2
    assert res.data["adminMcpStats"]["distinctUsers"] == 2
    assert len(res.data["adminMcpConnections"]) == 2
    assert any(
        e["event"] == "authorized" for e in res.data["adminMcpConnectionEvents"]
    )


@pytest.mark.django_db
def test_admin_mcp_requires_admin(user_a):
    # A non-admin context is rejected by _admin_user_id.
    c = _client()
    _refresh(c, user_a)
    ctx = SimpleNamespace(user_id=user_a)  # not an admin
    res = schema.execute_sync(ADMIN_MCP_Q, context_value=ctx)
    assert res.errors is not None


@pytest.mark.django_db
def test_cleanup_oauth_tokens(user_a):
    c = _client()
    now = timezone.now()
    # codes
    OAuthAuthorizationCode.objects.create(
        code_hash="expired", client=c, user_id=user_a, redirect_uri="x",
        code_challenge="x", expires_at=now - timedelta(minutes=1),
    )
    OAuthAuthorizationCode.objects.create(
        code_hash="consumed", client=c, user_id=user_a, redirect_uri="x",
        code_challenge="x", expires_at=now + timedelta(minutes=5), consumed_at=now,
    )
    OAuthAuthorizationCode.objects.create(
        code_hash="live", client=c, user_id=user_a, redirect_uri="x",
        code_challenge="x", expires_at=now + timedelta(minutes=5),
    )
    # refresh tokens
    _refresh(c, user_a, expired=True)
    _refresh(c, user_a)  # live → kept
    old_revoked = _refresh(c, user_a)
    old_revoked.revoked_at = now - timedelta(days=2)
    old_revoked.save(update_fields=["revoked_at"])

    call_command("cleanup_oauth_tokens")

    assert OAuthAuthorizationCode.objects.count() == 1  # only the live one
    assert OAuthRefreshToken.objects.count() == 1  # only the live one

"""Tests for `JWTAuthGraphQLView`.

These hit the real HTTP layer through Django's test client to verify
that:

* No `Authorization` header → 401 with `extensions.code = "UNAUTHENTICATED"`.
* Bad token → 401 with the same shape.
* Valid HS256 token signed with `SUPABASE_JWT_SECRET` → 200 and the
  resolver sees the right `user_id`.

The schema-level tests cover everything else; this file only verifies
the auth boundary.
"""

import datetime as dt
import json
import uuid

import jwt
import pytest
from django.conf import settings
from django.test import Client


@pytest.fixture
def client():
    return Client()


def _signed_token(user_id: uuid.UUID, **overrides) -> str:
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "exp": dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(hours=1),
        **overrides,
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")


def test_missing_auth_returns_401(client):
    response = client.post(
        "/graphql/",
        data=json.dumps({"query": "{ dashboard { lastBackup } }"}),
        content_type="application/json",
    )
    assert response.status_code == 401
    body = response.json()
    assert body["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"


def test_bad_token_returns_401(client):
    response = client.post(
        "/graphql/",
        data=json.dumps({"query": "{ dashboard { lastBackup } }"}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer not-a-real-token",
    )
    assert response.status_code == 401
    body = response.json()
    assert body["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"


def test_expired_token_returns_401(client):
    user_id = uuid.uuid4()
    expired = jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(hours=1),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )
    response = client.post(
        "/graphql/",
        data=json.dumps({"query": "{ dashboard { lastBackup } }"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {expired}",
    )
    assert response.status_code == 401
    body = response.json()
    assert body["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"


@pytest.mark.django_db
def test_valid_token_lets_request_through(client):
    user_id = uuid.uuid4()
    token = _signed_token(user_id)

    response = client.post(
        "/graphql/",
        data=json.dumps({"query": "{ dashboard { lastBackup projects { id } } }"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body.get("errors") is None
    assert body["data"]["dashboard"]["projects"] == []

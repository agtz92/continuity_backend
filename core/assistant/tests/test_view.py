"""End-to-end tests for the SSE chat endpoint with a fake Anthropic client."""

from __future__ import annotations

import datetime as dt
import json
from unittest import mock

import jwt
import pytest
from django.conf import settings as django_settings
from django.test import Client
from django.utils import timezone

from core import auth as auth_module
from core.assistant import anthropic_client
from core.assistant.models import Conversation, Message, UsageDay


@pytest.fixture(autouse=True)
def _force_test_auth_settings(settings, monkeypatch):
    """Pin auth settings for every test here.

    Mirrors `core/tests/test_auth_view.py` — a developer's .env file can
    leak a real SUPABASE_URL into settings, which would push the auth
    pipeline onto the JWKS path and bypass our HS256 fallback. Force the
    test values authoritatively.
    """
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


def _consume_sse(response) -> list[tuple[str, dict]]:
    body = b"".join(response.streaming_content).decode("utf-8")
    frames: list[tuple[str, dict]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        kind = ""
        data = {}
        for line in chunk.splitlines():
            if line.startswith("event: "):
                kind = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        frames.append((kind, data))
    return frames


@pytest.fixture
def http():
    return Client()


@pytest.mark.django_db
def test_chat_requires_auth(http):
    response = http.post(
        "/api/assistant/chat/",
        data=json.dumps({"content": "hello"}),
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_usage_endpoint_returns_snapshot(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    token = _make_jwt(user_a)
    response = http.get(
        "/api/assistant/usage/", HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["plan"] == "free"
    assert data["daily_message_cap"] == 20


@pytest.mark.django_db
def test_chat_streams_text_and_persists_message(
    http, user_a, make_profile, fake_anthropic
):
    make_profile(user_a, plan="free")
    token = _make_jwt(user_a)

    fake_client = fake_anthropic(
        [
            {
                "text": "Hello there!",
                "tool_uses": [],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 8,
                    "cache_creation_input_tokens": 0,
                },
            }
        ]
    )

    with mock.patch.object(
        anthropic_client, "_build_anthropic_client", return_value=fake_client
    ):
        response = http.post(
            "/api/assistant/chat/",
            data=json.dumps({"content": "Hi"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 200
        frames = _consume_sse(response)
    kinds = [k for k, _ in frames]
    assert "meta" in kinds
    assert "text_delta" in kinds
    assert "usage" in kinds
    assert "done" in kinds

    text_payload = next(p for k, p in frames if k == "text_delta")
    assert text_payload["text"] == "Hello there!"

    # Conversation + messages persisted.
    conv = Conversation.objects.get(user_id=user_a)
    assert Message.objects.filter(conversation=conv, role="user").count() == 1
    assert Message.objects.filter(conversation=conv, role="assistant").count() == 1

    usage_row = UsageDay.objects.get(user_id=user_a, date=timezone.now().date())
    assert usage_row.messages_sent == 1
    assert usage_row.tokens_in == 10
    assert usage_row.tokens_out == 5


@pytest.mark.django_db
def test_chat_executes_tool_use(http, user_a, make_profile, make_project, fake_anthropic):
    make_profile(user_a, plan="free")
    make_project(user_a, name="Telegram bot")
    token = _make_jwt(user_a)

    turns = [
        {
            "text": "",
            "tool_uses": [
                {"id": "tu_1", "name": "list_projects", "input": {"limit": 5}}
            ],
            "stop_reason": "tool_use",
        },
        {
            "text": "You have 1 project: Telegram bot.",
            "tool_uses": [],
            "stop_reason": "end_turn",
        },
    ]
    fake_client = fake_anthropic(turns)

    with mock.patch.object(
        anthropic_client, "_build_anthropic_client", return_value=fake_client
    ):
        response = http.post(
            "/api/assistant/chat/",
            data=json.dumps({"content": "List my projects"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 200
        frames = _consume_sse(response)
    kinds = [k for k, _ in frames]
    assert "tool_use_start" in kinds
    assert "tool_result" in kinds
    tool_result_payload = next(p for k, p in frames if k == "tool_result")
    assert tool_result_payload["name"] == "list_projects"
    assert any(
        proj.get("name") == "Telegram bot"
        for proj in tool_result_payload["output"].get("projects", [])
    )


@pytest.mark.django_db
def test_chat_rejects_oversized_input(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    token = _make_jwt(user_a)
    response = http.post(
        "/api/assistant/chat/",
        data=json.dumps({"content": "x" * 5000}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 413


@pytest.mark.django_db
def test_chat_blocked_when_quota_exceeded(http, user_a, make_profile):
    make_profile(user_a, plan="free")
    UsageDay.objects.create(
        user_id=user_a, date=timezone.now().date(), messages_sent=20
    )
    token = _make_jwt(user_a)
    response = http.post(
        "/api/assistant/chat/",
        data=json.dumps({"content": "Hi"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 429
    body = response.json()
    assert body["kind"] == "daily_messages"

"""User B can't reach user A's assistant conversations through any endpoint."""

import datetime as dt
import json

import jwt
import pytest
from django.conf import settings as django_settings
from django.test import Client

from core import auth as auth_module
from core.assistant.models import Conversation, Message

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _force_test_auth_settings(settings, monkeypatch):
    settings.SUPABASE_URL = ""
    settings.SUPABASE_JWT_SECRET = "test-jwt-secret"
    monkeypatch.setattr(auth_module, "_jwks_client", None)


def _auth(user_id):
    token = jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 3600,
        },
        django_settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@pytest.fixture
def a_conversation(user_a):
    conv = Conversation.objects.create(user_id=user_a, title="A secret plan")
    Message.objects.create(
        conversation=conv, role="user", content=[{"type": "text", "text": "A-only text"}]
    )
    return conv


def test_list_conversations_excludes_other_user(user_b, a_conversation, make_profile):
    make_profile(user_b, plan="studio")
    res = Client().get("/api/assistant/conversations/", **_auth(user_b))
    assert res.status_code == 200
    assert str(a_conversation.id) not in res.content.decode()
    assert "A secret plan" not in res.content.decode()


def test_read_other_users_messages_is_404(user_b, a_conversation, make_profile):
    make_profile(user_b, plan="studio")
    res = Client().get(
        f"/api/assistant/conversations/{a_conversation.id}/messages/", **_auth(user_b)
    )
    assert res.status_code == 404
    assert "A-only text" not in res.content.decode()


def test_chat_into_other_users_conversation_is_404(user_b, a_conversation, make_profile):
    make_profile(user_b, plan="studio")
    res = Client().post(
        "/api/assistant/chat/",
        data=json.dumps({"content": "hi", "conversation_id": str(a_conversation.id)}),
        content_type="application/json",
        **_auth(user_b),
    )
    assert res.status_code == 404
    assert a_conversation.messages.count() == 1


def test_cancel_other_users_conversation_is_404(user_b, a_conversation, make_profile):
    make_profile(user_b, plan="studio")
    res = Client().post(
        "/api/assistant/cancel/",
        data=json.dumps({"conversation_id": str(a_conversation.id)}),
        content_type="application/json",
        **_auth(user_b),
    )
    assert res.status_code == 404


def test_owner_still_reads_own_messages(user_a, a_conversation, make_profile):
    make_profile(user_a, plan="studio")
    res = Client().get(
        f"/api/assistant/conversations/{a_conversation.id}/messages/", **_auth(user_a)
    )
    assert res.status_code == 200
    assert "A-only text" in res.content.decode()

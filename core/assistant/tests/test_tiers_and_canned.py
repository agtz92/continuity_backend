"""Who gets which assistant, and what the deterministic one answers."""

from __future__ import annotations

import datetime as dt
import json

import jwt
import pytest
from django.conf import settings as django_settings
from django.test import Client
from django.utils import timezone

from core import auth as auth_module
from core.assistant import canned, tiers
from core.assistant.models import Conversation, Message, MessageRole
from core.notifications.models import NotificationSettings


@pytest.fixture(autouse=True)
def _force_test_auth_settings(settings, monkeypatch):
    settings.SUPABASE_URL = ""
    settings.SUPABASE_JWT_SECRET = "test-jwt-secret"
    monkeypatch.setattr(auth_module, "_jwks_client", None)


@pytest.fixture
def http():
    return Client()


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


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------


def test_each_plan_gets_exactly_one_assistant():
    assert tiers.assistant_mode("free") == "none"
    assert tiers.assistant_mode("pro") == "canned"
    assert tiers.assistant_mode("studio") == "llm"
    assert tiers.assistant_mode("admin") == "llm"


def test_an_unknown_plan_gets_the_poorest_assistant():
    assert tiers.assistant_mode("enterprise-platinum") == "none"
    assert not tiers.is_llm_tier("")


@pytest.mark.django_db
def test_usage_reports_the_mode_so_clients_stop_guessing(
    http, user_a, make_profile
):
    for plan, mode in (("free", "none"), ("pro", "canned"), ("studio", "llm")):
        make_profile(user_a, plan)
        resp = http.get(
            "/api/assistant/usage/", HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}"
        )
        assert resp.json()["assistant_mode"] == mode


# --------------------------------------------------------------------------
# Free: no assistant
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_free_cannot_chat_and_is_told_what_unlocks_it(http, user_a, make_profile):
    make_profile(user_a, "free")
    resp = http.post(
        "/api/assistant/chat/",
        data=json.dumps({"content": "Hi"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "plan_required"
    assert body["plan_required"] == "studio"


@pytest.mark.django_db
def test_free_has_no_action_catalogue_either(http, user_a, make_profile):
    make_profile(user_a, "free")
    resp = http.get(
        "/api/assistant/actions/", HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}"
    )
    assert resp.status_code == 403
    assert resp.json()["plan_required"] == "pro"


# --------------------------------------------------------------------------
# Pro: the catalogue, and nothing that costs money
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_pro_cannot_reach_the_model(http, user_a, make_profile):
    make_profile(user_a, "pro")
    for path, payload in (
        ("/api/assistant/chat/", {"content": "Hi"}),
        ("/api/assistant/parse-capture/", {"text": "comprar leche mañana"}),
    ):
        resp = http.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
        )
        assert resp.status_code == 403, path
        assert resp.json()["plan_required"] == "studio"


@pytest.mark.django_db
def test_catalogue_is_grouped_and_labelled(http, user_a, make_profile):
    make_profile(user_a, "pro")
    resp = http.get(
        "/api/assistant/actions/", HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}"
    )
    assert resp.status_code == 200
    groups = resp.json()["groups"]
    assert [g["group"] for g in groups] == canned.GROUP_ORDER
    ids = {a["id"] for g in groups for a in g["actions"]}
    assert ids == set(canned.ACTIONS)
    # Every action arrives ready to render: a label, and a placeholder only
    # for the one that takes text.
    for g in groups:
        for a in g["actions"]:
            assert a["label"]
            assert bool(a["placeholder"]) == a["needs_query"]


@pytest.mark.django_db
def test_running_an_action_answers_from_real_data(
    http, user_a, make_profile, make_project, make_task
):
    make_profile(user_a, "pro")
    p = make_project(user_a, name="ERP migration", status="active")
    make_task(
        user_a,
        project=p,
        title="Normalise addresses",
        due_date=timezone.now() - dt.timedelta(days=3),
    )

    resp = http.post(
        "/api/assistant/actions/overdue/",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )
    assert resp.status_code == 200
    body = resp.json()
    text = body["content"][0]["text"]
    assert "Normalise addresses" in text
    # Entity links, so the client can render a clickable chip rather than
    # dead text.
    assert "(task:" in text


@pytest.mark.django_db
def test_an_action_answers_in_the_users_language(
    http, user_a, make_profile, make_project
):
    make_profile(user_a, "pro")
    NotificationSettings.objects.update_or_create(
        user_id=user_a, defaults={"locale": "es"}
    )
    resp = http.post(
        "/api/assistant/actions/overdue/",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )
    # Nothing overdue: the empty state is server-rendered, so it must come
    # back in Spanish — the model isn't there to match the user's language.
    assert "vencido" in resp.json()["content"][0]["text"]


@pytest.mark.django_db
def test_an_action_persists_as_a_normal_turn(http, user_a, make_profile):
    make_profile(user_a, "pro")
    resp = http.post(
        "/api/assistant/actions/today_summary/",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )
    conv = Conversation.objects.get(id=resp.json()["conversation_id"])
    rows = list(Message.objects.filter(conversation=conv).order_by("created"))
    assert [r.role for r in rows] == [MessageRole.USER, MessageRole.ASSISTANT]
    # No model answered this, and the client can tell.
    assert rows[1].model == ""
    assert rows[1].stop_reason == "canned"


@pytest.mark.django_db
def test_the_catalogue_never_spends_quota(http, user_a, make_profile):
    """It never leaves our servers, so charging a message would invent a cost."""
    from core.assistant.models import UsageDay

    make_profile(user_a, "pro")
    http.post(
        "/api/assistant/actions/today_summary/",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )
    assert not UsageDay.objects.filter(user_id=user_a).exists()


@pytest.mark.django_db
def test_an_unknown_action_is_a_404_not_a_500(http, user_a, make_profile):
    make_profile(user_a, "pro")
    resp = http.post(
        "/api/assistant/actions/drop_database/",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_actions_are_scoped_to_the_caller(
    http, user_a, user_b, make_profile, make_project
):
    make_profile(user_a, "pro")
    make_project(user_b, name="Someone else's project", status="active")
    resp = http.post(
        "/api/assistant/actions/active_projects/",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )
    assert "Someone else's project" not in resp.json()["content"][0]["text"]


# --------------------------------------------------------------------------
# Studio: the deep model is the server's decision
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_deep_model_is_off_until_an_admin_turns_it_on(user_a, make_profile):
    from core.assistant import prompts
    from core.services import app_config

    make_profile(user_a, "studio")
    assert prompts.deep_mode_enabled() is False
    assert prompts.select_model("studio", deep=False) == django_settings.ASSISTANT_MODEL_FAST

    app_config.set("assistant_deep_enabled", True)
    assert prompts.deep_mode_enabled() is True
    assert prompts.select_model("studio", deep=True) == django_settings.ASSISTANT_MODEL_DEEP


@pytest.mark.django_db
def test_the_deep_switch_never_lifts_a_lower_tier(user_a, make_profile):
    from core.assistant import prompts
    from core.services import app_config

    app_config.set("assistant_deep_enabled", True)
    # Even asked for directly, a non-llm plan stays on the fast model.
    assert prompts.select_model("pro", deep=True) == django_settings.ASSISTANT_MODEL_FAST
    assert prompts.select_model("free", deep=True) == django_settings.ASSISTANT_MODEL_FAST

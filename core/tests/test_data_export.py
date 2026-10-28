"""Data export: complete, scoped to the person, and free of credentials."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import pytest

from core.account_deletion import USER_OWNED_MODELS
from core.assistant.models import AccountProfile, Conversation, Message
from core.models import (
    GoogleOAuthCredential,
    NoteSection,
    OAuthConnectionEvent,
    Project,
    QuickNote,
    Routine,
    Task,
    TaskBlocker,
)
from core.notifications.models import NotificationSettings
from core.services import data_export


def test_every_user_owned_model_is_exported_or_explicitly_skipped():
    exported = {m for _, m in data_export.SECTIONS}
    missing = [
        m.__name__
        for m in USER_OWNED_MODELS
        if m not in exported and m not in data_export.NOT_EXPORTED
    ]
    assert missing == [], f"Add to SECTIONS or NOT_EXPORTED: {missing}"


def test_every_column_of_an_exported_model_is_classified():
    unclassified, unknown = [], []
    for _, model in data_export.SECTIONS:
        columns = {f.attname for f in model._meta.concrete_fields} - {"user_id"}
        out = set(data_export.FIELDS[model])
        omitted = set(data_export.OMITTED_FIELDS.get(model, {}))
        unclassified += [f"{model.__name__}.{c}" for c in columns - out - omitted]
        unknown += [f"{model.__name__}.{c}" for c in (out | omitted) - columns]
    assert unclassified == [], f"Add to FIELDS or OMITTED_FIELDS: {unclassified}"
    assert unknown == [], f"Columns that no longer exist: {unknown}"


@pytest.mark.django_db
def test_export_includes_the_users_content_and_nothing_else():
    me, other = uuid.uuid4(), uuid.uuid4()
    p = Project.objects.create(user_id=me, name="Mío")
    a = Task.objects.create(user_id=me, project=p, title="A")
    b = Task.objects.create(user_id=me, title="B")
    TaskBlocker.objects.create(user_id=me, blocked_task=a, blocking_task=b)
    Routine.objects.create(user_id=me, title="Correr", start_date=dt.date(2026, 1, 1))
    note = QuickNote.objects.create(user_id=me, title="Cuaderno")
    NoteSection.objects.create(user_id=me, note=note, heading="Uno", body="texto")
    conv = Conversation.objects.create(user_id=me, title="Plan")
    Message.objects.create(conversation=conv, role="user", content=[{"type": "text", "text": "hola"}])
    GoogleOAuthCredential.objects.create(user_id=me, refresh_token="secret-refresh")
    Project.objects.create(user_id=other, name="Ajeno")

    data = data_export.build_export(me)

    assert [r["name"] for r in data["projects"]] == ["Mío"]
    assert {r["title"] for r in data["tasks"]} == {"A", "B"}
    assert data["tasks"][0]["project_id"] in (str(p.id), None)
    assert len(data["task_blockers"]) == 1
    assert [r["title"] for r in data["routines"]] == ["Correr"]
    assert data["quick_note_sections"][0]["body"] == "texto"
    assert data["assistant_conversations"][0]["messages"][0]["role"] == "user"

    text = json.dumps(data)
    assert "Ajeno" not in text
    assert "secret-refresh" not in text
    assert '"user_id"' not in text.replace('"account": {"user_id"', "")


@pytest.mark.django_db
def test_export_leaves_out_secrets_and_internals():
    me = uuid.uuid4()
    NotificationSettings.objects.create(user_id=me, calendar_feed_token="feed-secret", is_admin=True)
    AccountProfile.objects.create(user_id=me, plan="studio", is_billing_exempt=True, beta_cohort=True)
    Task.objects.create(user_id=me, title="T", client_token="tok-123", google_task_id="g-1")
    OAuthConnectionEvent.objects.create(user_id=me, client_id="mcp_abc", client_name="Claude", event="authorized")
    OAuthConnectionEvent.objects.create(user_id=me, client_id="mcp_abc", client_name="Claude", event="token_refreshed")
    conv = Conversation.objects.create(user_id=me, title="Plan")
    Message.objects.create(conversation=conv, role="user", content=[{"type": "text", "text": "crea una tarea"}])
    Message.objects.create(
        conversation=conv,
        role="assistant",
        model="claude-haiku",
        tokens_in=99,
        content=[
            {"type": "text", "text": "Listo"},
            {"type": "tool_use", "id": "toolu_1", "name": "create_task", "input": {"title": "X"}},
        ],
    )
    Message.objects.create(
        conversation=conv,
        role="tool",
        content=[{"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"ok": true}'}],
    )

    data = data_export.build_export(me)

    assert data["subscription"] == [
        {"plan": "studio", "plan_renews_at": None, "billing_source": "", "cancel_at_period_end": False}
    ]
    assert data["connector_events"] == [
        {"client_name": "Claude", "event": "authorized", "created": data["connector_events"][0]["created"]}
    ]
    msgs = data["assistant_conversations"][0]["messages"]
    assert [(m["role"], m["text"]) for m in msgs] == [("user", "crea una tarea"), ("assistant", "Listo")]
    assert set(msgs[0]) == {"role", "text", "created"}

    text = json.dumps(data)
    for leaked in (
        "feed-secret", "is_admin", "is_billing_exempt", "beta_cohort", "tok-123", "g-1",
        "mcp_abc", "token_refreshed", "claude-haiku", "tokens_in", "create_task", "toolu_1",
    ):
        assert leaked not in text, leaked


@pytest.mark.django_db
def test_my_data_export_query_returns_json(execute_query, user_a, monkeypatch):
    from core.admin_api import supabase_admin

    monkeypatch.setattr(supabase_admin, "get_user", lambda uid: SimpleNamespace(email="yo@ejemplo.com"))
    Project.objects.create(user_id=user_a, name="Exportable")
    res = execute_query("query { myDataExport }", user_a)
    assert not res.errors
    data = json.loads(res.data["myDataExport"])
    assert data["projects"][0]["name"] == "Exportable"
    assert data["account"]["email"] == "yo@ejemplo.com"


@pytest.mark.django_db
def test_my_data_export_still_works_without_the_email(execute_query, user_a, monkeypatch):
    from core.admin_api import supabase_admin

    def boom(uid):
        raise supabase_admin.SupabaseAdminError("down")

    monkeypatch.setattr(supabase_admin, "get_user", boom)
    res = execute_query("query { myDataExport }", user_a)
    assert not res.errors
    assert json.loads(res.data["myDataExport"])["account"]["email"] == ""

"""Data export: complete, scoped to the person, and free of credentials."""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest

from core.account_deletion import USER_OWNED_MODELS
from core.assistant.models import Conversation, Message
from core.models import (
    GoogleOAuthCredential,
    NoteSection,
    Project,
    QuickNote,
    Routine,
    Task,
    TaskBlocker,
)
from core.services import data_export


def test_every_user_owned_model_is_exported_or_explicitly_skipped():
    exported = {m for _, m in data_export.SECTIONS}
    missing = [
        m.__name__
        for m in USER_OWNED_MODELS
        if m not in exported and m not in data_export.NOT_EXPORTED
    ]
    assert missing == [], f"Add to SECTIONS or NOT_EXPORTED: {missing}"


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
def test_my_data_export_query_returns_json(execute_query, user_a):
    Project.objects.create(user_id=user_a, name="Exportable")
    res = execute_query("query { myDataExport }", user_a)
    assert not res.errors
    data = json.loads(res.data["myDataExport"])
    assert data["projects"][0]["name"] == "Exportable"

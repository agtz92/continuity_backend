"""Connector/assistant tools for the Quick Notes module (read=free, write=pro)."""

from __future__ import annotations

import pytest

from core.assistant import tools
from core.models import QuickNote
from core.services import quick_notes as qn_svc


@pytest.mark.django_db
def test_free_can_find_quick_notes(user_a):
    n = qn_svc.create_quick_note(user_a, title="Roadmap")
    qn_svc.add_section(user_a, n.id, heading="Q1", body="ship the connector")

    out = tools.call("list_quick_notes", user_a, {}, plan="free")
    assert any(x["title"] == "Roadmap" for x in out["quick_notes"])

    detail = tools.call("get_quick_note", user_a, {"id": str(n.id)}, plan="free")
    assert detail["title"] == "Roadmap"
    assert any("connector" in s["body"] for s in detail["sections"])


@pytest.mark.django_db
def test_list_quick_notes_user_scoped(user_a, user_b):
    qn_svc.create_quick_note(user_a, title="A note")
    qn_svc.create_quick_note(user_b, title="B note")
    out = tools.call("list_quick_notes", user_a, {}, plan="free")
    titles = [x["title"] for x in out["quick_notes"]]
    assert "A note" in titles
    assert "B note" not in titles


@pytest.mark.django_db
def test_get_quick_note_cross_user_blocked(user_a, user_b):
    n = qn_svc.create_quick_note(user_b, title="B secret")
    out = tools.call("get_quick_note", user_a, {"id": str(n.id)}, plan="free")
    assert "error" in out


@pytest.mark.django_db
def test_create_quick_note_requires_pro(user_a):
    out = tools.call("create_quick_note", user_a, {"title": "X"}, plan="free")
    assert "error" in out
    assert QuickNote.objects.filter(user_id=user_a).count() == 0

    out2 = tools.call("create_quick_note", user_a, {"title": "X"}, plan="pro")
    assert out2.get("ok") is True
    assert QuickNote.objects.filter(user_id=user_a).count() == 1


@pytest.mark.django_db
def test_quick_note_full_crud_pro(user_a):
    nid = tools.call("create_quick_note", user_a, {"title": "Plan"}, plan="pro")["id"]
    s = tools.call(
        "add_note_section",
        user_a,
        {"note_id": nid, "heading": "H", "body": "hello"},
        plan="pro",
    )
    assert s.get("ok") is True
    upd = tools.call(
        "update_quick_note", user_a, {"id": nid, "title": "Plan v2"}, plan="pro"
    )
    assert upd["title"] == "Plan v2"
    pin = tools.call(
        "set_quick_note_pinned", user_a, {"id": nid, "pinned": True}, plan="pro"
    )
    assert pin["pinned"] is True
    d = tools.call("delete_quick_note", user_a, {"id": nid}, plan="pro")
    assert d.get("deleted") == "quick_note"
    assert QuickNote.objects.filter(user_id=user_a).count() == 0


@pytest.mark.django_db
def test_search_includes_quick_notes(user_a):
    n = qn_svc.create_quick_note(user_a, title="Secret roadmap")
    qn_svc.add_section(user_a, n.id, heading="Launch", body="connector ships friday")
    out = tools.call("search", user_a, {"query": "connector ships"}, plan="free")
    assert "quick_note" in {h["kind"] for h in out["hits"]}

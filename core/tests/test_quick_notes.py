"""Quick Notes — GraphQL + service tests.

Covers CRUD, collapsible sections, reorder, ownership isolation, cascade
delete, and the SET_NULL behavior when a linked project/category is removed.
Runs against the schema directly via the `execute_query` fixture (conftest).
"""

from __future__ import annotations

import uuid

import pytest

from core.models import Category, NoteSection, Project, QuickNote
from core.services import quick_notes as svc
from core.services.projects import NotFoundError


# ---------- service layer ----------


@pytest.mark.django_db
def test_create_and_get_standalone_note(user_a):
    note = svc.create_quick_note(user_a, title="Cuentas banco HPK")
    assert note.title == "Cuentas banco HPK"
    assert note.category_id is None
    assert note.project_id is None
    fetched = svc.get_quick_note(user_a, note.id)
    assert fetched.id == note.id


@pytest.mark.django_db
def test_link_category_and_project(user_a):
    cat = Category.objects.create(user_id=user_a, name="Finanzas")
    proj = Project.objects.create(user_id=user_a, name="HPK")
    note = svc.create_quick_note(
        user_a, title="HPK", category_id=cat.id, project_id=proj.id
    )
    assert note.category_id == cat.id
    assert note.project_id == proj.id


@pytest.mark.django_db
def test_link_to_foreign_category_rejected(user_a, user_b):
    foreign = Category.objects.create(user_id=user_b, name="Ajeno")
    with pytest.raises(NotFoundError):
        svc.create_quick_note(user_a, title="x", category_id=foreign.id)


@pytest.mark.django_db
def test_ownership_isolation(user_a, user_b):
    note = svc.create_quick_note(user_a, title="privado")
    with pytest.raises(NotFoundError):
        svc.get_quick_note(user_b, note.id)
    # user_b's listing never sees it
    assert svc.list_quick_notes(user_b) == []


@pytest.mark.django_db
def test_sections_crud_and_ordering(user_a):
    note = svc.create_quick_note(user_a, title="N")
    s1 = svc.add_section(user_a, note.id, heading="A", body="aaa")
    s2 = svc.add_section(user_a, note.id, heading="B", body="bbb")
    s3 = svc.add_section(user_a, note.id, heading="C", body="ccc")
    assert [s.position for s in (s1, s2, s3)] == [0, 1, 2]

    svc.reorder_sections(user_a, note.id, [s3.id, s1.id, s2.id])
    ordered = list(
        NoteSection.objects.filter(note_id=note.id).order_by("position")
    )
    assert [s.heading for s in ordered] == ["C", "A", "B"]


@pytest.mark.django_db
def test_delete_note_cascades_sections(user_a):
    note = svc.create_quick_note(user_a, title="N")
    svc.add_section(user_a, note.id, heading="A")
    svc.add_section(user_a, note.id, heading="B")
    svc.delete_quick_note(user_a, note.id)
    assert NoteSection.objects.filter(note_id=note.id).count() == 0


@pytest.mark.django_db
def test_deleting_project_keeps_note(user_a):
    proj = Project.objects.create(user_id=user_a, name="P")
    note = svc.create_quick_note(user_a, title="N", project_id=proj.id)
    proj.delete()
    note.refresh_from_db()
    assert note.project_id is None  # SET_NULL, note survives


@pytest.mark.django_db
def test_search_matches_section_body(user_a):
    a = svc.create_quick_note(user_a, title="Banco")
    svc.add_section(user_a, a.id, heading="CLABE", body="0017800774449718")
    svc.create_quick_note(user_a, title="Otra cosa")
    hits = svc.list_quick_notes(user_a, search="00178007")
    assert [n.id for n in hits] == [a.id]


@pytest.mark.django_db
def test_section_quota_free_cap(user_a):
    from core.assistant.models import AccountProfile
    from core.quotas import EntityQuotaExceeded

    AccountProfile.objects.create(user_id=user_a, plan="free")
    note = svc.create_quick_note(user_a, title="N")
    for i in range(20):  # sections_per_note free cap = 20
        svc.add_section(user_a, note.id, heading=f"S{i}")
    with pytest.raises(EntityQuotaExceeded):
        svc.add_section(user_a, note.id, heading="overflow")


# ---------- GraphQL layer ----------


CREATE = """
mutation($data: QuickNoteInput!) {
  createQuickNote(data: $data) { id title pinned categoryId projectId }
}
"""

ADD_SECTION = """
mutation($noteId: ID!, $data: NoteSectionInput!) {
  addNoteSection(noteId: $noteId, data: $data) { id heading position collapsed }
}
"""

LIST = """
query { quickNotes { id title sections { heading position } } }
"""


@pytest.mark.django_db
def test_graphql_create_and_list(execute_query, user_a):
    res = execute_query(CREATE, user_id=user_a, variable_values={"data": {"title": "Hola"}})
    assert res.errors is None, res.errors
    note_id = res.data["createQuickNote"]["id"]

    res2 = execute_query(
        ADD_SECTION,
        user_id=user_a,
        variable_values={"noteId": note_id, "data": {"heading": "Sec", "body": "x"}},
    )
    assert res2.errors is None, res2.errors
    assert res2.data["addNoteSection"]["position"] == 0

    res3 = execute_query(LIST, user_id=user_a)
    assert res3.errors is None, res3.errors
    notes = res3.data["quickNotes"]
    assert len(notes) == 1
    assert notes[0]["sections"][0]["heading"] == "Sec"


@pytest.mark.django_db
def test_graphql_unauthenticated_rejected(execute_query):
    res = execute_query(LIST, user_id=None)
    assert res.errors is not None
    assert "UNAUTHENTICATED" in str(res.errors)

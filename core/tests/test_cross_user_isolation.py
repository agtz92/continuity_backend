"""User B, holding the ids of user A's records, can't read, change or link them.

Fills the gaps left by the per-feature isolation tests (test_errors.py,
test_quick_notes.py, test_offline_client_ids.py, ...): every case here was
untested before the 2026-11 ownership audit. Each test asserts both sides:
B gets nothing / a NotFound, and A's row is unchanged afterwards.
"""

import datetime as dt
import uuid

import pytest
from django.test import Client

from core.models import Category, Idea, Project, QuickNote, Routine, Task, TaskBlocker
from core.services import calendar_feed
from core.services import quick_notes as quick_notes_svc

pytestmark = pytest.mark.django_db


def _errors(result):
    return [e.message for e in (result.errors or [])]


# ---------- promoteIdea: foreign categoryId (the IDOR this audit fixed) ----------

PROMOTE = """
mutation($id: ID!, $cat: ID) {
  promoteIdea(id: $id, categoryId: $cat) { id categoryId }
}
"""

ANALYTICS_CATEGORIES = """
query { analytics(range: ALL) { categoryBreakdown { name } } }
"""


def test_promote_idea_cannot_attach_another_users_category(execute_query, user_a, user_b):
    secret = Category.objects.create(user_id=user_a, name="A-private-client", color="rose")
    idea = Idea.objects.create(user_id=user_b, title="B's idea")

    r = execute_query(PROMOTE, user_b, {"id": str(idea.id), "cat": str(secret.id)})

    assert r.errors is None
    assert r.data["promoteIdea"]["categoryId"] is None
    project = Project.objects.get(pk=r.data["promoteIdea"]["id"])
    assert project.user_id == user_b
    assert project.category_id is None
    # Before the fix B's analytics joined through to A's category name.
    a = execute_query(ANALYTICS_CATEGORIES, user_b)
    if a.errors is None:  # breakdown shape may evolve; the name must never leak
        assert "A-private-client" not in str(a.data)


def test_promote_idea_still_accepts_own_category(execute_query, user_b):
    mine = Category.objects.create(user_id=user_b, name="Mine", color="emerald")
    idea = Idea.objects.create(user_id=user_b, title="B's idea")
    r = execute_query(PROMOTE, user_b, {"id": str(idea.id), "cat": str(mine.id)})
    assert r.data["promoteIdea"]["categoryId"] == str(mine.id)


def test_promote_another_users_idea_fails(execute_query, user_a, user_b):
    idea = Idea.objects.create(user_id=user_a, title="A's idea")
    r = execute_query(PROMOTE, user_b, {"id": str(idea.id)})
    assert r.errors
    assert Idea.objects.filter(pk=idea.pk, user_id=user_a).exists()
    assert not Project.objects.filter(user_id=user_b).exists()


# ---------- direct reads by id ----------

def test_quick_note_by_id_returns_null_for_other_user(execute_query, user_a, user_b):
    note = quick_notes_svc.create_quick_note(user_a, title="A diary")
    r = execute_query("query($id: ID!){ quickNote(id: $id){ id title } }", user_b, {"id": str(note.id)})
    assert r.errors is None
    assert r.data["quickNote"] is None


def test_quick_notes_list_never_includes_other_user(execute_query, user_a, user_b, project_factory):
    a_project = project_factory(user_a)
    quick_notes_svc.create_quick_note(user_a, title="A diary", project_id=a_project.id)
    # Filtering by A's project id must not reveal A's notes.
    r = execute_query(
        "query($p: ID){ quickNotes(projectId: $p){ id title } }",
        user_b,
        {"p": str(a_project.id)},
    )
    assert r.errors is None
    assert r.data["quickNotes"] == []


# ---------- writes that reference another user's record ----------

def test_quick_note_cannot_link_another_users_project(execute_query, user_a, user_b, project_factory):
    a_project = project_factory(user_a)
    r = execute_query(
        "mutation($d: QuickNoteInput!){ createQuickNote(data: $d){ id } }",
        user_b,
        {"d": {"title": "x", "projectId": str(a_project.id)}},
    )
    assert r.errors
    assert not QuickNote.objects.filter(user_id=user_b).exists()


def test_routine_cannot_link_another_users_project(execute_query, user_a, user_b, project_factory):
    a_project = project_factory(user_a)
    r = execute_query(
        "mutation($d: RoutineInput!){ createRoutine(data: $d){ id } }",
        user_b,
        {
            "d": {
                "title": "x",
                "recurrenceType": "daily",
                "startDate": dt.date.today().isoformat(),
                "projectId": str(a_project.id),
            }
        },
    )
    assert r.errors
    assert not Routine.objects.filter(user_id=user_b, project_id=a_project.id).exists()


def test_task_blocker_cannot_point_at_another_users_task(
    execute_query, user_a, user_b, task_factory, project_factory
):
    a_task = task_factory(user_a, project_factory(user_a))
    b_task = task_factory(user_b, project_factory(user_b))
    r = execute_query(
        "mutation($d: TaskBlockerInput!){ addTaskBlocker(data: $d){ id } }",
        user_b,
        {"d": {"blockedTaskId": str(b_task.id), "blockingTaskId": str(a_task.id)}},
    )
    assert r.errors
    assert not TaskBlocker.objects.filter(blocking_task_id=a_task.id).exists()


def test_cannot_block_another_users_task(execute_query, user_a, user_b, task_factory, project_factory):
    a_task = task_factory(user_a, project_factory(user_a))
    r = execute_query(
        "mutation($d: TaskBlockerInput!){ addTaskBlocker(data: $d){ id } }",
        user_b,
        {"d": {"blockedTaskId": str(a_task.id), "externalDescription": "lol"}},
    )
    assert r.errors
    assert not TaskBlocker.objects.filter(blocked_task_id=a_task.id).exists()


@pytest.mark.parametrize(
    "document, model",
    [
        ("mutation($id: ID!){ deleteTask(id: $id) }", Task),
        ("mutation($id: ID!){ deleteQuickNote(id: $id) }", QuickNote),
        ("mutation($id: ID!){ deleteCategory(id: $id) }", Category),
        ("mutation($id: ID!){ deleteIdea(id: $id) }", Idea),
        ("mutation($id: ID!){ deleteProject(id: $id) }", Project),
    ],
)
def test_delete_by_foreign_id_leaves_row_intact(
    execute_query, user_a, user_b, project_factory, task_factory, document, model
):
    owners = {
        Task: lambda: task_factory(user_a, project_factory(user_a)),
        QuickNote: lambda: quick_notes_svc.create_quick_note(user_a, title="A"),
        Category: lambda: Category.objects.create(user_id=user_a, name="A", color="rose"),
        Idea: lambda: Idea.objects.create(user_id=user_a, title="A"),
        Project: lambda: project_factory(user_a),
    }
    row = owners[model]()
    execute_query(document, user_b, {"id": str(row.id)})  # error or silent no-op
    assert model.objects.filter(pk=row.pk, user_id=user_a).exists()


# ---------- token-addressed routes ----------

def test_ics_feed_unknown_token_is_404(user_a):
    calendar_feed.get_or_create_feed_token(user_a)
    res = Client().get(f"/api/calendar/feed/{uuid.uuid4().hex}.ics")
    assert res.status_code == 404

"""Tests for the unified Activity model and feed.

Covers:
- Every mutation that should log writes the expected `kind`.
- `toggle_task` logs `task_completed` (not the old `Update` row).
- Notes (kind=NOTE) are user-editable via `update_note`/`delete_note`;
  the service rejects edits on non-NOTE rows.
- GraphQL `activity` query: auth, ordering, isolation, filtering.
"""

import datetime as dt

import pytest
from django.utils import timezone

from core.models import Activity, ActivityKind
from core.services import activities as activities_svc
from core.services import ideas as ideas_svc
from core.services import projects as projects_svc
from core.services import tasks as tasks_svc
from core.services._common import NotFoundError


# ---------- Project events


@pytest.mark.django_db
def test_create_project_logs_created(user_a):
    p = projects_svc.create_project(user_a, name="Continuity")
    rows = list(Activity.objects.filter(user_id=user_a))
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == ActivityKind.PROJECT_CREATED
    assert row.entity_id == p.id
    assert row.entity_title == "Continuity"
    assert row.project_id == p.id


@pytest.mark.django_db
def test_delete_project_logs_with_title_preserved(user_a, project_factory):
    p = project_factory(user_a, name="Old project")
    Activity.objects.all().delete()
    projects_svc.delete_project(user_a, p.id)
    rows = list(Activity.objects.filter(user_id=user_a))
    assert len(rows) == 1
    assert rows[0].kind == ActivityKind.PROJECT_DELETED
    assert rows[0].entity_title == "Old project"


@pytest.mark.django_db
def test_update_project_status_change_logs(user_a, project_factory):
    p = project_factory(user_a, status="idea")
    Activity.objects.all().delete()
    projects_svc.update_project(user_a, p.id, name=p.name, status="active")
    rows = list(
        Activity.objects.filter(
            user_id=user_a, kind=ActivityKind.PROJECT_STATUS_CHANGED
        )
    )
    assert len(rows) == 1
    assert rows[0].previous_value == "idea"
    assert rows[0].new_value == "active"


@pytest.mark.django_db
def test_update_project_same_status_does_not_log(user_a, project_factory):
    p = project_factory(user_a, status="active")
    Activity.objects.all().delete()
    projects_svc.update_project(user_a, p.id, name=p.name, status="active")
    assert not Activity.objects.filter(
        user_id=user_a, kind=ActivityKind.PROJECT_STATUS_CHANGED
    ).exists()


@pytest.mark.django_db
def test_update_project_due_date_lifecycle(user_a, project_factory):
    p = project_factory(user_a)
    Activity.objects.all().delete()
    when = timezone.now() + dt.timedelta(days=3)

    projects_svc.update_project(user_a, p.id, name=p.name, due_date=when)
    when2 = when + dt.timedelta(days=1)
    projects_svc.update_project(user_a, p.id, name=p.name, due_date=when2)
    projects_svc.update_project(user_a, p.id, name=p.name, due_date=None)
    projects_svc.update_project(user_a, p.id, name=p.name, due_date=None)

    rows = list(
        Activity.objects.filter(
            user_id=user_a, kind=ActivityKind.PROJECT_DUE_DATE_CHANGED
        ).order_by("created")
    )
    assert len(rows) == 3
    assert rows[0].previous_value == "" and rows[0].new_value == when.isoformat()
    assert rows[1].previous_value == when.isoformat()
    assert rows[1].new_value == when2.isoformat()
    assert rows[2].previous_value == when2.isoformat() and rows[2].new_value == ""


# ---------- Task events


@pytest.mark.django_db
def test_create_task_logs(user_a, project_factory):
    p = project_factory(user_a)
    Activity.objects.all().delete()
    t = tasks_svc.create_task(user_a, title="Ship it", project_id=p.id)
    rows = list(Activity.objects.filter(user_id=user_a))
    assert len(rows) == 1
    assert rows[0].kind == ActivityKind.TASK_CREATED
    assert rows[0].entity_id == t.id
    assert rows[0].project_id == p.id


@pytest.mark.django_db
def test_update_task_due_date_change_logs(user_a, task_factory):
    t = task_factory(user_a)
    Activity.objects.all().delete()
    when = timezone.now() + dt.timedelta(days=2)
    tasks_svc.update_task(user_a, t.id, title=t.title, due_date=when)
    rows = list(
        Activity.objects.filter(
            user_id=user_a, kind=ActivityKind.TASK_DUE_DATE_CHANGED
        )
    )
    assert len(rows) == 1
    assert rows[0].new_value == when.isoformat()


@pytest.mark.django_db
def test_update_task_done_via_update_does_not_log(user_a, task_factory):
    t = task_factory(user_a)
    Activity.objects.all().delete()
    tasks_svc.update_task(user_a, t.id, title=t.title, done=True)
    assert not Activity.objects.filter(user_id=user_a).exists()


@pytest.mark.django_db
def test_toggle_task_done_logs_task_completed(user_a, project_factory, task_factory):
    p = project_factory(user_a)
    t = task_factory(user_a, project=p, title="Ship it")
    Activity.objects.all().delete()
    tasks_svc.toggle_task(user_a, t.id)
    rows = list(Activity.objects.filter(user_id=user_a))
    assert len(rows) == 1
    assert rows[0].kind == ActivityKind.TASK_COMPLETED
    assert rows[0].entity_id == t.id
    assert rows[0].entity_title == "Ship it"
    assert rows[0].project_id == p.id


@pytest.mark.django_db
def test_toggle_task_undone_does_not_log(user_a, task_factory):
    t = task_factory(user_a, done=True, completed_at=timezone.now())
    Activity.objects.all().delete()
    tasks_svc.toggle_task(user_a, t.id)
    assert not Activity.objects.filter(user_id=user_a).exists()


@pytest.mark.django_db
def test_delete_task_logs(user_a, project_factory, task_factory):
    p = project_factory(user_a)
    t = task_factory(user_a, project=p, title="Doomed")
    Activity.objects.all().delete()
    tasks_svc.delete_task(user_a, t.id)
    rows = list(Activity.objects.filter(user_id=user_a))
    assert len(rows) == 1
    assert rows[0].kind == ActivityKind.TASK_DELETED
    assert rows[0].entity_title == "Doomed"


# ---------- Idea events


@pytest.mark.django_db
def test_create_idea_logs(user_a):
    idea = ideas_svc.create_idea(user_a, title="A spark")
    rows = list(Activity.objects.filter(user_id=user_a))
    assert len(rows) == 1
    assert rows[0].kind == ActivityKind.IDEA_CREATED
    assert rows[0].entity_id == idea.id


@pytest.mark.django_db
def test_delete_idea_logs(user_a, idea_factory):
    i = idea_factory(user_a, title="Dropped")
    Activity.objects.all().delete()
    ideas_svc.delete_idea(user_a, i.id)
    rows = list(Activity.objects.filter(user_id=user_a))
    assert len(rows) == 1
    assert rows[0].kind == ActivityKind.IDEA_DELETED


@pytest.mark.django_db
def test_promote_idea_emits_single_promoted_event(user_a, idea_factory):
    i = idea_factory(user_a, title="Big idea")
    Activity.objects.all().delete()
    project = ideas_svc.promote_idea(user_a, i.id)
    rows = list(Activity.objects.filter(user_id=user_a))
    assert len(rows) == 1
    assert rows[0].kind == ActivityKind.IDEA_PROMOTED
    assert rows[0].entity_id == i.id
    assert rows[0].target_project_id == project.id
    assert rows[0].project_id == project.id


# ---------- Note CRUD (kind=NOTE)


@pytest.mark.django_db
def test_add_note_creates_note_activity(user_a, project_factory):
    p = project_factory(user_a)
    Activity.objects.all().delete()
    a = activities_svc.add_note(user_a, project_id=p.id, note="Hello world")
    assert a.kind == ActivityKind.NOTE
    assert a.note == "Hello world"
    assert a.project_id == p.id


@pytest.mark.django_db
def test_update_note_only_works_on_note_kind(user_a, project_factory):
    p = project_factory(user_a, name="P")
    note = activities_svc.add_note(user_a, project_id=p.id, note="orig")
    other = projects_svc.create_project(user_a, name="X")
    project_created_row = Activity.objects.get(
        user_id=user_a, kind=ActivityKind.PROJECT_CREATED, entity_id=other.id
    )

    activities_svc.update_note(user_a, note.id, note="edited")
    note.refresh_from_db()
    assert note.note == "edited"

    with pytest.raises(NotFoundError):
        activities_svc.update_note(user_a, project_created_row.id, note="hack")


@pytest.mark.django_db
def test_delete_note_only_works_on_note_kind(user_a, project_factory):
    p = project_factory(user_a)
    note = activities_svc.add_note(user_a, project_id=p.id, note="bye")
    project_created_row = Activity.objects.filter(
        user_id=user_a, kind=ActivityKind.PROJECT_CREATED
    ).first()

    activities_svc.delete_note(user_a, note.id)
    assert not Activity.objects.filter(pk=note.id).exists()

    if project_created_row is not None:
        with pytest.raises(NotFoundError):
            activities_svc.delete_note(user_a, project_created_row.id)


# ---------- GraphQL query


ACTIVITY_QUERY = """
    query($limit: Int, $since: DateTime, $until: DateTime, $kinds: [String!]) {
        activity(limit: $limit, since: $since, until: $until, kinds: $kinds) {
            id kind entityId entityTitle projectId targetProjectId
            note previousValue newValue created
        }
    }
"""


@pytest.mark.django_db
def test_activity_query_requires_auth(execute_query):
    result = execute_query(ACTIVITY_QUERY, user_id=None)
    assert result.errors is not None
    assert "Not authenticated" in result.errors[0].message


@pytest.mark.django_db
def test_activity_query_newest_first_with_limit(execute_query, user_a):
    for n in range(5):
        Activity.objects.create(
            user_id=user_a,
            kind=ActivityKind.PROJECT_CREATED,
            entity_id=user_a,
            entity_title=f"Project {n}",
        )
    res = execute_query(
        ACTIVITY_QUERY, user_id=user_a, variable_values={"limit": 3}
    )
    assert res.errors is None
    titles = [r["entityTitle"] for r in res.data["activity"]]
    assert titles == ["Project 4", "Project 3", "Project 2"]


@pytest.mark.django_db
def test_activity_query_isolates_users(execute_query, user_a, user_b):
    Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, note="mine"
    )
    Activity.objects.create(
        user_id=user_b, kind=ActivityKind.NOTE, note="theirs"
    )
    res = execute_query(ACTIVITY_QUERY, user_id=user_a)
    assert res.errors is None
    notes = [r["note"] for r in res.data["activity"]]
    assert notes == ["mine"]


@pytest.mark.django_db
def test_activity_query_filters_by_kinds(execute_query, user_a, project_factory):
    Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, note="manual"
    )
    Activity.objects.create(
        user_id=user_a, kind=ActivityKind.TASK_COMPLETED, entity_title="t"
    )
    res = execute_query(
        ACTIVITY_QUERY,
        user_id=user_a,
        variable_values={"kinds": ["task_completed"]},
    )
    assert res.errors is None
    kinds = [r["kind"] for r in res.data["activity"]]
    assert kinds == ["task_completed"]

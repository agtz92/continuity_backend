"""Backup restore: atomic, complete, remapped ids, no duplicates on merge."""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from django.utils import timezone

from core.assistant.models import AccountProfile
from core.models import (
    Activity,
    Category,
    Idea,
    NoteSection,
    Project,
    ProjectNote,
    QuickNote,
    Routine,
    RoutineOccurrence,
    Task,
    TaskBlocker,
)
from core.services import backup_restore
from core.services.data_export import build_export

RESTORE = """
mutation($data: String!, $mode: String!) {
  restoreBackup(data: $data, mode: $mode) { projects tasks routines quickNotes activity }
}
"""

OLD = timezone.make_aware(dt.datetime(2026, 3, 1, 12, 0))


def _studio(uid):
    AccountProfile.objects.create(user_id=uid, plan="studio")


def _seed(uid):
    cat = Category.objects.create(user_id=uid, name="Trabajo", color="emerald")
    p = Project.objects.create(
        user_id=uid, name="Viejo", status="killed", priority="high", category=cat,
        killed_reason="sin tiempo", killed_learnings="menos alcance",
    )
    a = Task.objects.create(user_id=uid, project=p, title="A", done=True, completed_at=OLD)
    b = Task.objects.create(user_id=uid, project=p, title="B")
    TaskBlocker.objects.create(user_id=uid, blocked_task=b, blocking_task=a)
    ProjectNote.objects.create(user_id=uid, project=p, title="Nota", body="cuerpo")
    r = Routine.objects.create(user_id=uid, title="Correr", recurrence_type="once", start_date=dt.date(2026, 1, 1), project=p)
    RoutineOccurrence.objects.create(user_id=uid, routine=r, scheduled_date=dt.date(2026, 1, 2), completed_at=OLD)
    Idea.objects.create(user_id=uid, title="Idea")
    qn = QuickNote.objects.create(user_id=uid, title="Cuaderno", category=cat, project=p)
    NoteSection.objects.create(user_id=uid, note=qn, heading="Uno", body="texto")
    Activity.objects.create(user_id=uid, kind="task_completed", entity_id=a.id, entity_title="A", project_id=p.id)
    Project.objects.filter(pk=p.pk).update(created=OLD)
    return p


def _file(uid) -> dict:
    return backup_restore.parse_backup(json.dumps(build_export(uid)))


@pytest.mark.django_db
def test_replace_restores_everything_into_another_account_with_new_ids():
    me, other = uuid.uuid4(), uuid.uuid4()
    _studio(other)
    original = _seed(me)
    Project.objects.create(user_id=other, name="Se va")

    created = backup_restore.restore_backup(other, _file(me), mode="replace")

    assert created["projects"] == 1 and created["tasks"] == 2 and created["activity"] == 1
    p = Project.objects.get(user_id=other)
    assert p.name == "Viejo" and p.pk != original.pk
    assert (p.status, p.priority, p.killed_reason) == ("killed", "high", "sin tiempo")
    assert p.created == OLD
    assert p.category.name == "Trabajo" and p.category.user_id == other
    done = Task.objects.get(user_id=other, title="A")
    assert done.project_id == p.pk and done.done and done.completed_at == OLD
    blocker = TaskBlocker.objects.get(user_id=other)
    assert blocker.blocked_task.title == "B" and blocker.blocking_task_id == done.pk
    assert ProjectNote.objects.get(user_id=other).project_id == p.pk
    occ = RoutineOccurrence.objects.get(user_id=other)
    assert occ.routine.user_id == other and occ.routine.project_id == p.pk
    section = NoteSection.objects.get(user_id=other)
    assert section.note.project_id == p.pk and section.body == "texto"
    act = Activity.objects.get(user_id=other)
    assert act.project_id == p.pk and act.entity_id == done.pk
    # The source account is untouched.
    assert Project.objects.filter(user_id=me).count() == 1


@pytest.mark.django_db
def test_merge_twice_does_not_duplicate():
    me = uuid.uuid4()
    _studio(me)
    _seed(me)
    data = _file(me)

    created = backup_restore.restore_backup(me, data, mode="merge")
    backup_restore.restore_backup(me, data, mode="merge")

    assert all(n == 0 for n in created.values())
    assert Project.objects.filter(user_id=me).count() == 1
    assert Task.objects.filter(user_id=me).count() == 2
    assert Category.objects.filter(user_id=me).count() == 1


@pytest.mark.django_db
def test_invalid_row_writes_nothing():
    me = uuid.uuid4()
    _studio(me)
    Project.objects.create(user_id=me, name="Mío")
    data = {"projects": [{"id": str(uuid.uuid4()), "name": "Bien"}, {"name": "Mal", "status": "nope"}]}

    with pytest.raises(backup_restore.BackupInvalid, match=r"projects\[1\]\.status"):
        backup_restore.restore_backup(me, data, mode="replace")

    assert list(Project.objects.filter(user_id=me).values_list("name", flat=True)) == ["Mío"]


@pytest.mark.django_db
def test_legacy_client_backup_is_converted_and_keeps_routines():
    me = uuid.uuid4()
    _studio(me)
    Routine.objects.create(user_id=me, title="Se queda", start_date=dt.date(2026, 1, 1))
    pid, tid = str(uuid.uuid4()), str(uuid.uuid4())
    legacy = {
        "version": 2,
        "exportedAt": "2026-06-09T19:50:20Z",
        "projects": [{"id": pid, "name": "Legacy", "nextStep": "algo", "status": "ACTIVE", "daysSinceTouch": 3}],
        "tasks": [{"id": tid, "title": "T", "projectId": pid, "done": False, "blockers": [
            {"id": str(uuid.uuid4()), "blockedTaskId": tid, "blockingTaskId": None, "externalDescription": "espera"}
        ]}],
        "ideas": [],
        "activities": [{"id": str(uuid.uuid4()), "kind": "NOTE", "projectId": pid, "note": "hola", "created": "2026-05-01T00:00:00Z"}],
        "projectNotes": [{"id": str(uuid.uuid4()), "projectId": pid, "title": "", "body": "n"}],
    }

    backup_restore.restore_backup(me, backup_restore.parse_backup(json.dumps(legacy)), mode="replace")

    p = Project.objects.get(user_id=me)
    assert (p.name, p.next_step, p.status) == ("Legacy", "algo", "active")
    assert Task.objects.get(user_id=me).project_id == p.pk
    assert TaskBlocker.objects.get(user_id=me).external_description == "espera"
    assert Activity.objects.get(user_id=me).note == "hola"
    assert ProjectNote.objects.get(user_id=me).body == "n"
    assert Routine.objects.filter(user_id=me, title="Se queda").exists()


@pytest.mark.django_db
def test_quota_overrun_rolls_back_and_reports(execute_query, user_a):
    # No profile → free plan: 3 active projects.
    data = {"projects": [{"name": f"P{i}", "status": "active"} for i in range(4)]}
    res = execute_query(RESTORE, user_a, variable_values={"data": json.dumps(data), "mode": "merge"})
    assert res.errors and res.errors[0].extensions["code"] == "QUOTA_EXCEEDED"
    assert not Project.objects.filter(user_id=user_a).exists()


@pytest.mark.django_db
def test_mutation_restores_and_rejects_garbage(execute_query, user_a):
    _studio(user_a)
    data = {"projects": [{"name": "Uno"}], "routines": [{"title": "R", "recurrence_type": "once", "start_date": "2026-01-01"}]}
    res = execute_query(RESTORE, user_a, variable_values={"data": json.dumps(data), "mode": "replace"})
    assert not res.errors
    assert res.data["restoreBackup"]["projects"] == 1
    assert res.data["restoreBackup"]["routines"] == 1

    bad = execute_query(RESTORE, user_a, variable_values={"data": "no es json", "mode": "merge"})
    assert bad.errors[0].extensions["code"] == "BAD_INPUT"
    bad_mode = execute_query(RESTORE, user_a, variable_values={"data": json.dumps(data), "mode": "wipe"})
    assert bad_mode.errors[0].extensions["code"] == "BAD_INPUT"

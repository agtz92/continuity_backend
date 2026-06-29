"""State closure system: stalled auto-detection, closure-note validation,
cap counting for killed, and revive (docs/_archive/state-closure/STATE_CLOSURE_FINAL.md)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.assistant.models import AccountProfile
from core.models import (
    Activity,
    ActivityKind,
    GraveyardInsight,
    Project,
    ProjectStatus,
    StalledSweepState,
)
from core.quotas import EntityQuotaExceeded
from core.services import projects as projects_svc
from core.services.stalled import STALLED_THRESHOLD_DAYS, detect_and_mark_stalled


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture(autouse=True)
def _stalled_cutoff_in_past(db):
    # Most tests assume the feature has been live a while, so the avalanche
    # cutoff has already passed and detection runs normally. The first-run /
    # grace-window behavior is covered explicitly in its own test.
    StalledSweepState.objects.update_or_create(
        pk=1, defaults={"cutoff_at": timezone.now() - dt.timedelta(days=60)}
    )


def _mk(user, status, *, days_idle=0, name="proj"):
    p = Project.objects.create(user_id=user, name=name, status=status)
    if days_idle:
        old = timezone.now() - dt.timedelta(days=days_idle)
        Project.objects.filter(pk=p.pk).update(last_activity=old)
    return Project.objects.get(pk=p.pk)


# ----- stalled auto-detection (D4/D9) -----

@pytest.mark.django_db
def test_stalls_old_active(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE, days_idle=STALLED_THRESHOLD_DAYS + 1)
    changed = detect_and_mark_stalled(user_id)
    assert len(changed) == 1
    p.refresh_from_db()
    assert p.status == ProjectStatus.STALLED
    assert p.stalled_at is not None
    assert Activity.objects.filter(
        kind=ActivityKind.PROJECT_STATUS_CHANGED, project_id=p.id
    ).exists()


@pytest.mark.django_db
def test_ignores_recent_active(user_id):
    _mk(user_id, ProjectStatus.ACTIVE, days_idle=3)
    assert detect_and_mark_stalled(user_id) == []


@pytest.mark.django_db
def test_idea_never_auto_stalls(user_id):
    _mk(user_id, ProjectStatus.IDEA, days_idle=STALLED_THRESHOLD_DAYS + 30)
    assert detect_and_mark_stalled(user_id) == []


@pytest.mark.django_db
def test_cutoff_prevents_avalanche_on_first_run(user_id):
    # Fresh deployment: no cutoff stamped yet. Even very old active projects must
    # NOT stall during the grace window (avoids day-1 avalanche).
    StalledSweepState.objects.all().delete()
    _mk(user_id, ProjectStatus.ACTIVE, days_idle=120)
    assert detect_and_mark_stalled(user_id) == []  # first run stamps cutoff, stalls nothing
    assert detect_and_mark_stalled(user_id) == []  # still inside the grace window


# ----- closure-note validation (D2) -----

@pytest.mark.django_db
def test_pause_requires_notes(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    with pytest.raises(ValidationError):
        projects_svc.update_project(user_id, p.id, name=p.name, status="paused")


@pytest.mark.django_db
def test_pause_with_notes_sets_fields(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    projects_svc.update_project(
        user_id, p.id, name=p.name, status="paused",
        paused_context="stopped at hero", paused_next_action="write pricing copy",
    )
    p.refresh_from_db()
    assert p.status == ProjectStatus.PAUSED
    assert p.paused_at is not None
    assert p.paused_context == "stopped at hero"


@pytest.mark.django_db
def test_kill_requires_notes(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    with pytest.raises(ValidationError):
        projects_svc.update_project(
            user_id, p.id, name=p.name, status="killed", killed_reason="x"
        )  # missing killed_learnings


@pytest.mark.django_db
def test_kill_then_revive_clears_killed_at_keeps_notes(user_id):
    AccountProfile.objects.create(user_id=user_id, plan="pro")
    p = _mk(user_id, ProjectStatus.ACTIVE)
    projects_svc.update_project(
        user_id, p.id, name=p.name, status="killed",
        killed_reason="scope creep", killed_learnings="ship mvp first",
    )
    p.refresh_from_db()
    assert p.status == ProjectStatus.KILLED and p.killed_at is not None
    # revive -> active
    projects_svc.update_project(user_id, p.id, name=p.name, status="active")
    p.refresh_from_db()
    assert p.status == ProjectStatus.ACTIVE
    assert p.killed_at is None
    assert p.killed_reason == "scope creep"  # notes kept for history


# ----- cap counting (D3) -----

@pytest.mark.django_db
def test_killed_does_not_count_against_cap(user_id):
    AccountProfile.objects.create(user_id=user_id, plan="free")  # cap = 3
    a = _mk(user_id, ProjectStatus.ACTIVE, name="a")
    _mk(user_id, ProjectStatus.ACTIVE, name="b")
    _mk(user_id, ProjectStatus.ACTIVE, name="c")
    # at cap: 4th create blocked
    with pytest.raises(EntityQuotaExceeded):
        projects_svc.create_project(user_id, name="d")
    # killing one frees a slot
    projects_svc.update_project(
        user_id, a.id, name=a.name, status="killed",
        killed_reason="r", killed_learnings="l",
    )
    projects_svc.create_project(user_id, name="d")  # now allowed
    assert Project.objects.filter(user_id=user_id).exclude(
        status__in=["archived", "killed"]
    ).count() == 3


@pytest.mark.django_db
def test_revive_over_cap_is_blocked(user_id):
    AccountProfile.objects.create(user_id=user_id, plan="free")  # cap = 3
    killed = _mk(user_id, ProjectStatus.ACTIVE, name="dead")
    projects_svc.update_project(
        user_id, killed.id, name=killed.name, status="killed",
        killed_reason="r", killed_learnings="l",
    )
    # fill the cap with 3 live projects
    _mk(user_id, ProjectStatus.ACTIVE, name="a")
    _mk(user_id, ProjectStatus.ACTIVE, name="b")
    _mk(user_id, ProjectStatus.ACTIVE, name="c")
    with pytest.raises(EntityQuotaExceeded):
        projects_svc.update_project(user_id, killed.id, name=killed.name, status="active")


# ----- autopsy hook is best-effort (D12) -----

@pytest.mark.django_db
def test_kill_without_api_key_is_noop_but_kill_succeeds(user_id, settings):
    settings.ANTHROPIC_API_KEY = ""
    AccountProfile.objects.create(user_id=user_id, plan="pro")
    p = _mk(user_id, ProjectStatus.ACTIVE)
    projects_svc.update_project(
        user_id, p.id, name=p.name, status="killed",
        killed_reason="r", killed_learnings="l",
    )
    p.refresh_from_db()
    assert p.status == ProjectStatus.KILLED
    assert p.killed_ai_reflection == ""  # no model call without a key


@pytest.mark.django_db
def test_revive_marks_graveyard_pattern_stale(user_id, settings):
    settings.ANTHROPIC_API_KEY = ""
    AccountProfile.objects.create(user_id=user_id, plan="pro")
    GraveyardInsight.objects.create(
        user_id=user_id, body="prior pattern", deaths_count=3, is_stale=False
    )
    p = _mk(user_id, ProjectStatus.ACTIVE)
    projects_svc.update_project(
        user_id, p.id, name=p.name, status="killed",
        killed_reason="r", killed_learnings="l",
    )
    projects_svc.update_project(user_id, p.id, name=p.name, status="active")  # revive
    assert GraveyardInsight.objects.get(user_id=user_id).is_stale is True


# ----- task due-date parking on closure (state-closure parking) -----

from core.models import Routine, Task  # noqa: E402
from core.services import routines as routines_svc  # noqa: E402
from core.services import tasks as tasks_svc  # noqa: E402


def _pause(user, p):
    return projects_svc.update_project(
        user, p.id, name=p.name, status="paused",
        paused_context="stopping here", paused_next_action="resume X",
    )


@pytest.mark.django_db
def test_pausing_parks_open_task_due_dates(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    due = timezone.now() + dt.timedelta(days=3)
    t = tasks_svc.create_task(user_id, title="ship", project_id=p.id, due_date=due)
    _pause(user_id, p)
    t.refresh_from_db()
    assert t.due_date is None
    assert t.parked_due_date == due


@pytest.mark.django_db
def test_parking_skips_done_and_dateless_tasks(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    done = tasks_svc.create_task(
        user_id, title="done", project_id=p.id,
        due_date=timezone.now(), done=True,
    )
    no_date = tasks_svc.create_task(user_id, title="someday", project_id=p.id)
    _pause(user_id, p)
    done.refresh_from_db()
    no_date.refresh_from_db()
    assert done.due_date is not None and done.parked_due_date is None
    assert no_date.parked_due_date is None


@pytest.mark.django_db
def test_paused_to_killed_keeps_existing_snapshot(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    due = timezone.now() + dt.timedelta(days=2)
    t = tasks_svc.create_task(user_id, title="x", project_id=p.id, due_date=due)
    _pause(user_id, p)
    projects_svc.update_project(
        user_id, p.id, name=p.name, status="killed",
        killed_reason="r", killed_learnings="l",
    )
    t.refresh_from_db()
    assert t.due_date is None and t.parked_due_date == due  # not double-parked to None


@pytest.mark.django_db
def test_revive_does_not_autorestore(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    due = timezone.now() + dt.timedelta(days=4)
    t = tasks_svc.create_task(user_id, title="x", project_id=p.id, due_date=due)
    _pause(user_id, p)
    projects_svc.update_project(user_id, p.id, name=p.name, status="active")
    t.refresh_from_db()
    assert t.due_date is None  # suggest, not auto
    assert t.parked_due_date == due  # snapshot retained as the reschedule hint


@pytest.mark.django_db
def test_restore_parked_reapplies_and_clears(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    due = timezone.now() + dt.timedelta(days=4)
    t = tasks_svc.create_task(user_id, title="x", project_id=p.id, due_date=due)
    _pause(user_id, p)
    n = tasks_svc.restore_parked_due_dates(user_id, p.id)
    t.refresh_from_db()
    assert n == 1
    assert t.due_date == due and t.parked_due_date is None


@pytest.mark.django_db
def test_dismiss_parked_clears_without_restoring(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    due = timezone.now() + dt.timedelta(days=4)
    t = tasks_svc.create_task(user_id, title="x", project_id=p.id, due_date=due)
    _pause(user_id, p)
    n = tasks_svc.dismiss_parked_due_dates(user_id, p.id)
    t.refresh_from_db()
    assert n == 1
    assert t.due_date is None and t.parked_due_date is None


@pytest.mark.django_db
def test_reschedule_consumes_parked_snapshot(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE)
    due = timezone.now() + dt.timedelta(days=4)
    t = tasks_svc.create_task(user_id, title="x", project_id=p.id, due_date=due)
    _pause(user_id, p)
    new_due = timezone.now() + dt.timedelta(days=10)
    tasks_svc.update_task(user_id, t.id, title="x", project_id=p.id, due_date=new_due)
    t.refresh_from_db()
    assert t.due_date == new_due and t.parked_due_date is None


@pytest.mark.django_db
def test_stalled_does_not_park_due_dates(user_id):
    p = _mk(user_id, ProjectStatus.ACTIVE, days_idle=STALLED_THRESHOLD_DAYS + 1)
    due = timezone.now() + dt.timedelta(days=3)
    t = tasks_svc.create_task(user_id, title="x", project_id=p.id, due_date=due)
    Project.objects.filter(pk=p.pk).update(
        last_activity=timezone.now() - dt.timedelta(days=STALLED_THRESHOLD_DAYS + 1)
    )
    detect_and_mark_stalled(user_id)
    p.refresh_from_db()
    t.refresh_from_db()
    assert p.status == ProjectStatus.STALLED
    assert t.due_date == due and t.parked_due_date is None  # auto-stall never mutates


# ----- routine daily-view filter by parent project status (Fase 0) -----

@pytest.mark.django_db
def test_routines_of_closed_project_excluded_from_due_range(user_id):
    today = timezone.now().date()
    AccountProfile.objects.create(user_id=user_id, plan="pro")  # lift free routine cap
    live = _mk(user_id, ProjectStatus.ACTIVE)
    paused = _mk(user_id, ProjectStatus.PAUSED, name="p2")
    r_live = routines_svc.create_routine(
        user_id, title="daily-live", recurrence_type="every_n", interval_n=1, interval_unit="days",
        start_date=today - dt.timedelta(days=2), project_id=live.id,
    )
    r_loose = routines_svc.create_routine(
        user_id, title="daily-loose", recurrence_type="every_n", interval_n=1, interval_unit="days",
        start_date=today - dt.timedelta(days=2),
    )
    routines_svc.create_routine(
        user_id, title="daily-paused", recurrence_type="every_n", interval_n=1, interval_unit="days",
        start_date=today - dt.timedelta(days=2), project_id=paused.id,
    )
    items = routines_svc.list_due_in_range(user_id, today, today)
    rids = {it["routine_id"] for it in items}
    assert r_live.id in rids
    assert r_loose.id in rids
    assert all(
        Routine.objects.get(pk=rid).project_id != paused.id for rid in rids
    )

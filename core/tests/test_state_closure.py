"""State closure system: stalled auto-detection, closure-note validation,
cap counting for killed, and revive (STATE_CLOSURE_FINAL.md)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.assistant.models import AccountProfile
from core.models import Activity, ActivityKind, Project, ProjectStatus
from core.quotas import EntityQuotaExceeded
from core.services import projects as projects_svc
from core.services.stalled import STALLED_THRESHOLD_DAYS, detect_and_mark_stalled


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


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

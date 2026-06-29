"""Project services."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ..models import ActivityKind, Category, Project, ProjectStatus
from ..quotas import check_entity_quota
from ._cache import bump_context_version as _bump_context_version
from ._common import NotFoundError
from .activities import iso, log_event


# Re-export so existing `from .services.projects import NotFoundError` keeps working.
__all__ = ["NotFoundError"]


# Statuses that appear in daily views and trigger notifications (docs/_archive/state-closure/STATE_CLOSURE_FINAL.md D5).
DAILY_VIEW_PROJECT_STATUSES = [
    ProjectStatus.ACTIVE,
    ProjectStatus.IDEA,
    ProjectStatus.LAUNCHED,
]
# Statuses that count toward the plan cap (D3). killed/archived are free.
COUNTING_STATUSES = [
    ProjectStatus.IDEA,
    ProjectStatus.ACTIVE,
    ProjectStatus.STALLED,
    ProjectStatus.PAUSED,
    ProjectStatus.LAUNCHED,
]
NONCOUNTING_STATUSES = [ProjectStatus.KILLED, ProjectStatus.ARCHIVED]
# Explicit closures that withdraw a project's tasks from daily surfaces AND
# snapshot/clear their due dates (state-closure parking). STALLED is excluded on
# purpose: it is auto-detected by the cron, so it only filters daily views and
# must never silently mutate task data. Revive/resume does NOT auto-restore the
# dates (suggest, not auto) — the snapshot stays as the reschedule hint.
PARKING_STATUSES = [
    ProjectStatus.PAUSED,
    ProjectStatus.KILLED,
    ProjectStatus.ARCHIVED,
]


def list_projects(
    user_id: uuid.UUID,
    *,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> list[Project]:
    qs = Project.objects.filter(user_id=user_id)
    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if category_id:
        qs = qs.filter(category_id=category_id)
    qs = qs.order_by("-last_activity")
    if limit:
        qs = qs[: max(1, min(int(limit), 200))]
    return list(qs)


def get_project(user_id: uuid.UUID, project_id) -> Project:
    obj = Project.objects.filter(pk=project_id, user_id=user_id).first()
    if obj is None:
        raise NotFoundError("Project not found")
    return obj


def assert_owned(user_id: uuid.UUID, project_id) -> None:
    if project_id and not Project.objects.filter(
        pk=project_id, user_id=user_id
    ).exists():
        raise NotFoundError("Project not found")


def create_project(
    user_id: uuid.UUID,
    *,
    name: str,
    description: str = "",
    why: str = "",
    next_step: str = "",
    status: str = "idea",
    priority: str = "medium",
    category_id: Optional[uuid.UUID] = None,
    due_date: Optional[dt.datetime] = None,
) -> Project:
    check_entity_quota(user_id, "projects")
    category = None
    if category_id:
        category = Category.objects.filter(pk=category_id, user_id=user_id).first()
    # New projects land at the end of the manual order ("Mi orden").
    next_position = (
        Project.objects.filter(user_id=user_id).aggregate(m=Max("position"))["m"] or 0
    ) + 1
    project = Project.objects.create(
        user_id=user_id,
        name=name,
        description=description or "",
        why=why or "",
        next_step=next_step or "",
        status=status or "idea",
        priority=priority or "medium",
        category=category,
        due_date=due_date,
        position=next_position,
    )
    log_event(
        user_id,
        kind=ActivityKind.PROJECT_CREATED,
        entity_id=project.id,
        entity_title=project.name,
        project_id=project.id,
    )
    _bump_context_version(user_id)
    return project


def update_project(
    user_id: uuid.UUID,
    project_id,
    *,
    name: str,
    description: str = "",
    why: str = "",
    next_step: str = "",
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category_id: Optional[uuid.UUID] = None,
    clear_category: bool = False,
    due_date: Optional[dt.datetime] = None,
    # Closure notes (additive). Validated only when the transition needs them.
    paused_context: Optional[str] = None,
    paused_next_action: Optional[str] = None,
    paused_blocker: Optional[str] = None,
    killed_reason: Optional[str] = None,
    killed_learnings: Optional[str] = None,
    killed_would_restart: Optional[str] = None,
) -> Project:
    project = get_project(user_id, project_id)
    old_status = project.status
    old_due_date = project.due_date
    project.name = name
    project.description = description or ""
    project.why = why or ""
    project.next_step = next_step or ""
    if status and status != old_status:
        _apply_status_transition(
            user_id,
            project,
            status,
            paused_context=paused_context,
            paused_next_action=paused_next_action,
            paused_blocker=paused_blocker,
            killed_reason=killed_reason,
            killed_learnings=killed_learnings,
            killed_would_restart=killed_would_restart,
        )
    elif status:
        project.status = status
    if priority:
        project.priority = priority
    if clear_category:
        project.category = None
    elif category_id is not None:
        project.category = Category.objects.filter(
            pk=category_id, user_id=user_id
        ).first()
    project.due_date = due_date
    project.last_activity = timezone.now()
    project.save()
    if status and old_status != project.status:
        log_event(
            user_id,
            kind=ActivityKind.PROJECT_STATUS_CHANGED,
            entity_id=project.id,
            entity_title=project.name,
            project_id=project.id,
            previous_value=old_status,
            new_value=project.status,
            note=_closure_note_summary(project),
        )
        if project.status == ProjectStatus.KILLED:
            from .autopsy import maybe_generate_on_kill

            maybe_generate_on_kill(user_id, project)
        elif old_status == ProjectStatus.KILLED:
            from .autopsy import mark_pattern_stale

            mark_pattern_stale(user_id)
    if old_due_date != project.due_date:
        log_event(
            user_id,
            kind=ActivityKind.PROJECT_DUE_DATE_CHANGED,
            entity_id=project.id,
            entity_title=project.name,
            project_id=project.id,
            previous_value=iso(old_due_date),
            new_value=iso(project.due_date),
        )
    _bump_context_version(user_id)
    return project


def _apply_status_transition(
    user_id: uuid.UUID,
    project: Project,
    new_status: str,
    *,
    paused_context: Optional[str],
    paused_next_action: Optional[str],
    paused_blocker: Optional[str],
    killed_reason: Optional[str],
    killed_learnings: Optional[str],
    killed_would_restart: Optional[str],
) -> None:
    """Validate required closure notes, enforce the cap when re-entering a
    counting state (e.g. revive), set timestamps, and assign the new status.
    The project is NOT saved here — the caller saves once."""
    previous_status = project.status
    if project.status in NONCOUNTING_STATUSES and new_status in COUNTING_STATUSES:
        # Revive / unarchive into a state that counts -> revalidate the plan cap.
        check_entity_quota(user_id, "projects")

    if new_status == ProjectStatus.PAUSED:
        if not (paused_context or "").strip():
            raise ValidationError(
                "Pausing requires 'paused_context'. "
                "Tell future you where you're stopping."
            )
        if not (paused_next_action or "").strip():
            raise ValidationError(
                "Pausing requires 'paused_next_action'. "
                "What's the very next action when you return?"
            )
        project.paused_context = paused_context.strip()
        project.paused_next_action = paused_next_action.strip()
        project.paused_blocker = (paused_blocker or "").strip()
        project.paused_at = timezone.now()
    elif new_status == ProjectStatus.KILLED:
        if not (killed_reason or "").strip():
            raise ValidationError(
                "Killing requires 'killed_reason'. "
                "Killing is a form of finishing. It deserves a why."
            )
        if not (killed_learnings or "").strip():
            raise ValidationError(
                "Killing requires 'killed_learnings'. "
                "What did this project teach you?"
            )
        project.killed_reason = killed_reason.strip()
        project.killed_learnings = killed_learnings.strip()
        project.killed_would_restart = (killed_would_restart or "").strip()
        project.killed_at = timezone.now()
    elif new_status == ProjectStatus.STALLED:
        project.stalled_at = timezone.now()
    elif new_status in (ProjectStatus.ACTIVE, ProjectStatus.IDEA):
        # Resume / revive: clear gating timestamps, keep the notes for history.
        project.paused_at = None
        project.stalled_at = None
        project.killed_at = None

    project.status = new_status

    # State-closure parking: entering a closed state snapshots + clears its
    # tasks' due dates so they leave the daily surfaces. Idempotent and only on
    # the live -> closed edge (paused -> killed keeps the existing snapshots).
    # Revive (closed -> live) intentionally does NOT auto-restore: the snapshot
    # remains as a reschedule suggestion surfaced by the revive/welcome UI.
    if new_status in PARKING_STATUSES and previous_status not in PARKING_STATUSES:
        from .tasks import park_project_tasks  # local import avoids import cycle

        park_project_tasks(user_id, project.id)


def _closure_note_summary(project: Project) -> str:
    """Plain-text summary stored on the Activity log's `note` field (D8)."""
    if project.status == ProjectStatus.PAUSED:
        parts = [
            f"context: {project.paused_context}",
            f"next: {project.paused_next_action}",
        ]
        if project.paused_blocker:
            parts.append(f"blocker: {project.paused_blocker}")
        return "\n".join(parts)
    if project.status == ProjectStatus.KILLED:
        parts = [
            f"reason: {project.killed_reason}",
            f"learnings: {project.killed_learnings}",
        ]
        if project.killed_would_restart:
            parts.append(f"would_restart: {project.killed_would_restart}")
        return "\n".join(parts)
    return ""


def delete_project(user_id: uuid.UUID, project_id) -> None:
    project = (
        Project.objects.filter(pk=project_id, user_id=user_id)
        .only("id", "name")
        .first()
    )
    Project.objects.filter(pk=project_id, user_id=user_id).delete()
    if project is not None:
        log_event(
            user_id,
            kind=ActivityKind.PROJECT_DELETED,
            entity_id=project.id,
            entity_title=project.name,
            project_id=project.id,
        )
    _bump_context_version(user_id)


def reorder_projects(user_id: uuid.UUID, ordered_ids: list) -> list[Project]:
    """Persist the manual order ("Mi orden"). Assigns dense 0..N `position`
    values following `ordered_ids`; ids not owned by the user are ignored, and
    any owned project missing from the list keeps its previous position. Does
    NOT touch `last_activity` — reordering is not "activity" on a project."""
    projects = {str(p.id): p for p in Project.objects.filter(user_id=user_id)}
    with transaction.atomic():
        for idx, pid in enumerate(ordered_ids):
            p = projects.get(str(pid))
            if p is not None and p.position != idx:
                p.position = idx
                p.save(update_fields=["position"])
    _bump_context_version(user_id)
    return list(Project.objects.filter(user_id=user_id))


def touch_last_activity(user_id: uuid.UUID, project_id, *, when: Optional[dt.datetime] = None) -> None:
    Project.objects.filter(pk=project_id, user_id=user_id).update(
        last_activity=when or timezone.now()
    )
    _bump_context_version(user_id)

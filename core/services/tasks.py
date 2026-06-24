"""Task services."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from ..models import ActivityKind, Project, Task, TaskBlocker
from ..quotas import check_entity_quota
from ._cache import bump_context_version
from .activities import iso, log_event
from .projects import (
    DAILY_VIEW_PROJECT_STATUSES,
    NotFoundError,
    assert_owned,
    touch_last_activity,
)


def list_tasks(
    user_id: uuid.UUID,
    *,
    project_id: Optional[uuid.UUID] = None,
    done: Optional[bool] = None,
    due_within_days: Optional[int] = None,
    daily_view: bool = False,
    limit: int = 50,
) -> list[Task]:
    qs = Task.objects.filter(user_id=user_id).prefetch_related("blockers")
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    if daily_view:
        # Only tasks of "live" projects pollute daily views; standalone tasks
        # (no project) always stay visible (D5/D6).
        qs = qs.filter(
            Q(project__isnull=True)
            | Q(project__status__in=DAILY_VIEW_PROJECT_STATUSES)
        )
    if done is not None:
        qs = qs.filter(done=done)
    if due_within_days is not None:
        now = timezone.now()
        cutoff = now + dt.timedelta(days=int(due_within_days))
        qs = qs.filter(due_date__isnull=False, due_date__lte=cutoff)
    qs = qs.order_by("done", "due_date", "-created")
    if limit:
        qs = qs[: max(1, min(int(limit), 200))]
    return list(qs)


def get_task(user_id: uuid.UUID, task_id) -> Task:
    obj = Task.objects.filter(pk=task_id, user_id=user_id).first()
    if obj is None:
        raise NotFoundError("Task not found")
    return obj


def create_task(
    user_id: uuid.UUID,
    *,
    title: str,
    project_id: Optional[uuid.UUID] = None,
    due_date: Optional[dt.datetime] = None,
    done: bool = False,
    effort_hours: Optional[float] = None,
    due_time: Optional[dt.time] = None,
    duration_minutes: Optional[int] = None,
) -> Task:
    assert_owned(user_id, project_id)
    check_entity_quota(user_id, "tasks_total")
    if project_id:
        check_entity_quota(user_id, "tasks_per_project", project_id=project_id)
    task = Task.objects.create(
        user_id=user_id,
        title=title,
        project_id=project_id or None,
        due_date=due_date,
        done=bool(done),
        effort_hours=effort_hours,
        due_time=due_time,
        duration_minutes=duration_minutes,
    )
    log_event(
        user_id,
        kind=ActivityKind.TASK_CREATED,
        entity_id=task.id,
        entity_title=task.title,
        project_id=task.project_id,
    )
    if task.project_id:
        touch_last_activity(user_id, task.project_id)
    bump_context_version(user_id)
    return task


def update_task(
    user_id: uuid.UUID,
    task_id,
    *,
    title: str,
    project_id: Optional[uuid.UUID] = None,
    due_date: Optional[dt.datetime] = None,
    done: bool = False,
    effort_hours: Optional[float] = None,
    due_time: Optional[dt.time] = None,
    duration_minutes: Optional[int] = None,
) -> Task:
    assert_owned(user_id, project_id)
    task = get_task(user_id, task_id)
    old_due_date = task.due_date
    task.title = title
    task.project_id = project_id or None
    task.due_date = due_date
    task.done = bool(done)
    task.effort_hours = effort_hours
    task.due_time = due_time
    task.duration_minutes = duration_minutes
    if task.done and not task.completed_at:
        task.completed_at = timezone.now()
    if not task.done:
        task.completed_at = None
    task.save()
    if task.project_id:
        touch_last_activity(user_id, task.project_id)
    if old_due_date != task.due_date:
        log_event(
            user_id,
            kind=ActivityKind.TASK_DUE_DATE_CHANGED,
            entity_id=task.id,
            entity_title=task.title,
            project_id=task.project_id,
            previous_value=iso(old_due_date),
            new_value=iso(task.due_date),
        )
    bump_context_version(user_id)
    return task


def toggle_task(user_id: uuid.UUID, task_id) -> Task:
    task = get_task(user_id, task_id)
    task.done = not task.done
    task.completed_at = timezone.now() if task.done else None
    task.save()
    if task.done:
        # Auto-remove blockers where this task was the blocking dependency
        TaskBlocker.objects.filter(blocking_task_id=task.id).delete()
        log_event(
            user_id,
            kind=ActivityKind.TASK_COMPLETED,
            entity_id=task.id,
            entity_title=task.title,
            project_id=task.project_id,
        )
        if task.project_id:
            Project.objects.filter(pk=task.project_id, user_id=user_id).update(
                last_activity=timezone.now()
            )
    bump_context_version(user_id)
    return task


def _detect_cycle(user_id: uuid.UUID, start_id, end_id) -> bool:
    """Return True if making start_id block end_id would create a cycle."""
    visited: set = set()
    queue = [str(end_id)]
    while queue:
        current = queue.pop()
        if current == str(start_id):
            return True
        if current in visited:
            continue
        visited.add(current)
        downstream = list(
            TaskBlocker.objects.filter(
                blocking_task_id=current,
            ).values_list("blocked_task_id", flat=True)
        )
        queue.extend(str(d) for d in downstream)
    return False


def add_task_blocker(
    user_id: uuid.UUID,
    blocked_task_id,
    *,
    blocking_task_id=None,
    external_description: str = "",
) -> TaskBlocker:
    has_task = bool(blocking_task_id)
    has_ext = bool(external_description.strip())
    if has_task == has_ext:
        raise ValueError("Provide exactly one of blocking_task_id or external_description")
    blocked_task = get_task(user_id, blocked_task_id)
    if has_task:
        get_task(user_id, blocking_task_id)
        if str(blocking_task_id) == str(blocked_task_id):
            raise ValueError("A task cannot block itself")
        if _detect_cycle(user_id, blocking_task_id, blocked_task_id):
            raise ValueError("Adding this blocker would create a circular dependency")
    blocker = TaskBlocker.objects.create(
        user_id=user_id,
        blocked_task=blocked_task,
        blocking_task_id=blocking_task_id or None,
        external_description=external_description.strip(),
    )
    bump_context_version(user_id)
    return blocker


def remove_task_blocker(user_id: uuid.UUID, blocker_id) -> None:
    TaskBlocker.objects.filter(pk=blocker_id, user_id=user_id).delete()
    bump_context_version(user_id)


def delete_task(user_id: uuid.UUID, task_id) -> None:
    task = (
        Task.objects.filter(pk=task_id, user_id=user_id)
        .only("id", "title", "project_id")
        .first()
    )
    Task.objects.filter(pk=task_id, user_id=user_id).delete()
    if task is not None and task.project_id:
        touch_last_activity(user_id, task.project_id)
    if task is not None:
        log_event(
            user_id,
            kind=ActivityKind.TASK_DELETED,
            entity_id=task.id,
            entity_title=task.title,
            project_id=task.project_id,
        )
    bump_context_version(user_id)

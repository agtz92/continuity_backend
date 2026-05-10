"""Task services."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from django.utils import timezone

from ..models import Project, Task, Update
from ._cache import bump_context_version
from .projects import NotFoundError, assert_owned, touch_last_activity


def list_tasks(
    user_id: uuid.UUID,
    *,
    project_id: Optional[uuid.UUID] = None,
    done: Optional[bool] = None,
    due_within_days: Optional[int] = None,
    limit: int = 50,
) -> list[Task]:
    qs = Task.objects.filter(user_id=user_id)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
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
) -> Task:
    assert_owned(user_id, project_id)
    task = Task.objects.create(
        user_id=user_id,
        title=title,
        project_id=project_id or None,
        due_date=due_date,
        done=bool(done),
        effort_hours=effort_hours,
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
) -> Task:
    assert_owned(user_id, project_id)
    task = get_task(user_id, task_id)
    task.title = title
    task.project_id = project_id or None
    task.due_date = due_date
    task.done = bool(done)
    task.effort_hours = effort_hours
    if task.done and not task.completed_at:
        task.completed_at = timezone.now()
    if not task.done:
        task.completed_at = None
    task.save()
    bump_context_version(user_id)
    return task


def toggle_task(user_id: uuid.UUID, task_id) -> Task:
    task = get_task(user_id, task_id)
    task.done = not task.done
    task.completed_at = timezone.now() if task.done else None
    task.save()
    if task.done and task.project_id:
        Update.objects.create(
            user_id=user_id, project_id=task.project_id, note=f"Completed: {task.title}"
        )
        Project.objects.filter(pk=task.project_id, user_id=user_id).update(
            last_activity=timezone.now()
        )
    bump_context_version(user_id)
    return task


def delete_task(user_id: uuid.UUID, task_id) -> None:
    Task.objects.filter(pk=task_id, user_id=user_id).delete()
    bump_context_version(user_id)

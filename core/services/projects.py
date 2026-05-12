"""Project services."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from django.utils import timezone

from ..models import ActivityKind, Category, Project
from ._cache import bump_context_version as _bump_context_version
from ._common import NotFoundError
from .activities import iso, log_event


# Re-export so existing `from .services.projects import NotFoundError` keeps working.
__all__ = ["NotFoundError"]


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
    category = None
    if category_id:
        category = Category.objects.filter(pk=category_id, user_id=user_id).first()
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
) -> Project:
    project = get_project(user_id, project_id)
    old_status = project.status
    old_due_date = project.due_date
    project.name = name
    project.description = description or ""
    project.why = why or ""
    project.next_step = next_step or ""
    if status:
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
        )
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


def touch_last_activity(user_id: uuid.UUID, project_id, *, when: Optional[dt.datetime] = None) -> None:
    Project.objects.filter(pk=project_id, user_id=user_id).update(
        last_activity=when or timezone.now()
    )
    _bump_context_version(user_id)

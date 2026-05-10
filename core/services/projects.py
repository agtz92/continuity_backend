"""Project services."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from django.utils import timezone

from ..models import Category, Project
from ._cache import bump_context_version as _bump_context_version


class NotFoundError(Exception):
    """Raised when an entity is missing or owned by another user."""


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
) -> Project:
    project = get_project(user_id, project_id)
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
    project.last_activity = timezone.now()
    project.save()
    _bump_context_version(user_id)
    return project


def delete_project(user_id: uuid.UUID, project_id) -> None:
    Project.objects.filter(pk=project_id, user_id=user_id).delete()
    _bump_context_version(user_id)


def touch_last_activity(user_id: uuid.UUID, project_id, *, when: Optional[dt.datetime] = None) -> None:
    Project.objects.filter(pk=project_id, user_id=user_id).update(
        last_activity=when or timezone.now()
    )
    _bump_context_version(user_id)

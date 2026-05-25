"""Idea services."""

from __future__ import annotations

import uuid
from typing import Optional

from django.db import transaction
from django.utils import timezone

from ..models import ActivityKind, Idea, Project
from ..quotas import check_entity_quota
from ._cache import bump_context_version
from .activities import log_event
from .projects import NotFoundError


def list_ideas(user_id: uuid.UUID, *, limit: int = 30) -> list[Idea]:
    qs = Idea.objects.filter(user_id=user_id).order_by("-created")
    if limit:
        qs = qs[: max(1, min(int(limit), 100))]
    return list(qs)


def get_idea(user_id: uuid.UUID, idea_id) -> Idea:
    obj = Idea.objects.filter(pk=idea_id, user_id=user_id).first()
    if obj is None:
        raise NotFoundError("Idea not found")
    return obj


def create_idea(
    user_id: uuid.UUID,
    *,
    title: str,
    description: str = "",
    why: str = "",
) -> Idea:
    check_entity_quota(user_id, "ideas")
    idea = Idea.objects.create(
        user_id=user_id,
        title=title,
        description=description or "",
        why=why or "",
    )
    log_event(
        user_id,
        kind=ActivityKind.IDEA_CREATED,
        entity_id=idea.id,
        entity_title=idea.title,
    )
    bump_context_version(user_id)
    return idea


def update_idea(
    user_id: uuid.UUID,
    idea_id,
    *,
    title: str,
    description: str = "",
    why: str = "",
) -> Idea:
    idea = get_idea(user_id, idea_id)
    idea.title = title
    idea.description = description or ""
    idea.why = why or ""
    idea.save()
    bump_context_version(user_id)
    return idea


def delete_idea(user_id: uuid.UUID, idea_id) -> None:
    idea = (
        Idea.objects.filter(pk=idea_id, user_id=user_id)
        .only("id", "title")
        .first()
    )
    Idea.objects.filter(pk=idea_id, user_id=user_id).delete()
    if idea is not None:
        log_event(
            user_id,
            kind=ActivityKind.IDEA_DELETED,
            entity_id=idea.id,
            entity_title=idea.title,
        )
    bump_context_version(user_id)


def promote_idea(user_id: uuid.UUID, idea_id) -> Project:
    check_entity_quota(user_id, "projects")
    with transaction.atomic():
        idea = get_idea(user_id, idea_id)
        project = Project.objects.create(
            user_id=user_id,
            name=idea.title,
            description=idea.description,
            why=idea.why,
            status="idea",
            promoted_from_idea_at=timezone.now(),
        )
        idea_id_snapshot = idea.id
        idea_title_snapshot = idea.title
        idea.delete()
        log_event(
            user_id,
            kind=ActivityKind.IDEA_PROMOTED,
            entity_id=idea_id_snapshot,
            entity_title=idea_title_snapshot,
            project_id=project.id,
            target_project_id=project.id,
        )
    bump_context_version(user_id)
    return project

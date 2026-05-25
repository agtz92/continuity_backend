"""Project-note services."""

from __future__ import annotations

import uuid
from typing import Optional

from ..models import ProjectNote
from ..quotas import check_entity_quota
from .projects import NotFoundError, assert_owned, touch_last_activity


def list_notes(
    user_id: uuid.UUID,
    *,
    project_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> list[ProjectNote]:
    qs = ProjectNote.objects.filter(user_id=user_id)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    qs = qs.order_by("-updated_at")
    if limit:
        qs = qs[: max(1, min(int(limit), 200))]
    return list(qs)


def get_note(user_id: uuid.UUID, note_id) -> ProjectNote:
    obj = ProjectNote.objects.filter(pk=note_id, user_id=user_id).first()
    if obj is None:
        raise NotFoundError("ProjectNote not found")
    return obj


def create_note(
    user_id: uuid.UUID,
    *,
    project_id: uuid.UUID,
    title: str = "",
    body: str = "",
) -> ProjectNote:
    assert_owned(user_id, project_id)
    check_entity_quota(user_id, "notes_per_project", project_id=project_id)
    clean_title = (title or "").strip()
    clean_body = body or ""
    note = ProjectNote.objects.create(
        user_id=user_id,
        project_id=project_id,
        title=clean_title,
        body=clean_body,
    )
    touch_last_activity(user_id, project_id)
    return note


def update_note(
    user_id: uuid.UUID,
    note_id,
    *,
    title: str = "",
    body: str = "",
) -> ProjectNote:
    note = get_note(user_id, note_id)
    note.title = (title or "").strip()
    note.body = body or ""
    note.save(update_fields=["title", "body", "updated_at"])
    return note


def delete_note(user_id: uuid.UUID, note_id) -> None:
    ProjectNote.objects.filter(pk=note_id, user_id=user_id).delete()

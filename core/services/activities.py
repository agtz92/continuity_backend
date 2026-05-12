"""Unified activity service.

Single source of truth for the activity feed:
- `log_event(...)` — internal helper called by projects/tasks/ideas services
  after each mutation. Append-only.
- `add_note / update_note / delete_note` — public surface for user-authored
  notes (kind=NOTE). The only kind that's user-editable.
- `list_activity` — read API used by the dashboard and stats.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Iterable, Optional

from django.utils import timezone

from ..models import Activity, ActivityKind, Project
from ._cache import bump_context_version as _bump_context_version
from ._common import NotFoundError


def log_event(
    user_id: uuid.UUID,
    *,
    kind: str,
    entity_id: Optional[uuid.UUID] = None,
    entity_title: str = "",
    project_id: Optional[uuid.UUID] = None,
    target_project_id: Optional[uuid.UUID] = None,
    previous_value: str = "",
    new_value: str = "",
    note: str = "",
) -> Activity:
    return Activity.objects.create(
        user_id=user_id,
        kind=kind,
        entity_id=entity_id,
        entity_title=entity_title or "",
        project_id=project_id,
        target_project_id=target_project_id,
        previous_value=previous_value or "",
        new_value=new_value or "",
        note=note or "",
    )


def iso(d: Optional[dt.datetime]) -> str:
    return d.isoformat() if d else ""


def list_activity(
    user_id: uuid.UUID,
    *,
    project_id: Optional[uuid.UUID] = None,
    kinds: Optional[Iterable[str]] = None,
    limit: int = 100,
    since: Optional[dt.datetime] = None,
    until: Optional[dt.datetime] = None,
) -> list[Activity]:
    qs = Activity.objects.filter(user_id=user_id)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    if kinds:
        qs = qs.filter(kind__in=list(kinds))
    if since is not None:
        qs = qs.filter(created__gte=since)
    if until is not None:
        qs = qs.filter(created__lte=until)
    capped = max(1, min(int(limit), 500))
    return list(qs.order_by("-created")[:capped])


# ---------- Public note operations (kind=NOTE only)


def add_note(user_id: uuid.UUID, *, project_id, note: str) -> Activity:
    """Create a user-authored note tied to a project. Touches last_activity."""
    if not Project.objects.filter(pk=project_id, user_id=user_id).exists():
        raise NotFoundError("Project not found")
    activity = log_event(
        user_id,
        kind=ActivityKind.NOTE,
        project_id=project_id,
        note=note,
    )
    Project.objects.filter(pk=project_id, user_id=user_id).update(
        last_activity=timezone.now()
    )
    _bump_context_version(user_id)
    return activity


def _get_note_for_edit(user_id: uuid.UUID, activity_id) -> Activity:
    obj = Activity.objects.filter(
        pk=activity_id, user_id=user_id, kind=ActivityKind.NOTE
    ).first()
    if obj is None:
        raise NotFoundError("Note not found")
    return obj


def update_note(user_id: uuid.UUID, activity_id, *, note: str) -> Activity:
    activity = _get_note_for_edit(user_id, activity_id)
    activity.note = note
    activity.save(update_fields=["note"])
    _bump_context_version(user_id)
    return activity


def delete_note(user_id: uuid.UUID, activity_id) -> None:
    activity = _get_note_for_edit(user_id, activity_id)
    activity.delete()
    _bump_context_version(user_id)

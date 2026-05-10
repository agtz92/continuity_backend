"""Update (activity log) services."""

from __future__ import annotations

import uuid
from typing import Optional

from ..models import Update
from .projects import NotFoundError, assert_owned, touch_last_activity


def list_updates(
    user_id: uuid.UUID,
    *,
    project_id: Optional[uuid.UUID] = None,
    limit: int = 20,
) -> list[Update]:
    qs = Update.objects.filter(user_id=user_id)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    qs = qs.order_by("-date")
    if limit:
        qs = qs[: max(1, min(int(limit), 200))]
    return list(qs)


def get_update(user_id: uuid.UUID, update_id) -> Update:
    obj = Update.objects.filter(pk=update_id, user_id=user_id).first()
    if obj is None:
        raise NotFoundError("Update not found")
    return obj


def add_update(user_id: uuid.UUID, *, project_id: uuid.UUID, note: str) -> Update:
    assert_owned(user_id, project_id)
    update = Update.objects.create(user_id=user_id, project_id=project_id, note=note)
    touch_last_activity(user_id, project_id)
    return update


def edit_update(user_id: uuid.UUID, update_id, *, note: str) -> Update:
    update = get_update(user_id, update_id)
    update.note = note
    update.save()
    return update


def delete_update(user_id: uuid.UUID, update_id) -> None:
    Update.objects.filter(pk=update_id, user_id=user_id).delete()

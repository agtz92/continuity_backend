"""Push action buttons: "Marcar hecha" / "Pasar a mañana".

The mobile app sends back the `taskIds` the push carried (see
`builders.CATEGORY_*`). Both actions are idempotent on purpose: the app can
receive the same response twice (live listener + cold-start replay), and a
push can be acted on hours later, after the user already handled the task in
the app. So "complete" never un-completes, and "postpone" never pulls a task
that already lives in the future back to tomorrow.
"""

from __future__ import annotations

import datetime as dt
import uuid
import zoneinfo
from typing import Iterable

from django.utils import timezone

from core.models import Task
from core.services import tasks as tasks_service

from .models import NotificationSettings

# A due warning lists every open task of the day; anything past this is not a
# push the app built.
MAX_TASKS = 50


def _parse_ids(task_ids: Iterable) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for raw in list(task_ids)[:MAX_TASKS]:
        try:
            out.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    return out


def _open_tasks(user_id: uuid.UUID, task_ids: Iterable) -> list[Task]:
    """The caller's still-open tasks among `task_ids`. Ids that were deleted,
    belong to someone else or are already done are dropped silently."""
    ids = _parse_ids(task_ids)
    if not ids:
        return []
    return list(Task.objects.filter(user_id=user_id, id__in=ids, done=False))


def complete_tasks(user_id: uuid.UUID, task_ids: Iterable) -> int:
    tasks = _open_tasks(user_id, task_ids)
    for task in tasks:
        # toggle_task carries the side effects (activity log, blockers, project
        # last_activity); the done=False filter above makes it a pure "complete".
        tasks_service.toggle_task(user_id, task.id)
    return len(tasks)


def _user_tz(user_id: uuid.UUID) -> zoneinfo.ZoneInfo:
    s = NotificationSettings.objects.filter(user_id=user_id).only("timezone").first()
    try:
        return zoneinfo.ZoneInfo((s.timezone if s else "") or "UTC")
    except zoneinfo.ZoneInfoNotFoundError:
        return zoneinfo.ZoneInfo("UTC")


def postpone_tasks(
    user_id: uuid.UUID, task_ids: Iterable, *, now: dt.datetime | None = None
) -> int:
    """Move each open task due today or earlier to tomorrow (user's local
    date), keeping its time of day."""
    tz = _user_tz(user_id)
    today = (now or timezone.now()).astimezone(tz).date()
    tomorrow = today + dt.timedelta(days=1)

    moved = 0
    for task in _open_tasks(user_id, task_ids):
        if task.due_date is None:
            local_time = dt.time.min
        else:
            local = task.due_date.astimezone(tz)
            if local.date() > today:
                continue
            local_time = local.time()
        new_due = dt.datetime.combine(tomorrow, local_time, tzinfo=tz)
        tasks_service.postpone_task(user_id, task.id, new_due)
        moved += 1
    return moved

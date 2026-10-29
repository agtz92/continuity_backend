"""Task services."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from ..models import ActivityKind, Project, Task, TaskBlocker
from ..quotas import check_entity_quota
from ._cache import bump_context_version
from ._common import existing_for_client_id
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
    qs = tasks_queryset(
        user_id,
        project_id=project_id,
        done=done,
        due_within_days=due_within_days,
        daily_view=daily_view,
    )
    if limit:
        qs = qs[: max(1, min(int(limit), 200))]
    return list(qs)


def tasks_queryset(
    user_id: uuid.UUID,
    *,
    project_id: Optional[uuid.UUID] = None,
    done: Optional[bool] = None,
    due_within_days: Optional[int] = None,
    daily_view: bool = False,
):
    """Filtered, ordered, unsliced — for callers that paginate (count + offset)."""
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
    return qs.order_by("done", "due_date", "-created", "id")


def next_task_position(user_id: uuid.UUID, project_id) -> int:
    """Posición para una tarea que entra a `project_id`: al final de su orden
    manual. Sin proyecto devuelve 0 (el orden manual solo existe dentro de uno)."""
    if not project_id:
        return 0
    last = (
        Task.objects.filter(user_id=user_id, project_id=project_id)
        .aggregate(m=Max("position"))["m"]
    )
    return 0 if last is None else last + 1


def reorder_project_tasks(
    user_id: uuid.UUID, project_id, ordered_ids: list
) -> list[Task]:
    """Persiste el orden manual de las tareas de un proyecto (drag & drop del
    detalle). Asigna posiciones densas 0..N siguiendo `ordered_ids`; ids que no
    son de ese proyecto/usuario se ignoran y las tareas del proyecto que no
    vienen en la lista conservan su posición. No toca `last_activity`: reordenar
    no es actividad."""
    assert_owned(user_id, project_id)
    tasks = {
        str(t.id): t
        for t in Task.objects.filter(user_id=user_id, project_id=project_id)
    }
    with transaction.atomic():
        for idx, tid in enumerate(ordered_ids):
            t = tasks.get(str(tid))
            if t is not None and t.position != idx:
                t.position = idx
                t.save(update_fields=["position"])
    bump_context_version(user_id)
    return list(
        Task.objects.filter(user_id=user_id, project_id=project_id)
        .prefetch_related("blockers")
        .order_by("position", "-created")
    )


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
    blocker: str = "",
    client_token: str = "",
    client_id=None,
) -> Task:
    """Crea una tarea y, si viene, su blocker externo **en la misma
    transaccion**.

    `blocker` y `client_token` existen por la captura rapida (⌘K), que escribia
    en dos pasos: `createTask` y despues `addTaskBlocker`. Si el segundo fallaba
    quedaba una tarea sin bloqueo y el usuario reintentaba, creando una tarea
    duplicada. Aqui o entran las dos cosas o no entra ninguna.

    `client_token` es la otra mitad del problema: la peticion pudo llegar y
    perderse la respuesta. Al reintentar con el mismo token se devuelve la tarea
    que ya se grabo, en lugar de una segunda. Vacio = sin idempotencia (el resto
    de la app, que escribe desde formularios y no reintenta sola).
    """
    assert_owned(user_id, project_id)

    if client_token:
        existing = Task.objects.filter(
            user_id=user_id, client_token=client_token
        ).first()
        if existing is not None:
            return existing

    # `client_id`: la cola offline del móvil crea con su propio UUID y reintenta
    # con el mismo (ver `existing_for_client_id`).
    existing, new_id = existing_for_client_id(Task, user_id, client_id)
    if existing is not None:
        return existing

    check_entity_quota(user_id, "tasks_total")
    if project_id:
        check_entity_quota(user_id, "tasks_per_project", project_id=project_id)

    reason = (blocker or "").strip()
    with transaction.atomic():
        task = Task.objects.create(
            **({"id": new_id} if new_id else {}),
            user_id=user_id,
            title=title,
            project_id=project_id or None,
            position=next_task_position(user_id, project_id),
            due_date=due_date,
            done=bool(done),
            effort_hours=effort_hours,
            due_time=due_time,
            duration_minutes=duration_minutes,
            client_token=client_token or "",
        )
        if reason:
            TaskBlocker.objects.create(
                user_id=user_id,
                blocked_task=task,
                blocking_task_id=None,
                external_description=reason,
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
    new_project_id = project_id or None
    if str(new_project_id or "") != str(task.project_id or ""):
        # Cambiar de proyecto la manda al final del orden manual del nuevo.
        task.position = next_task_position(user_id, new_project_id)
    task.title = title
    task.project_id = new_project_id
    task.due_date = due_date
    task.done = bool(done)
    task.effort_hours = effort_hours
    task.due_time = due_time
    task.duration_minutes = duration_minutes
    if due_date is not None:
        # A real reschedule supersedes any parked snapshot (state-closure):
        # giving the task a date again consumes the "restore?" suggestion.
        task.parked_due_date = None
        task.parked_due_time = None
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


# ---------- State-closure parking (due-date snapshot) ----------


def park_project_tasks(user_id: uuid.UUID, project_id) -> int:
    """Snapshot + clear the due dates of a project's OPEN tasks when the project
    enters a closed state (paused/killed/archived), so they stop surfacing in
    daily views. Idempotent: only tasks that still carry a due_date are parked
    (already-parked tasks have due_date=None and are skipped). Returns count.

    NOTE (calendar integration, not yet built): we clear calendar_event_id here
    so a parked task no longer maps to a pushed event. When the Google Calendar
    push lands, park/restore must also delete/recreate the remote event.
    """
    qs = Task.objects.filter(
        user_id=user_id,
        project_id=project_id,
        done=False,
        due_date__isnull=False,
    )
    parked = 0
    for task in qs:
        task.parked_due_date = task.due_date
        task.parked_due_time = task.due_time
        task.due_date = None
        task.due_time = None
        task.calendar_event_id = ""
        task.save()
        parked += 1
    if parked:
        bump_context_version(user_id)
    return parked


def restore_parked_due_dates(user_id: uuid.UUID, project_id) -> int:
    """User-initiated 'restore original dates' on revive: re-apply each parked
    task's snapshot to its live due_date and clear the snapshot. Skips tasks the
    user already rescheduled while parked (those have a due_date already).
    Returns the number of tasks whose snapshot was consumed."""
    qs = Task.objects.filter(
        user_id=user_id,
        project_id=project_id,
        parked_due_date__isnull=False,
    )
    restored = 0
    for task in qs:
        if task.due_date is None:
            task.due_date = task.parked_due_date
            task.due_time = task.parked_due_time
        task.parked_due_date = None
        task.parked_due_time = None
        task.save()
        restored += 1
    if restored:
        bump_context_version(user_id)
    return restored


def dismiss_parked_due_dates(user_id: uuid.UUID, project_id) -> int:
    """User-initiated 'keep unscheduled' on revive: drop the reschedule
    suggestion, leaving the tasks without a due date. Returns count cleared."""
    updated = Task.objects.filter(
        user_id=user_id,
        project_id=project_id,
        parked_due_date__isnull=False,
    ).update(parked_due_date=None, parked_due_time=None)
    if updated:
        bump_context_version(user_id)
    return updated


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


def set_task_done(user_id: uuid.UUID, task_id, done: bool) -> Task:
    """`toggle_task` con el estado explícito: idempotente.

    La cola offline del móvil puede mandar una operación tarde o dos veces; un
    toggle repetido la dejaría al revés. Si ya está como se pide, no se toca
    (ni se vuelve a registrar la activity de completada).
    """
    task = get_task(user_id, task_id)
    if task.done == bool(done):
        return task
    return toggle_task(user_id, task_id)


def postpone_task(user_id: uuid.UUID, task_id, due_date: dt.datetime) -> Task:
    """Move a task's due date without touching anything else (used by the
    push "Pasar a mañana" action). Same bookkeeping as an `update_task`
    reschedule: clears a parked snapshot and logs the due-date change."""
    task = get_task(user_id, task_id)
    old_due_date = task.due_date
    if old_due_date == due_date:
        return task
    task.due_date = due_date
    task.parked_due_date = None
    task.parked_due_time = None
    task.save(update_fields=["due_date", "parked_due_date", "parked_due_time"])
    if task.project_id:
        touch_last_activity(user_id, task.project_id)
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

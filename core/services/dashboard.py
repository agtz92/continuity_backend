"""Carga de datos del dashboard (capa de servicio).

Extrae el acceso a datos que vivía dentro del resolver ``dashboard`` de
``core/schema.py`` (ver AUDITORIA_CODIGO.md). Junta en un solo pase todo el
estado del usuario para que el cliente arranque con un único round-trip.
Devuelve modelos crudos (sin tipos Strawberry); el resolver los proyecta con
sus conversores ``from_model``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from django.db.models import Count, Q, Sum
from django.utils import timezone

from core.models import (
    Activity as ActivityModel,
    ActivityKind,
    BackupMeta,
    Category as CategoryModel,
    Idea as IdeaModel,
    Project as ProjectModel,
    ProjectNote as ProjectNoteModel,
    Task as TaskModel,
    TaskBlocker as TaskBlockerModel,
)

from . import routines as routines_svc


def done_window_start(done_task_days: Optional[int]) -> Optional[dt.datetime]:
    """Inicio de la ventana de completadas, o ``None`` si no hay ventana."""
    if done_task_days is None:
        return None
    return timezone.now() - dt.timedelta(days=max(1, int(done_task_days)))


def older_done_q(since: dt.datetime) -> Q:
    """Completadas fuera de la ventana. Las sin ``completed_at`` (datos viejos)
    cuentan como viejas: no hay forma de saber si son recientes."""
    return Q(done=True) & (Q(completed_at__lt=since) | Q(completed_at__isnull=True))


def older_done_by_project(uid, since: Optional[dt.datetime]) -> dict:
    """``project_id -> (cuántas, horas)`` de completadas fuera de la ventana.

    Un solo GROUP BY. Sin ventana devuelve ``{}`` (el cliente tiene todas)."""
    if since is None:
        return {}
    rows = (
        TaskModel.objects.filter(older_done_q(since), user_id=uid, project_id__isnull=False)
        .values("project_id")
        .annotate(n=Count("id"), hours=Sum("effort_hours"))
    )
    return {r["project_id"]: (r["n"], r["hours"] or 0.0) for r in rows}


def activity_window_start(activity_days: Optional[int]) -> Optional[dt.datetime]:
    """Inicio de la ventana de activities, o ``None`` si no hay ventana."""
    if activity_days is None:
        return None
    return timezone.now() - dt.timedelta(days=max(1, int(activity_days)))


def older_notes_by_project(uid, since: Optional[dt.datetime]) -> dict:
    """``project_id -> cuántas notas`` de bitácora anteriores a ``since``.

    Un solo GROUP BY sobre el índice ``(user_id, project_id)`` de Activity.
    Sin ventana devuelve ``{}``."""
    if since is None:
        return {}
    rows = (
        ActivityModel.objects.filter(
            user_id=uid,
            kind=ActivityKind.NOTE,
            created__lt=since,
            project_id__isnull=False,
        )
        .values("project_id")
        .annotate(n=Count("id"))
    )
    return {r["project_id"]: r["n"] for r in rows}


COMPLETED_PAGE_MAX = 200


def list_older_done(uid, before, project_id=None, offset: int = 0, limit: int = 50) -> list:
    """Página de completadas fuera de la ventana (ver ``completedTasks``).

    Las completadas no llevan blockers activos que importen en una lista de
    historial, así que se proyectan sin ellos."""
    from django.db.models import F

    qs = TaskModel.objects.filter(older_done_q(before), user_id=uid)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    qs = qs.order_by(F("completed_at").desc(nulls_last=True), "-created")
    start = max(0, int(offset))
    size = max(1, min(int(limit), COMPLETED_PAGE_MAX))
    return list(qs[start : start + size])


@dataclass
class DashboardData:
    """Estado completo del usuario para la carga inicial (modelos crudos)."""

    projects: list
    tasks: list
    ideas: list
    activities: list
    categories: list
    project_notes: list
    routines: list
    routine_occurrences: list
    # blocked_task_id -> lista de TaskBlocker, precargado para evitar N+1.
    blocker_map: dict
    last_backup: Optional[dt.datetime]
    # project_id -> (completadas fuera de la ventana, sus horas). Vacío sin ventana.
    older_done: dict = None
    # project_id -> notas de bitácora anteriores a la ventana (solo con
    # ``all_notes=False``). Vacío si el cliente recibe todas.
    older_notes: dict = None


@dataclass
class DashboardDeltaData:
    """Proyectos con su ``blocked_since`` y las activities desde ``since``."""

    projects: list
    blocked_at: dict
    activities: list
    older_done: dict = None
    older_notes: dict = None


# Tope de activities por delta: una ráfaga normal genera unas pocas. Si alguna
# vez se llega aquí, el cliente igual reconcilia en el siguiente dashboard.
DELTA_ACTIVITY_LIMIT = 200


def get_dashboard_delta(
    uid,
    since: dt.datetime,
    done_task_days: Optional[int] = None,
    activity_days: Optional[int] = None,
    all_notes: bool = True,
) -> DashboardDeltaData:
    """Lo mínimo para reconciliar la caché del cliente tras sus escrituras.

    Cuatro consultas pequeñas en vez de las ~10 del dashboard completo: todos
    los proyectos (son pocos), solo las tareas **abiertas** y sus blockers (lo
    único que necesita ``project_blocked_since``) y las activities creadas
    desde ``since``. ``since`` lo manda el cliente a partir de la activity más
    nueva que ya tiene, así que es hora del servidor y no hay desfase de reloj.
    """
    from . import cooling as cooling_svc

    projects = list(ProjectModel.objects.filter(user_id=uid))
    open_tasks = list(
        TaskModel.objects.filter(user_id=uid, done=False).only(
            "id", "project_id", "done"
        )
    )
    open_ids = {t.id for t in open_tasks}
    blocker_map: dict = {}
    for b in TaskBlockerModel.objects.filter(user_id=uid):
        if b.blocked_task_id in open_ids:
            blocker_map.setdefault(b.blocked_task_id, []).append(b)
    blocked_at = cooling_svc.blocked_since_by_project(
        projects, open_tasks, blocker_map
    )
    activities = list(
        ActivityModel.objects.filter(user_id=uid, created__gte=since).order_by(
            "-created"
        )[:DELTA_ACTIVITY_LIMIT]
    )
    return DashboardDeltaData(
        projects=projects,
        blocked_at=blocked_at,
        activities=activities,
        older_done=older_done_by_project(uid, done_window_start(done_task_days)),
        older_notes=(
            {} if all_notes else older_notes_by_project(uid, activity_window_start(activity_days))
        ),
    )


def get_dashboard(
    uid,
    activity_days: Optional[int] = None,
    done_task_days: Optional[int] = None,
    all_notes: bool = True,
) -> DashboardData:
    """Reúne todo el estado del usuario en un solo objeto.

    Consulta varios modelos directamente (un round-trip de producto) y los
    devuelve crudos. Los bloqueadores se agrupan por tarea bloqueada en una
    sola consulta para evitar un N+1 al proyectar las tareas.

    Args:
        uid: UUID del usuario autenticado.
        activity_days: si viene, solo trae las actividades de los últimos N
            días **más todas las notas** (kind=NOTE: son texto del usuario y
            el detalle de proyecto las lista completas). Lo pide el móvil: la
            cuenta más grande pasa de 1,700 actividades y el dashboard se
            descarga varias veces por sesión. El historial completo va por la
            query paginada ``activity``. ``None`` = todo (lo que usa la web).
        done_task_days: si viene, de las tareas **completadas** solo trae las
            de los últimos N días (las abiertas van todas). Las completadas no
            tienen tope en ningún plan y nunca se borran, así que eran lo que
            hacía crecer el dashboard sin fin. Las anteriores se cuentan por
            proyecto (``older_done``) y se listan con ``completedTasks``.
            ``None`` = todas (clientes viejos).

    Returns:
        ``DashboardData`` con los modelos crudos y el ``blocker_map``.
    """
    projects = list(ProjectModel.objects.filter(user_id=uid))
    window = done_window_start(done_task_days)
    task_qs = TaskModel.objects.filter(user_id=uid)
    if window is not None:
        # Abiertas o hechas dentro de la ventana. Escrito como OR positivo (no
        # ``exclude(older_done_q)``) para que Postgres use los dos índices
        # parciales de Task (abiertas / hechas por completed_at); un NOT (...)
        # obliga a recorrer todas las tareas del usuario.
        task_qs = task_qs.filter(
            Q(done=False) | Q(done=True, completed_at__gte=window)
        )
    tasks = list(task_qs)
    ideas = list(IdeaModel.objects.filter(user_id=uid))
    activity_qs = ActivityModel.objects.filter(user_id=uid)
    activity_since = activity_window_start(activity_days)
    if activity_since is not None:
        if all_notes:
            # Clientes viejos: todas las notas de la historia, siempre.
            activity_qs = activity_qs.filter(
                Q(created__gte=activity_since) | Q(kind=ActivityKind.NOTE)
            )
        else:
            # Las notas anteriores se cuentan por proyecto (`older_notes`) y
            # se piden con la query `activity` al abrir el logbook.
            activity_qs = activity_qs.filter(created__gte=activity_since)
    activities = list(activity_qs)
    categories = list(CategoryModel.objects.filter(user_id=uid))
    project_notes = list(ProjectNoteModel.objects.filter(user_id=uid))
    routines = routines_svc.list_routines(uid, include_archived=True)
    routine_occurrences = routines_svc.list_recent_occurrences(uid, days=90)
    meta = BackupMeta.objects.filter(user_id=uid).first()
    blocker_map: dict = {}
    blocker_qs = TaskBlockerModel.objects.filter(user_id=uid)
    if window is not None:
        # Solo los de tareas que viajan; antes se bajaban todos y se
        # filtraban en Python.
        blocker_qs = blocker_qs.filter(blocked_task_id__in=[t.id for t in tasks])
    for b in blocker_qs:
        blocker_map.setdefault(b.blocked_task_id, []).append(b)
    return DashboardData(
        projects=projects,
        tasks=tasks,
        ideas=ideas,
        activities=activities,
        categories=categories,
        project_notes=project_notes,
        routines=routines,
        routine_occurrences=routine_occurrences,
        blocker_map=blocker_map,
        last_backup=meta.last_backup if meta else None,
        older_done=older_done_by_project(uid, window),
        older_notes={} if all_notes else older_notes_by_project(uid, activity_since),
    )

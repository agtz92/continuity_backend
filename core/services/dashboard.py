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


@dataclass
class DashboardDeltaData:
    """Proyectos con su ``blocked_since`` y las activities desde ``since``."""

    projects: list
    blocked_at: dict
    activities: list
    older_done: dict = None


# Tope de activities por delta: una ráfaga normal genera unas pocas. Si alguna
# vez se llega aquí, el cliente igual reconcilia en el siguiente dashboard.
DELTA_ACTIVITY_LIMIT = 200


def get_dashboard_delta(
    uid, since: dt.datetime, done_task_days: Optional[int] = None
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
    blocked_at = {
        p.id: cooling_svc.project_blocked_since(
            p.id, open_tasks, blocker_map, status=p.status
        )
        for p in projects
    }
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
    )


def get_dashboard(
    uid,
    activity_days: Optional[int] = None,
    done_task_days: Optional[int] = None,
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
        task_qs = task_qs.exclude(older_done_q(window))
    tasks = list(task_qs)
    ideas = list(IdeaModel.objects.filter(user_id=uid))
    activity_qs = ActivityModel.objects.filter(user_id=uid)
    if activity_days is not None:
        since = timezone.now() - dt.timedelta(days=max(1, activity_days))
        activity_qs = activity_qs.filter(
            Q(created__gte=since) | Q(kind=ActivityKind.NOTE)
        )
    activities = list(activity_qs)
    categories = list(CategoryModel.objects.filter(user_id=uid))
    project_notes = list(ProjectNoteModel.objects.filter(user_id=uid))
    routines = routines_svc.list_routines(uid, include_archived=True)
    routine_occurrences = routines_svc.list_recent_occurrences(uid, days=90)
    meta = BackupMeta.objects.filter(user_id=uid).first()
    blocker_map: dict = {}
    task_ids = {t.id for t in tasks}
    for b in TaskBlockerModel.objects.filter(user_id=uid):
        if window is None or b.blocked_task_id in task_ids:
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
    )

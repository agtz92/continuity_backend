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

from core.models import (
    Activity as ActivityModel,
    BackupMeta,
    Category as CategoryModel,
    Idea as IdeaModel,
    Project as ProjectModel,
    ProjectNote as ProjectNoteModel,
    Task as TaskModel,
    TaskBlocker as TaskBlockerModel,
)

from . import routines as routines_svc


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


def get_dashboard(uid) -> DashboardData:
    """Reúne todo el estado del usuario en un solo objeto.

    Consulta varios modelos directamente (un round-trip de producto) y los
    devuelve crudos. Los bloqueadores se agrupan por tarea bloqueada en una
    sola consulta para evitar un N+1 al proyectar las tareas.

    Args:
        uid: UUID del usuario autenticado.

    Returns:
        ``DashboardData`` con los modelos crudos y el ``blocker_map``.
    """
    projects = list(ProjectModel.objects.filter(user_id=uid))
    tasks = list(TaskModel.objects.filter(user_id=uid))
    ideas = list(IdeaModel.objects.filter(user_id=uid))
    activities = list(ActivityModel.objects.filter(user_id=uid))
    categories = list(CategoryModel.objects.filter(user_id=uid))
    project_notes = list(ProjectNoteModel.objects.filter(user_id=uid))
    routines = routines_svc.list_routines(uid, include_archived=True)
    routine_occurrences = routines_svc.list_recent_occurrences(uid, days=90)
    meta = BackupMeta.objects.filter(user_id=uid).first()
    blocker_map: dict = {}
    for b in TaskBlockerModel.objects.filter(user_id=uid):
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
    )

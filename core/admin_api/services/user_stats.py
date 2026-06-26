"""Estadísticas por usuario para el panel admin (capa de servicio).

Extrae el acceso a ORM que vivía en ``core/admin_api/schema.py``
(``_build_counts_for`` / ``_bulk_counts`` / ``_last_activity_map``). Devuelve
datos planos (dataclasses, sin tipos Strawberry) para que la capa de servicio
quede independiente del esquema GraphQL; el resolver mapea a los tipos GraphQL.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from django.db.models import Count, Max

from core.models import Activity as ActivityModel
from core.models import Idea as IdeaModel
from core.models import Project as ProjectModel
from core.models import Task as TaskModel


@dataclass(frozen=True)
class EntityCounts:
    """Conteo de objetos de producto de un usuario."""

    projects: int = 0
    tasks_open: int = 0
    tasks_done: int = 0
    ideas: int = 0
    notes: int = 0


def counts_for(user_id: uuid.UUID) -> EntityCounts:
    """Cuenta los objetos de un solo usuario (una query ``COUNT`` por entidad).

    Para los caminos de un único usuario (detalle, mutaciones que devuelven el
    summary). Para listas usar ``bulk_counts`` y evitar el N+1.
    """
    return EntityCounts(
        projects=ProjectModel.objects.filter(user_id=user_id).count(),
        tasks_open=TaskModel.objects.filter(user_id=user_id, done=False).count(),
        tasks_done=TaskModel.objects.filter(user_id=user_id, done=True).count(),
        ideas=IdeaModel.objects.filter(user_id=user_id).count(),
        notes=ActivityModel.objects.filter(user_id=user_id, kind="note").count(),
    )


def bulk_counts(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, EntityCounts]:
    """Cuenta objetos de muchos usuarios de una vez (lista admin, anti-N+1).

    Agrupa con ``annotate(Count)`` para resolver cada entidad en UNA query.
    Los usuarios sin filas en una entidad quedan en 0. Mapa vacío si la lista
    de ids está vacía.
    """
    if not user_ids:
        return {}

    def _grouped(qs):
        return dict(
            qs.values_list("user_id")
            .annotate(c=Count("id"))
            .values_list("user_id", "c")
        )

    projects = _grouped(ProjectModel.objects.filter(user_id__in=user_ids))
    tasks_open = _grouped(
        TaskModel.objects.filter(user_id__in=user_ids, done=False)
    )
    tasks_done = _grouped(
        TaskModel.objects.filter(user_id__in=user_ids, done=True)
    )
    ideas = _grouped(IdeaModel.objects.filter(user_id__in=user_ids))
    notes = _grouped(
        ActivityModel.objects.filter(user_id__in=user_ids, kind="note")
    )
    return {
        uid: EntityCounts(
            projects=projects.get(uid, 0),
            tasks_open=tasks_open.get(uid, 0),
            tasks_done=tasks_done.get(uid, 0),
            ideas=ideas.get(uid, 0),
            notes=notes.get(uid, 0),
        )
        for uid in user_ids
    }


def last_activity_map(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dt.datetime]:
    """``MAX(created)`` de Activity por usuario en UNA query (anti-N+1).

    Los usuarios sin actividad se omiten del mapa. Vacío si la lista está vacía.
    """
    if not user_ids:
        return {}
    rows = (
        ActivityModel.objects.filter(user_id__in=user_ids)
        .values_list("user_id")
        .annotate(latest=Max("created"))
        .values_list("user_id", "latest")
    )
    return {uid: latest for uid, latest in rows if latest is not None}

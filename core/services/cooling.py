"""Enfriamiento y bloqueo derivados: la fuente única de los tramos.

El rediseño trata el tiempo como material — un proyecto frío se ve frío — y
para eso la UI necesita dos datos que hoy cada cliente recalculaba a su manera:

  * ``days_since_touch``: días desde el último movimiento del proyecto.
  * ``cooling``: en qué tramo cae ese número.

Los tramos viven **aquí y solo aquí** (REDISENO_PLAN.md §8). Si web y móvil los
calculan por su cuenta, tarde o temprano discrepan y el usuario ve "11 días" en
una pantalla y "frío" en otra con el mismo proyecto.

El bloqueo también se deriva: "atorado" no es un estado del modelo. Un proyecto
está atorado si tiene al menos una tarea abierta con un blocker sin resolver.
Ver DP-03 en REDISENO_PLAN.md — se decidió derivarlo en vez de añadirlo al enum
de ``ProjectStatus``.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable, Optional

from django.utils import timezone

# Tramos de enfriamiento, en días desde el último movimiento.
#   warm  0-7    · el proyecto está vivo
#   cool  8-21   · se está apagando
#   cold  22+    · frío; a los 45 el producto pregunta si sigue vivo
COOLING_WARM_MAX = 7
COOLING_COOL_MAX = 21

WARM = "warm"
COOL = "cool"
COLD = "cold"


def days_since_touch(last_activity: Optional[dt.datetime], now: Optional[dt.datetime] = None) -> int:
    """Días completos desde el último movimiento. 0 si nunca se tocó."""
    if last_activity is None:
        return 0
    ref = now or timezone.now()
    delta = ref - last_activity
    return max(delta.days, 0)


def cooling(days: int) -> str:
    """Tramo de enfriamiento para un número de días."""
    if days <= COOLING_WARM_MAX:
        return WARM
    if days <= COOLING_COOL_MAX:
        return COOL
    return COLD


def blocked_since(blockers: Iterable) -> Optional[dt.datetime]:
    """El blocker abierto más antiguo de un conjunto. ``None`` si no hay.

    Se toma el más antiguo, no el más reciente: lo que importa es cuánto lleva
    la cosa detenida, no cuándo fue la última vez que alguien lo apuntó.
    """
    created = [b.created for b in blockers if b.created is not None]
    return min(created) if created else None


def blocked_reason(blockers: Iterable) -> str:
    """La razón del blocker más antiguo. Cadena vacía si no la hay.

    Solo se expone la descripción externa: cuando el blocker es otra tarea, la
    UI ya tiene el id y resuelve el título por su cuenta.
    """
    ordered = sorted(
        (b for b in blockers if b.created is not None), key=lambda b: b.created
    )
    for b in ordered:
        if b.external_description:
            return b.external_description
    return ""


def project_blocked_since(
    project_id, tasks: Iterable, blocker_map: dict
) -> Optional[dt.datetime]:
    """Desde cuándo está atorado un proyecto, mirando sus tareas abiertas.

    Args:
        project_id: id del proyecto.
        tasks: tareas del usuario (se filtran aquí por proyecto).
        blocker_map: ``task_id -> [TaskBlocker]``, ya precargado por el
            servicio de dashboard para no disparar un N+1.

    Returns:
        La fecha del blocker abierto más antiguo entre sus tareas pendientes,
        o ``None`` si el proyecto no está atorado.
    """
    found = []
    for t in tasks:
        if t.project_id != project_id or t.done:
            continue
        found.extend(blocker_map.get(t.id, []))
    return blocked_since(found)

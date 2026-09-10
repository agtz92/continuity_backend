"""Enfriamiento y atoro derivados (REDISENO_PLAN.md §8).

Los tramos son la razón de ser de este módulo: si alguien los mueve sin querer,
web y móvil empiezan a decir cosas distintas del mismo proyecto.
"""

import datetime as dt

import pytest
from django.utils import timezone

from core.models import Project, Task, TaskBlocker
from core.services import cooling as svc


def _dias(n: int) -> dt.datetime:
    return timezone.now() - dt.timedelta(days=n)


class _Blocker:
    """Doble mínimo: solo se leen `created` y `external_description`."""

    def __init__(self, created, description=""):
        self.created = created
        self.external_description = description


def test_tramos_de_enfriamiento():
    # Las fronteras son lo que se rompe al "afinar" los tramos.
    assert svc.cooling(0) == svc.WARM
    assert svc.cooling(7) == svc.WARM
    assert svc.cooling(8) == svc.COOL
    assert svc.cooling(21) == svc.COOL
    assert svc.cooling(22) == svc.COLD
    assert svc.cooling(365) == svc.COLD


def test_dias_sin_tocar_cuenta_dias_completos():
    assert svc.days_since_touch(_dias(3)) == 3
    assert svc.days_since_touch(timezone.now()) == 0
    # Un last_activity en el futuro (reloj torcido) no devuelve negativos.
    assert svc.days_since_touch(timezone.now() + dt.timedelta(days=2)) == 0
    assert svc.days_since_touch(None) == 0


def test_blocked_since_toma_el_mas_antiguo():
    # Importa cuánto lleva detenido, no cuándo se apuntó por última vez.
    viejo, nuevo = _dias(9), _dias(2)
    assert svc.blocked_since([_Blocker(nuevo), _Blocker(viejo)]) == viejo
    assert svc.blocked_since([]) is None


def test_blocked_reason_prefiere_el_mas_antiguo_con_texto():
    blockers = [
        _Blocker(_dias(9)),  # blocker por tarea: sin descripción externa
        _Blocker(_dias(5), "Esperando acceso al DNS"),
        _Blocker(_dias(1), "Otra cosa"),
    ]
    assert svc.blocked_reason(blockers) == "Esperando acceso al DNS"
    assert svc.blocked_reason([_Blocker(_dias(1))]) == ""


@pytest.mark.django_db
def test_proyecto_atorado_solo_por_tareas_abiertas(user_a):
    p = Project.objects.create(user_id=user_a, name="ERP de Vela")
    abierta = Task.objects.create(user_id=user_a, project=p, title="Migrar contactos")
    cerrada = Task.objects.create(
        user_id=user_a, project=p, title="Exportar esquema", done=True
    )
    otro = Project.objects.create(user_id=user_a, name="Landing")

    b_abierta = TaskBlocker.objects.create(
        user_id=user_a, blocked_task=abierta, external_description="Sin credenciales"
    )
    b_cerrada = TaskBlocker.objects.create(
        user_id=user_a, blocked_task=cerrada, external_description="Ya no aplica"
    )
    blocker_map = {abierta.id: [b_abierta], cerrada.id: [b_cerrada]}
    tasks = [abierta, cerrada]

    # La tarea cerrada no atora: su blocker es historia.
    assert svc.project_blocked_since(p.id, tasks, blocker_map) == b_abierta.created
    # Un proyecto sin tareas bloqueadas no está atorado.
    assert svc.project_blocked_since(otro.id, tasks, blocker_map) is None

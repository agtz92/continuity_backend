"""Las mutaciones de tarea devuelven los bloqueadores que de verdad tiene.

Regresión de un bug que no rompía nada en el servidor y sí en los clientes.

`Task.from_model` recibe los bloqueadores en lugar de consultarlos, para que el
dashboard los precargue en bloque y evite el N+1. Ese parámetro tiene default de
lista vacía, y `update_task` y `toggle_task` lo usaban tal cual — así que
respondían `blockers: []`, `blockedSince: null` y `blockedReason: ""` a clientes
que **sí piden ese campo** en la mutación.

Apollo hace entonces lo único que puede: reemplaza el array de su caché por el
vacío que le llegó, y avisa con un warning que nadie leía. En pantalla, una
tarea bloqueada dejaba de parecerlo en cuanto la tocabas, y su proyecto perdía
el badge de atasco.

Ninguno de los trece tests de tareas que ya existían lo detectaba, porque todos
preguntaban por `id`, `title` y `done` — nunca por `blockers`. El bug vivía
exactamente en el hueco entre lo que el servidor devuelve y lo que el cliente
pide.
"""

import pytest

from core.models import TaskBlocker


UPDATE_TASK_WITH_BLOCKERS = """
    mutation($id: ID!, $data: TaskInput!) {
        updateTask(id: $id, data: $data) {
            id
            title
            blockedSince
            blockedReason
            blockers { id externalDescription }
        }
    }
"""

TOGGLE_TASK_WITH_BLOCKERS = """
    mutation($id: ID!) {
        toggleTask(id: $id) {
            id
            done
            blockedSince
            blockedReason
            blockers { id externalDescription }
        }
    }
"""


@pytest.mark.django_db
def test_update_task_devuelve_los_bloqueadores_existentes(
    execute_query, user_a, task_factory
):
    task = task_factory(user_a, title="Antes")
    TaskBlocker.objects.create(
        user_id=user_a,
        blocked_task=task,
        external_description="esperando el contrato firmado",
    )

    result = execute_query(
        UPDATE_TASK_WITH_BLOCKERS,
        user_id=user_a,
        variable_values={"id": str(task.id), "data": {"title": "Después"}},
    )

    assert result.errors is None
    payload = result.data["updateTask"]
    assert len(payload["blockers"]) == 1
    assert payload["blockers"][0]["externalDescription"] == (
        "esperando el contrato firmado"
    )
    # Los derivados salen de la misma lista: si llega vacía, el badge de bloqueo
    # se queda sin razón que mostrar y "bloqueado" no le dice nada a nadie.
    assert payload["blockedReason"] == "esperando el contrato firmado"
    assert payload["blockedSince"] is not None


@pytest.mark.django_db
def test_toggle_task_devuelve_los_bloqueadores_existentes(
    execute_query, user_a, task_factory
):
    task = task_factory(user_a, title="Bloqueada")
    TaskBlocker.objects.create(
        user_id=user_a, blocked_task=task, external_description="falta el acceso"
    )

    result = execute_query(
        TOGGLE_TASK_WITH_BLOCKERS,
        user_id=user_a,
        variable_values={"id": str(task.id)},
    )

    assert result.errors is None
    payload = result.data["toggleTask"]
    assert payload["done"] is True
    assert len(payload["blockers"]) == 1
    assert payload["blockedReason"] == "falta el acceso"


@pytest.mark.django_db
def test_una_tarea_sin_bloqueadores_sigue_devolviendo_lista_vacia(
    execute_query, user_a, task_factory
):
    """El arreglo no puede inventar bloqueos donde no los hay."""
    task = task_factory(user_a, title="Libre")

    result = execute_query(
        TOGGLE_TASK_WITH_BLOCKERS,
        user_id=user_a,
        variable_values={"id": str(task.id)},
    )

    assert result.errors is None
    payload = result.data["toggleTask"]
    assert payload["blockers"] == []
    assert payload["blockedSince"] is None
    assert payload["blockedReason"] == ""

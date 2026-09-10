"""La escritura de la captura rápida (⌘K): atómica e idempotente.

La captura escribía en dos pasos — `createTask` y luego `addTaskBlocker` — y
los dos fallos posibles eran silenciosos: si el segundo paso se caía quedaba una
tarea sin su bloqueo, y si el usuario reintentaba se creaba una tarea duplicada
porque el primer paso ya había entrado.

Estos tests fijan las dos garantías nuevas: `blocker` viaja dentro de
`TaskInput` (o entran los dos o no entra ninguno) y `clientToken` hace que
reintentar devuelva **la misma** tarea.
"""

import uuid

import pytest

from core.models import Task, TaskBlocker

CREATE_TASK = """
    mutation($data: TaskInput!) {
        createTask(data: $data) {
            id
            title
            projectId
            blockedReason
            blockers { id externalDescription }
        }
    }
"""


@pytest.mark.django_db
def test_blocker_viaja_dentro_de_create_task(execute_query, user_a, project_factory):
    """Una sola mutation deja la tarea y su bloqueo en el mismo commit."""
    project = project_factory(user_a)

    result = execute_query(
        CREATE_TASK,
        user_id=user_a,
        variable_values={
            "data": {
                "title": "Firmar el anexo",
                "projectId": str(project.id),
                "blocker": "falta el poder notarial",
            }
        },
    )

    assert result.errors is None
    task = result.data["createTask"]
    assert task["title"] == "Firmar el anexo"
    assert [b["externalDescription"] for b in task["blockers"]] == [
        "falta el poder notarial"
    ]
    assert task["blockedReason"] == "falta el poder notarial"
    assert TaskBlocker.objects.filter(user_id=user_a).count() == 1


@pytest.mark.django_db
def test_sin_blocker_no_se_inventa_ninguno(execute_query, user_a):
    result = execute_query(
        CREATE_TASK,
        user_id=user_a,
        variable_values={"data": {"title": "Comprar café"}},
    )

    assert result.errors is None
    assert result.data["createTask"]["blockers"] == []
    assert TaskBlocker.objects.filter(user_id=user_a).count() == 0


@pytest.mark.django_db
def test_el_mismo_client_token_no_duplica(execute_query, user_a):
    """Reintentar una captura que sí había entrado devuelve la tarea original."""
    token = uuid.uuid4().hex

    first = execute_query(
        CREATE_TASK,
        user_id=user_a,
        variable_values={
            "data": {"title": "Llamar al notario", "clientToken": token}
        },
    )
    second = execute_query(
        CREATE_TASK,
        user_id=user_a,
        variable_values={
            # El reintento manda lo mismo; el título podría venir editado y aun
            # así no debe crear una segunda tarea.
            "data": {"title": "Llamar al notario", "clientToken": token}
        },
    )

    assert first.errors is None and second.errors is None
    assert first.data["createTask"]["id"] == second.data["createTask"]["id"]
    assert Task.objects.filter(user_id=user_a).count() == 1


@pytest.mark.django_db
def test_el_token_es_por_usuario(execute_query, user_a, user_b):
    """Dos personas pueden generar el mismo token sin pisarse."""
    token = uuid.uuid4().hex
    payload = {"data": {"title": "Revisar contrato", "clientToken": token}}

    a = execute_query(CREATE_TASK, user_id=user_a, variable_values=payload)
    b = execute_query(CREATE_TASK, user_id=user_b, variable_values=payload)

    assert a.errors is None and b.errors is None
    assert a.data["createTask"]["id"] != b.data["createTask"]["id"]
    assert Task.objects.filter(user_id=user_a).count() == 1
    assert Task.objects.filter(user_id=user_b).count() == 1


@pytest.mark.django_db
def test_sin_token_no_hay_idempotencia(execute_query, user_a):
    """El resto de la app escribe desde formularios: dos envíos, dos tareas."""
    payload = {"data": {"title": "Comprar café"}}

    execute_query(CREATE_TASK, user_id=user_a, variable_values=payload)
    execute_query(CREATE_TASK, user_id=user_a, variable_values=payload)

    assert Task.objects.filter(user_id=user_a).count() == 2

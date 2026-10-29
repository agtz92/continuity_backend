"""La cola offline de la app móvil: creates con id propio y `setTaskDone`.

Sin red, la app crea con un UUID que ella misma genera y reenvía la operación
hasta que el servidor contesta. Así que el mismo create puede llegar dos veces
(la respuesta se perdió) y un cambio de estado puede llegar tarde. Estos tests
fijan las garantías que la cola necesita:

- Un create con `id` deja la fila con **ese** id, y reenviarlo devuelve la misma
  fila en vez de duplicarla.
- Un `id` de otro usuario o que no es UUID se rechaza como NOT_FOUND.
- `setTaskDone` es idempotente: repetirlo no invierte la tarea ni duplica la
  activity de completada.
"""

import datetime as dt
import uuid

import pytest

from core.models import (
    Activity,
    ActivityKind,
    Idea,
    NoteSection,
    QuickNote,
    RecurrenceType,
    RoutineOccurrence,
    Task,
)
from core.services import routines as routines_svc

CREATE_TASK = """
    mutation($data: TaskInput!) { createTask(data: $data) { id title done } }
"""
CREATE_IDEA = """
    mutation($data: IdeaInput!) { createIdea(data: $data) { id title } }
"""
CREATE_QUICK_NOTE = """
    mutation($data: QuickNoteInput!) { createQuickNote(data: $data) { id title } }
"""
ADD_NOTE_SECTION = """
    mutation($noteId: ID!, $data: NoteSectionInput!) {
        addNoteSection(noteId: $noteId, data: $data) { id heading }
    }
"""
ADD_NOTE = """
    mutation($projectId: ID!, $note: String!, $id: ID) {
        addNote(projectId: $projectId, note: $note, id: $id) { id note }
    }
"""
COMPLETE_OCCURRENCE = """
    mutation($routineId: ID!, $date: Date!, $id: ID) {
        completeRoutineOccurrence(routineId: $routineId, scheduledDate: $date, id: $id) { id }
    }
"""
SET_TASK_DONE = """
    mutation($id: ID!, $done: Boolean!) { setTaskDone(id: $id, done: $done) { id done } }
"""


def _code(result):
    return result.errors[0].extensions.get("code") if result.errors else None


@pytest.mark.django_db
def test_create_task_con_id_usa_ese_id_y_reintentar_no_duplica(execute_query, user_a):
    client_id = str(uuid.uuid4())
    variables = {"data": {"title": "Comprar pan", "id": client_id}}

    first = execute_query(CREATE_TASK, user_id=user_a, variable_values=variables)
    again = execute_query(CREATE_TASK, user_id=user_a, variable_values=variables)

    assert first.errors is None and again.errors is None
    assert first.data["createTask"]["id"] == client_id
    assert again.data["createTask"]["id"] == client_id
    assert Task.objects.filter(user_id=user_a).count() == 1


@pytest.mark.django_db
def test_create_task_sin_id_sigue_igual(execute_query, user_a):
    result = execute_query(
        CREATE_TASK, user_id=user_a, variable_values={"data": {"title": "Normal"}}
    )
    assert result.errors is None
    assert Task.objects.filter(user_id=user_a).count() == 1


@pytest.mark.django_db
def test_id_de_otro_usuario_se_rechaza(execute_query, user_a, user_b, task_factory):
    ajena = task_factory(user_b, title="De B")

    result = execute_query(
        CREATE_TASK,
        user_id=user_a,
        variable_values={"data": {"title": "Pirata", "id": str(ajena.id)}},
    )

    assert _code(result) == "NOT_FOUND"
    assert Task.objects.get(pk=ajena.id).title == "De B"
    assert not Task.objects.filter(user_id=user_a).exists()


@pytest.mark.django_db
def test_id_que_no_es_uuid_se_rechaza(execute_query, user_a):
    result = execute_query(
        CREATE_IDEA,
        user_id=user_a,
        variable_values={"data": {"title": "x", "id": "tmp-123"}},
    )
    assert _code(result) == "NOT_FOUND"
    assert not Idea.objects.filter(user_id=user_a).exists()


@pytest.mark.django_db
def test_create_idea_idempotente(execute_query, user_a):
    client_id = str(uuid.uuid4())
    variables = {"data": {"title": "Idea offline", "id": client_id}}
    execute_query(CREATE_IDEA, user_id=user_a, variable_values=variables)
    result = execute_query(CREATE_IDEA, user_id=user_a, variable_values=variables)

    assert result.data["createIdea"]["id"] == client_id
    assert Idea.objects.filter(user_id=user_a).count() == 1
    # Solo una activity de "idea creada", no una por reintento.
    assert (
        Activity.objects.filter(user_id=user_a, kind=ActivityKind.IDEA_CREATED).count()
        == 1
    )


@pytest.mark.django_db
def test_quick_note_y_seccion_idempotentes(execute_query, user_a):
    note_id = str(uuid.uuid4())
    section_id = str(uuid.uuid4())
    note_vars = {"data": {"title": "En el avión", "id": note_id}}
    section_vars = {"noteId": note_id, "data": {"heading": "Ideas", "id": section_id}}

    for _ in range(2):
        r1 = execute_query(CREATE_QUICK_NOTE, user_id=user_a, variable_values=note_vars)
        r2 = execute_query(ADD_NOTE_SECTION, user_id=user_a, variable_values=section_vars)
        assert r1.errors is None and r2.errors is None

    assert QuickNote.objects.filter(user_id=user_a).count() == 1
    assert NoteSection.objects.filter(user_id=user_a).count() == 1
    assert str(NoteSection.objects.get(user_id=user_a).note_id) == note_id


@pytest.mark.django_db
def test_add_note_idempotente(execute_query, user_a, project_factory):
    project = project_factory(user_a)
    client_id = str(uuid.uuid4())
    variables = {"projectId": str(project.id), "note": "avance", "id": client_id}

    execute_query(ADD_NOTE, user_id=user_a, variable_values=variables)
    result = execute_query(ADD_NOTE, user_id=user_a, variable_values=variables)

    assert result.data["addNote"]["id"] == client_id
    assert Activity.objects.filter(user_id=user_a, kind=ActivityKind.NOTE).count() == 1


@pytest.mark.django_db
def test_complete_occurrence_usa_el_id_del_cliente_si_es_nueva(execute_query, user_a):
    routine = routines_svc.create_routine(
        user_a,
        title="Correr",
        recurrence_type=RecurrenceType.WEEKLY_DAYS,
        start_date=dt.date(2026, 1, 1),
        weekdays=[0, 1, 2, 3, 4, 5, 6],
    )
    client_id = str(uuid.uuid4())
    variables = {"routineId": str(routine.id), "date": "2026-10-29", "id": client_id}

    first = execute_query(COMPLETE_OCCURRENCE, user_id=user_a, variable_values=variables)
    again = execute_query(COMPLETE_OCCURRENCE, user_id=user_a, variable_values=variables)

    assert first.errors is None and again.errors is None
    assert first.data["completeRoutineOccurrence"]["id"] == client_id
    assert RoutineOccurrence.objects.filter(user_id=user_a).count() == 1


@pytest.mark.django_db
def test_set_task_done_es_idempotente(execute_query, user_a, task_factory):
    task = task_factory(user_a, title="Pagar luz")
    variables = {"id": str(task.id), "done": True}

    for _ in range(2):
        result = execute_query(SET_TASK_DONE, user_id=user_a, variable_values=variables)
        assert result.errors is None
        assert result.data["setTaskDone"]["done"] is True

    task.refresh_from_db()
    assert task.done is True and task.completed_at is not None
    assert (
        Activity.objects.filter(
            user_id=user_a, kind=ActivityKind.TASK_COMPLETED
        ).count()
        == 1
    )

    undo = execute_query(
        SET_TASK_DONE, user_id=user_a, variable_values={"id": str(task.id), "done": False}
    )
    assert undo.data["setTaskDone"]["done"] is False
    task.refresh_from_db()
    assert task.completed_at is None


@pytest.mark.django_db
def test_set_task_done_de_otro_usuario(execute_query, user_a, user_b, task_factory):
    task = task_factory(user_b)
    result = execute_query(
        SET_TASK_DONE, user_id=user_a, variable_values={"id": str(task.id), "done": True}
    )
    assert _code(result) == "NOT_FOUND"
    task.refresh_from_db()
    assert task.done is False


CREATE_ROUTINE = """
    mutation($data: RoutineInput!) { createRoutine(data: $data) { id title } }
"""


@pytest.mark.django_db
def test_create_routine_idempotente(execute_query, user_a):
    from core.models import Routine

    client_id = str(uuid.uuid4())
    variables = {
        "data": {
            "title": "Leer",
            "recurrenceType": "weekly_days",
            "startDate": "2026-10-29",
            "weekdays": [0, 2, 4],
            "id": client_id,
        }
    }
    first = execute_query(CREATE_ROUTINE, user_id=user_a, variable_values=variables)
    again = execute_query(CREATE_ROUTINE, user_id=user_a, variable_values=variables)

    assert first.errors is None and again.errors is None
    assert first.data["createRoutine"]["id"] == client_id
    assert again.data["createRoutine"]["id"] == client_id
    assert Routine.objects.filter(user_id=user_a).count() == 1

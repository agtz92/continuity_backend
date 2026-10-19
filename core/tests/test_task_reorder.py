"""Manual task order inside a project: position assignment + reorder."""

from __future__ import annotations

import uuid

import pytest

from core.models import Task
from core.services import projects as projects_svc
from core.services import tasks as tasks_svc
from core.services.projects import NotFoundError


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


def _pos(task) -> int:
    return Task.objects.get(pk=task.id).position


@pytest.mark.django_db
def test_new_tasks_land_at_the_end(user_id):
    p = projects_svc.create_project(user_id, name="P")
    a = tasks_svc.create_task(user_id, title="A", project_id=p.id)
    b = tasks_svc.create_task(user_id, title="B", project_id=p.id)
    c = tasks_svc.create_task(user_id, title="C", project_id=p.id)
    assert (_pos(a), _pos(b), _pos(c)) == (0, 1, 2)


@pytest.mark.django_db
def test_positions_are_per_project(user_id):
    p1 = projects_svc.create_project(user_id, name="P1")
    p2 = projects_svc.create_project(user_id, name="P2")
    tasks_svc.create_task(user_id, title="A", project_id=p1.id)
    tasks_svc.create_task(user_id, title="B", project_id=p1.id)
    first_in_p2 = tasks_svc.create_task(user_id, title="C", project_id=p2.id)
    assert _pos(first_in_p2) == 0


@pytest.mark.django_db
def test_reorder_assigns_dense_positions(user_id):
    p = projects_svc.create_project(user_id, name="P")
    a = tasks_svc.create_task(user_id, title="A", project_id=p.id)
    b = tasks_svc.create_task(user_id, title="B", project_id=p.id)
    c = tasks_svc.create_task(user_id, title="C", project_id=p.id)

    rows = tasks_svc.reorder_project_tasks(user_id, p.id, [c.id, a.id, b.id])

    assert [t.id for t in rows] == [c.id, a.id, b.id]
    assert (_pos(c), _pos(a), _pos(b)) == (0, 1, 2)


@pytest.mark.django_db
def test_reorder_ignores_tasks_of_other_projects_and_users(user_id):
    p = projects_svc.create_project(user_id, name="P")
    other_p = projects_svc.create_project(user_id, name="Other")
    a = tasks_svc.create_task(user_id, title="A", project_id=p.id)
    elsewhere = tasks_svc.create_task(user_id, title="X", project_id=other_p.id)
    stranger = uuid.uuid4()
    sp = projects_svc.create_project(stranger, name="S")
    foreign = tasks_svc.create_task(stranger, title="F", project_id=sp.id)

    tasks_svc.reorder_project_tasks(user_id, p.id, [foreign.id, elsewhere.id, a.id])

    assert _pos(a) == 2
    assert _pos(elsewhere) == 0
    assert _pos(foreign) == 0


@pytest.mark.django_db
def test_reorder_foreign_project_raises(user_id):
    stranger_project = projects_svc.create_project(uuid.uuid4(), name="S")
    with pytest.raises(NotFoundError):
        tasks_svc.reorder_project_tasks(user_id, stranger_project.id, [])


@pytest.mark.django_db
def test_moving_task_to_another_project_appends_it(user_id):
    p1 = projects_svc.create_project(user_id, name="P1")
    p2 = projects_svc.create_project(user_id, name="P2")
    tasks_svc.create_task(user_id, title="B1", project_id=p2.id)
    tasks_svc.create_task(user_id, title="B2", project_id=p2.id)
    a = tasks_svc.create_task(user_id, title="A", project_id=p1.id)

    tasks_svc.update_task(user_id, a.id, title="A", project_id=p2.id)
    assert _pos(a) == 2

    # Editing without changing project keeps the position.
    tasks_svc.update_task(user_id, a.id, title="A renamed", project_id=p2.id)
    assert _pos(a) == 2

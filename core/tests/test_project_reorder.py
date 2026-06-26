"""Manual project ordering ("Mi orden"): position assignment + reorder."""

from __future__ import annotations

import uuid

import pytest

from core.models import Project
from core.services import projects as projects_svc


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.mark.django_db
def test_create_appends_position_at_end(user_id):
    a = projects_svc.create_project(user_id, name="A")
    b = projects_svc.create_project(user_id, name="B")
    c = projects_svc.create_project(user_id, name="C")
    # Each new project gets a strictly increasing position (lands at the end).
    assert a.position < b.position < c.position


@pytest.mark.django_db
def test_reorder_assigns_dense_positions(user_id):
    a = projects_svc.create_project(user_id, name="A")
    b = projects_svc.create_project(user_id, name="B")
    c = projects_svc.create_project(user_id, name="C")

    projects_svc.reorder_projects(user_id, [c.id, a.id, b.id])

    assert Project.objects.get(pk=c.id).position == 0
    assert Project.objects.get(pk=a.id).position == 1
    assert Project.objects.get(pk=b.id).position == 2


@pytest.mark.django_db
def test_reorder_ignores_foreign_ids_and_keeps_owner_scope(user_id):
    other = uuid.uuid4()
    mine = projects_svc.create_project(user_id, name="Mine")
    theirs = projects_svc.create_project(other, name="Theirs")

    # A foreign id in the list is silently ignored; the foreign project is
    # never touched.
    projects_svc.reorder_projects(user_id, [theirs.id, mine.id])

    assert Project.objects.get(pk=mine.id).position == 1
    # Theirs keeps whatever position create_project gave it (untouched).
    assert Project.objects.get(pk=theirs.id).position == theirs.position

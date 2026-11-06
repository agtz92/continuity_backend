"""`dashboardDelta`: la reconciliación barata que la web pide tras escribir.

Trae los proyectos con sus derivados (sobre todo `blockedSince`, que depende de
las tareas abiertas y sus blockers) y solo las activities desde `since`.
"""

import datetime as dt

import pytest
from django.utils import timezone

from core.models import Activity, ActivityKind, TaskBlocker

DELTA = """
    query($since: DateTime!) {
        dashboardDelta(since: $since) {
            projects { id name isBlocked blockedSince cooling }
            activities { id kind note }
        }
    }
"""


def _since(delta: dt.timedelta) -> str:
    return (timezone.now() - delta).isoformat()


@pytest.mark.django_db
def test_delta_returns_projects_and_only_new_activities(
    execute_query, user_a, project_factory
):
    project = project_factory(user_a, name="Mine")
    old = Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=project.id, note="old"
    )
    Activity.objects.filter(pk=old.pk).update(
        created=timezone.now() - dt.timedelta(days=2)
    )
    Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=project.id, note="new"
    )

    res = execute_query(
        DELTA, user_id=user_a, variable_values={"since": _since(dt.timedelta(hours=1))}
    )

    assert res.errors is None
    delta = res.data["dashboardDelta"]
    assert [p["name"] for p in delta["projects"]] == ["Mine"]
    assert [a["note"] for a in delta["activities"]] == ["new"]


@pytest.mark.django_db
def test_delta_computes_blocked_from_open_tasks_only(
    execute_query, user_a, project_factory, task_factory
):
    project = project_factory(user_a, name="P")
    blocked = task_factory(user_a, project=project, title="blocked")
    TaskBlocker.objects.create(
        user_id=user_a, blocked_task=blocked, external_description="waiting"
    )

    def is_blocked():
        res = execute_query(
            DELTA, user_id=user_a, variable_values={"since": _since(dt.timedelta(hours=1))}
        )
        assert res.errors is None
        return res.data["dashboardDelta"]["projects"][0]["isBlocked"]

    assert is_blocked() is True
    blocked.done = True
    blocked.save()
    assert is_blocked() is False


@pytest.mark.django_db
def test_delta_isolates_users(execute_query, user_a, user_b, project_factory):
    project_factory(user_b, name="B's")
    res = execute_query(
        DELTA, user_id=user_a, variable_values={"since": _since(dt.timedelta(days=1))}
    )
    assert res.errors is None
    assert res.data["dashboardDelta"]["projects"] == []


@pytest.mark.django_db
def test_delta_requires_auth(execute_query):
    res = execute_query(
        DELTA, user_id=None, variable_values={"since": _since(dt.timedelta(days=1))}
    )
    assert res.errors

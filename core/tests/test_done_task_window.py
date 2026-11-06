"""Ventana de completadas del dashboard (`doneTaskDays`) y `completedTasks`.

Las completadas no tienen tope en ningún plan y nunca se borran: eran lo que
hacía crecer el dashboard sin fin. Con ventana, el dashboard trae las abiertas
y las completadas recientes; las anteriores se cuentan por proyecto y se listan
paginadas.
"""

import datetime as dt

import pytest
from django.utils import timezone

DASH = """
    query($days: Int) {
        dashboard(activityDays: 60, doneTaskDays: $days) {
            projects { id olderDoneCount olderDoneEffortHours }
            tasks { id title done }
        }
    }
"""

COMPLETED = """
    query($before: DateTime!, $projectId: ID, $offset: Int, $limit: Int) {
        completedTasks(before: $before, projectId: $projectId, offset: $offset, limit: $limit) {
            id title done
        }
    }
"""


@pytest.fixture
def seeded(user_a, project_factory, task_factory):
    now = timezone.now()
    p = project_factory(user_a, name="P")
    task_factory(user_a, project=p, title="open")
    task_factory(user_a, project=p, title="recent", done=True, completed_at=now - dt.timedelta(days=2))
    task_factory(
        user_a, project=p, title="old", done=True,
        completed_at=now - dt.timedelta(days=90), effort_hours=1.5,
    )
    task_factory(
        user_a, project=p, title="older", done=True,
        completed_at=now - dt.timedelta(days=200), effort_hours=2,
    )
    task_factory(user_a, project=p, title="legacy", done=True, completed_at=None)
    return p


def _titles(rows):
    return sorted(r["title"] for r in rows)


@pytest.mark.django_db
def test_without_window_everything_comes(execute_query, user_a, seeded):
    res = execute_query(DASH, user_id=user_a, variable_values={"days": None})
    assert res.errors is None
    dash = res.data["dashboard"]
    assert _titles(dash["tasks"]) == ["legacy", "old", "older", "open", "recent"]
    assert dash["projects"][0]["olderDoneCount"] == 0


@pytest.mark.django_db
def test_window_keeps_open_and_recent_and_counts_the_rest(execute_query, user_a, seeded):
    res = execute_query(DASH, user_id=user_a, variable_values={"days": 30})
    assert res.errors is None
    dash = res.data["dashboard"]
    assert _titles(dash["tasks"]) == ["open", "recent"]
    project = dash["projects"][0]
    assert project["olderDoneCount"] == 3
    assert project["olderDoneEffortHours"] == pytest.approx(3.5)


@pytest.mark.django_db
def test_completed_tasks_pages_the_older_ones_newest_first(execute_query, user_a, seeded):
    before = (timezone.now() - dt.timedelta(days=30)).isoformat()
    res = execute_query(
        COMPLETED, user_id=user_a,
        variable_values={"before": before, "projectId": str(seeded.id), "limit": 2},
    )
    assert res.errors is None
    assert [t["title"] for t in res.data["completedTasks"]] == ["old", "older"]
    res = execute_query(
        COMPLETED, user_id=user_a,
        variable_values={"before": before, "projectId": str(seeded.id), "offset": 2, "limit": 2},
    )
    assert [t["title"] for t in res.data["completedTasks"]] == ["legacy"]


@pytest.mark.django_db
def test_completed_tasks_isolates_users(execute_query, user_b, seeded):
    before = (timezone.now() - dt.timedelta(days=30)).isoformat()
    res = execute_query(COMPLETED, user_id=user_b, variable_values={"before": before})
    assert res.errors is None
    assert res.data["completedTasks"] == []


@pytest.mark.django_db
def test_completed_tasks_bad_project_id_is_empty(execute_query, user_a, seeded):
    before = (timezone.now() - dt.timedelta(days=30)).isoformat()
    res = execute_query(
        COMPLETED, user_id=user_a, variable_values={"before": before, "projectId": "nope"}
    )
    assert res.errors is None
    assert res.data["completedTasks"] == []


@pytest.mark.django_db
def test_delta_carries_older_done_counts(execute_query, user_a, seeded):
    res = execute_query(
        """query($s: DateTime!) { dashboardDelta(since: $s, doneTaskDays: 30) {
            projects { olderDoneCount } } }""",
        user_id=user_a,
        variable_values={"s": timezone.now().isoformat()},
    )
    assert res.errors is None
    assert res.data["dashboardDelta"]["projects"][0]["olderDoneCount"] == 3

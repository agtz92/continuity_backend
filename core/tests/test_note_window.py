"""`allNotes: false`: el dashboard deja de traer las notas de toda la historia.

Las anteriores a `activityDays` se cuentan por proyecto (`olderNoteCount`, en
dashboard y delta, para que el logbook no pierda el número) y se piden con
`activity(projectId, kinds: ["note"], until)`.
"""

import datetime as dt

import pytest
from django.utils import timezone

from core.models import Activity

DASH = """
    query($all: Boolean!) {
        dashboard(activityDays: 60, doneTaskDays: 30, allNotes: $all) {
            projects { id olderNoteCount }
            activities { id kind note }
        }
    }
"""

DELTA = """
    query($since: DateTime!) {
        dashboardDelta(since: $since, doneTaskDays: 30, activityDays: 60, allNotes: false) {
            projects { id olderNoteCount }
        }
    }
"""

FEED = """
    query($pid: ID, $until: DateTime) {
        activity(projectId: $pid, kinds: ["note"], until: $until, limit: 50) { id note }
    }
"""


def _note(user, project, text, days_ago):
    a = Activity.objects.create(
        user_id=user, project_id=project.id, kind="note", note=text
    )
    Activity.objects.filter(pk=a.pk).update(
        created=timezone.now() - dt.timedelta(days=days_ago)
    )
    return a


@pytest.fixture
def seeded(user_a, project_factory):
    p = project_factory(user_a, name="P")
    _note(user_a, p, "new", 3)
    _note(user_a, p, "old", 120)
    _note(user_a, p, "older", 400)
    return p


@pytest.mark.django_db
def test_all_notes_keeps_old_behaviour(execute_query, user_a, seeded):
    res = execute_query(DASH, user_id=user_a, variable_values={"all": True})
    assert res.errors is None
    texts = {a["note"] for a in res.data["dashboard"]["activities"] if a["kind"] == "note"}
    assert texts == {"new", "old", "older"}
    assert res.data["dashboard"]["projects"][0]["olderNoteCount"] == 0


@pytest.mark.django_db
def test_windowed_notes_are_counted(execute_query, user_a, seeded):
    res = execute_query(DASH, user_id=user_a, variable_values={"all": False})
    assert res.errors is None
    texts = {a["note"] for a in res.data["dashboard"]["activities"] if a["kind"] == "note"}
    assert texts == {"new"}
    assert res.data["dashboard"]["projects"][0]["olderNoteCount"] == 2


@pytest.mark.django_db
def test_delta_keeps_the_count(execute_query, user_a, seeded):
    since = (timezone.now() - dt.timedelta(hours=1)).isoformat()
    res = execute_query(DELTA, user_id=user_a, variable_values={"since": since})
    assert res.errors is None
    assert res.data["dashboardDelta"]["projects"][0]["olderNoteCount"] == 2


@pytest.mark.django_db
def test_older_notes_come_from_the_feed(execute_query, user_a, seeded):
    until = (timezone.now() - dt.timedelta(days=60)).isoformat()
    res = execute_query(
        FEED, user_id=user_a, variable_values={"pid": str(seeded.id), "until": until}
    )
    assert res.errors is None
    assert [a["note"] for a in res.data["activity"]] == ["old", "older"]

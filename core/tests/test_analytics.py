"""Tests for the `analytics` query and supporting aggregations."""

import datetime as dt

import pytest
from django.utils import timezone

from core.models import Activity, ActivityKind, Project, Task

ANALYTICS_QUERY = """
    query($range: AnalyticsRange) {
        analytics(range: $range) {
            range
            rangeStart
            rangeEnd
            cadence {
                activeDaysInRange
                totalActivityEvents
            }
            activitySeries { day updates completedTasks totalEvents }
            weekdayHeatmap { weekday count }
            topProjects { projectId name status interactions deltaVsPrev }
            statusCounts { status count }
            categoryBreakdown {
                categoryId name color projectCount interactions
            }
            backlog {
                overdueTasks dueSoonTasks openTasks quickWins almostThere
            }
            sleepingProjects { projectId name daysIdle bucket }
            staleIdeas { ideaId title daysOld }
            ideaFunnel { ideasCreated ideasPromoted promotionRate }
            effort {
                effortHoursTotal
                tasksWithEffortPct
                effortHoursByProject { projectId name hours }
            }
            loop {
                messagesSent
                messagesDeltaVsPrev
                conversations
                actionsTaken
                activeDays
                deepMessages
                connectorInteractions
                daily { day messages deepMessages }
                topTools { tool count }
            }
        }
    }
"""

PROMOTE_IDEA = """
    mutation($id: ID!) { promoteIdea(id: $id) { id name status } }
"""


def _shift_created(obj, when: dt.datetime):
    """Bypass auto_now_add to backdate `created` for testing."""
    type(obj).objects.filter(pk=obj.pk).update(created=when)


def _shift_last_activity(project: Project, when: dt.datetime):
    Project.objects.filter(pk=project.pk).update(last_activity=when)


def _shift_activity_created(activity: Activity, when: dt.datetime):
    Activity.objects.filter(pk=activity.pk).update(created=when)


# ---------- Auth & isolation


@pytest.mark.django_db
def test_analytics_requires_auth(execute_query):
    result = execute_query(ANALYTICS_QUERY, user_id=None)
    assert result.errors is not None
    assert "Not authenticated" in result.errors[0].message


@pytest.mark.django_db
def test_analytics_isolated_per_user(
    execute_query, user_a, user_b, project_factory, task_factory
):
    pa = project_factory(user_a, name="A")
    pb = project_factory(user_b, name="B")
    Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=pa.id, note="a-note"
    )
    Activity.objects.create(
        user_id=user_b, kind=ActivityKind.NOTE, project_id=pb.id, note="b-note"
    )
    task_factory(user_a, project=pa, title="a-task", done=True,
                 completed_at=timezone.now())
    task_factory(user_b, project=pb, title="b-task", done=True,
                 completed_at=timezone.now())

    res_a = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    assert res_a.errors is None
    names_a = [r["name"] for r in res_a.data["analytics"]["topProjects"]]
    assert names_a == ["A"]

    res_b = execute_query(
        ANALYTICS_QUERY, user_id=user_b,
        variable_values={"range": "LAST_30_DAYS"},
    )
    names_b = [r["name"] for r in res_b.data["analytics"]["topProjects"]]
    assert names_b == ["B"]


# ---------- Activity series


@pytest.mark.django_db
def test_activity_series_fills_empty_days(
    execute_query, user_a, project_factory
):
    p = project_factory(user_a)
    Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=p.id, note="hello"
    )
    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    assert res.errors is None
    series = res.data["analytics"]["activitySeries"]
    # 30-day window inclusive of today: 31 points (start..end).
    assert 30 <= len(series) <= 31
    # `updates` field in ActivityPoint counts notes (post-unify semantics).
    assert sum(p["updates"] for p in series) == 1


@pytest.mark.django_db
def test_activity_series_all_time_returns_null_start(
    execute_query, user_a, project_factory
):
    project_factory(user_a)
    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "ALL_TIME"},
    )
    assert res.errors is None
    assert res.data["analytics"]["rangeStart"] is None


# ---------- Weekday heatmap


@pytest.mark.django_db
def test_weekday_heatmap_has_seven_buckets(
    execute_query, user_a, project_factory
):
    project_factory(user_a)
    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    heat = res.data["analytics"]["weekdayHeatmap"]
    assert [b["weekday"] for b in heat] == [1, 2, 3, 4, 5, 6, 7]


# ---------- Top projects


@pytest.mark.django_db
def test_top_projects_orders_and_truncates(
    execute_query, user_a, project_factory, task_factory
):
    projects = [project_factory(user_a, name=f"P{i}") for i in range(7)]
    for i, p in enumerate(projects):
        for _ in range(i + 1):  # P0=1, P1=2, ..., P6=7
            Activity.objects.create(
                user_id=user_a, kind=ActivityKind.NOTE,
                project_id=p.id, note="x",
            )

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    top = res.data["analytics"]["topProjects"]
    assert len(top) == 5
    assert [r["name"] for r in top] == ["P6", "P5", "P4", "P3", "P2"]
    assert top[0]["interactions"] == 7


@pytest.mark.django_db
def test_top_projects_delta_vs_previous_window(
    execute_query, user_a, project_factory
):
    p = project_factory(user_a, name="P")
    now = timezone.now()
    # 2 notes within last 7 days (current window)
    a1 = Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=p.id, note="now1"
    )
    a2 = Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=p.id, note="now2"
    )
    _shift_activity_created(a1, now - dt.timedelta(days=1))
    _shift_activity_created(a2, now - dt.timedelta(days=2))
    # 1 note in previous 7-day window (8-14d ago)
    a3 = Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=p.id, note="prev"
    )
    _shift_activity_created(a3, now - dt.timedelta(days=10))

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_7_DAYS"},
    )
    top = res.data["analytics"]["topProjects"]
    assert len(top) == 1
    assert top[0]["interactions"] == 2
    assert top[0]["deltaVsPrev"] == 1  # 2 - 1


# ---------- Cadence


@pytest.mark.django_db
def test_cadence_active_days_and_events(
    execute_query, user_a, project_factory
):
    p = project_factory(user_a)
    today = timezone.now()
    # activity on 3 distinct days within the window
    for offset in (0, 1, 2):
        a = Activity.objects.create(
            user_id=user_a, kind=ActivityKind.NOTE,
            project_id=p.id, note=f"d{offset}",
        )
        _shift_activity_created(a, today - dt.timedelta(days=offset))
    # an older isolated activity, still inside the 30-day window
    a_old = Activity.objects.create(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=p.id, note="old"
    )
    _shift_activity_created(a_old, today - dt.timedelta(days=10))

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    cad = res.data["analytics"]["cadence"]
    assert cad["activeDaysInRange"] == 4
    assert cad["totalActivityEvents"] >= 4


# ---------- Status & category breakdown


@pytest.mark.django_db
def test_status_counts_aggregate(
    execute_query, user_a, project_factory
):
    project_factory(user_a, status="active")
    project_factory(user_a, status="active")
    project_factory(user_a, status="idea")
    project_factory(user_a, status="launched")

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "ALL_TIME"},
    )
    counts = {s["status"]: s["count"] for s in res.data["analytics"]["statusCounts"]}
    assert counts == {"active": 2, "idea": 1, "launched": 1}


@pytest.mark.django_db
def test_category_breakdown_counts(
    execute_query, user_a, project_factory, category_factory
):
    cat = category_factory(user_a, name="Work", color="blue")
    project_factory(user_a, category=cat)
    project_factory(user_a, category=cat)
    project_factory(user_a, category=None)

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "ALL_TIME"},
    )
    rows = res.data["analytics"]["categoryBreakdown"]
    by_id = {r["categoryId"]: r for r in rows}
    assert by_id[str(cat.id)]["projectCount"] == 2
    assert by_id[None]["projectCount"] == 1


# ---------- Backlog


@pytest.mark.django_db
def test_backlog_overdue_due_soon_quickwins(
    execute_query, user_a, project_factory, task_factory
):
    now = timezone.now()
    p_qw = project_factory(user_a, name="QW", status="active")
    task_factory(user_a, project=p_qw, title="qw1", done=False)
    task_factory(user_a, project=p_qw, title="qw2", done=False)  # 2 open → quick win

    p_close = project_factory(user_a, name="Close", status="active")
    for _ in range(8):
        task_factory(user_a, project=p_close, title="d", done=True,
                     completed_at=now)
    task_factory(user_a, project=p_close, title="left", done=False)
    task_factory(user_a, project=p_close, title="left2", done=False)
    # 8/10 = 80% → almost_there

    # An overdue task on QW
    task_factory(
        user_a, project=p_qw, title="overdue", done=False,
        due_date=now - dt.timedelta(days=2),
    )
    # A due-soon task
    task_factory(
        user_a, project=p_qw, title="soon", done=False,
        due_date=now + dt.timedelta(days=2),
    )

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    b = res.data["analytics"]["backlog"]
    assert b["overdueTasks"] == 1
    assert b["dueSoonTasks"] == 1
    assert b["almostThere"] == 1
    # QW has 4 open tasks (qw1, qw2, overdue, soon) so it's no longer ≤2.
    assert b["quickWins"] == 0


@pytest.mark.django_db
def test_quick_win_threshold_two_open_tasks(
    execute_query, user_a, project_factory, task_factory
):
    p = project_factory(user_a, status="active")
    task_factory(user_a, project=p, title="o1", done=False)
    task_factory(user_a, project=p, title="o2", done=False)
    task_factory(user_a, project=p, title="d", done=True,
                 completed_at=timezone.now())

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    assert res.data["analytics"]["backlog"]["quickWins"] == 1


# ---------- Sleeping & stale


@pytest.mark.django_db
def test_sleeping_buckets(execute_query, user_a, project_factory):
    now = timezone.now()
    p1 = project_factory(user_a, name="P1", status="active")
    _shift_last_activity(p1, now - dt.timedelta(days=10))  # 7-14
    p2 = project_factory(user_a, name="P2", status="active")
    _shift_last_activity(p2, now - dt.timedelta(days=20))  # 15-30
    p3 = project_factory(user_a, name="P3", status="idea")
    _shift_last_activity(p3, now - dt.timedelta(days=60))  # 30+
    p4 = project_factory(user_a, name="P4", status="active")
    _shift_last_activity(p4, now - dt.timedelta(days=2))  # NOT sleeping
    p5 = project_factory(user_a, name="P5", status="archived")
    _shift_last_activity(p5, now - dt.timedelta(days=60))  # excluded by status

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_90_DAYS"},
    )
    rows = res.data["analytics"]["sleepingProjects"]
    by_name = {r["name"]: r for r in rows}
    assert set(by_name.keys()) == {"P1", "P2", "P3"}
    assert by_name["P1"]["bucket"] == "7-14"
    assert by_name["P2"]["bucket"] == "15-30"
    assert by_name["P3"]["bucket"] == "30+"


@pytest.mark.django_db
def test_stale_ideas(execute_query, user_a, idea_factory):
    now = timezone.now()
    fresh = idea_factory(user_a, title="fresh")
    old = idea_factory(user_a, title="old")
    _shift_created(old, now - dt.timedelta(days=45))

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "ALL_TIME"},
    )
    titles = [r["title"] for r in res.data["analytics"]["staleIdeas"]]
    assert titles == ["old"]


# ---------- Idea funnel


@pytest.mark.django_db
def test_idea_funnel_uses_promote_idea_mutation(
    execute_query, user_a, idea_factory
):
    idea = idea_factory(user_a, title="To promote")
    idea_factory(user_a, title="Sticking around")

    promote = execute_query(
        PROMOTE_IDEA, user_id=user_a,
        variable_values={"id": str(idea.id)},
    )
    assert promote.errors is None

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    funnel = res.data["analytics"]["ideaFunnel"]
    assert funnel["ideasPromoted"] == 1
    assert funnel["ideasCreated"] == 1
    # rate = 1 / (1 + 1)
    assert abs(funnel["promotionRate"] - 0.5) < 0.0001


# ---------- Effort


@pytest.mark.django_db
def test_effort_stats_sum_and_coverage(
    execute_query, user_a, project_factory, task_factory
):
    p = project_factory(user_a, name="P")
    now = timezone.now()
    task_factory(user_a, project=p, title="t1", done=True,
                 completed_at=now, effort_hours=2.5)
    task_factory(user_a, project=p, title="t2", done=True,
                 completed_at=now, effort_hours=1.0)
    task_factory(user_a, project=p, title="t3", done=True,
                 completed_at=now, effort_hours=None)

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    eff = res.data["analytics"]["effort"]
    assert eff["effortHoursTotal"] == 3.5
    # 2 of 3 done tasks have effort recorded.
    assert abs(eff["tasksWithEffortPct"] - 2 / 3) < 0.001
    by_proj = eff["effortHoursByProject"]
    assert len(by_proj) == 1
    assert by_proj[0]["hours"] == 3.5


# ---------- Loop (AI assistant) usage


@pytest.mark.django_db
def test_loop_stats_counts_messages_actions_and_surfaces(
    execute_query, user_a
):
    from core.assistant.models import Conversation, Message, UsageDay
    from core.models import InteractionDay, InteractionSource

    today = timezone.now().date()
    # In-app messages over two days (one with a deep/Sonnet message).
    UsageDay.objects.create(
        user_id=user_a, date=today, messages_sent=3, deep_messages=1
    )
    UsageDay.objects.create(
        user_id=user_a,
        date=today - dt.timedelta(days=1),
        messages_sent=2,
        deep_messages=0,
    )
    # A conversation with one assistant turn carrying two tool_use blocks.
    conv = Conversation.objects.create(user_id=user_a, title="c")
    Message.objects.create(
        conversation=conv,
        role="assistant",
        content=[
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "1", "name": "create_task", "input": {}},
            {"type": "tool_use", "id": "2", "name": "create_task", "input": {}},
        ],
    )
    # Connector (Claude.ai) interactions live in InteractionDay.
    InteractionDay.objects.create(
        user_id=user_a, date=today, source=InteractionSource.CONNECTOR, count=4
    )
    # A non-connector source must NOT be counted as Loop connector usage.
    InteractionDay.objects.create(
        user_id=user_a, date=today, source=InteractionSource.WEB, count=9
    )

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    assert res.errors is None
    loop = res.data["analytics"]["loop"]
    assert loop["messagesSent"] == 5
    assert loop["deepMessages"] == 1
    assert loop["activeDays"] == 2
    assert loop["conversations"] == 1
    assert loop["actionsTaken"] == 2
    assert loop["connectorInteractions"] == 4
    assert loop["topTools"] == [{"tool": "create_task", "count": 2}]
    # Daily series is gap-filled across the window and sums to messagesSent.
    assert sum(p["messages"] for p in loop["daily"]) == 5


@pytest.mark.django_db
def test_loop_stats_isolated_per_user(execute_query, user_a, user_b):
    from core.assistant.models import UsageDay

    today = timezone.now().date()
    UsageDay.objects.create(user_id=user_a, date=today, messages_sent=7)
    UsageDay.objects.create(user_id=user_b, date=today, messages_sent=99)

    res = execute_query(
        ANALYTICS_QUERY, user_id=user_a,
        variable_values={"range": "LAST_30_DAYS"},
    )
    assert res.data["analytics"]["loop"]["messagesSent"] == 7

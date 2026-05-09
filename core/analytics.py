"""Analytics aggregations for the dashboard's "Analíticas" view.

Pure-Python helpers + Django ORM aggregations. Schema layer (schema.py)
imports the dataclasses defined here and exposes them through Strawberry
types. Keeping computation here keeps schema.py thin.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Optional

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import ExtractIsoWeekDay, TruncDate
from django.utils import timezone

from .models import Idea, Project, Task, Update

# Thresholds — kept in parity with the frontend (useProductivityStats.ts).
QUICK_WIN_OPEN_TASKS_MAX = 2
ALMOST_THERE_PCT = 0.8
SLEEPING_THRESHOLD_DAYS = 7
SLEEPING_BUCKET_MID = 14
SLEEPING_BUCKET_LATE = 30
STALE_IDEA_DAYS = 30
DUE_SOON_DAYS = 7
TOP_N_PROJECTS = 5
TOP_N_EFFORT_PROJECTS = 5
SLEEPING_LIMIT = 20
STALE_LIMIT = 20


class AnalyticsRange(str, enum.Enum):
    LAST_7_DAYS = "LAST_7_DAYS"
    LAST_30_DAYS = "LAST_30_DAYS"
    LAST_90_DAYS = "LAST_90_DAYS"
    LAST_365_DAYS = "LAST_365_DAYS"
    ALL_TIME = "ALL_TIME"


_RANGE_DAYS = {
    AnalyticsRange.LAST_7_DAYS: 7,
    AnalyticsRange.LAST_30_DAYS: 30,
    AnalyticsRange.LAST_90_DAYS: 90,
    AnalyticsRange.LAST_365_DAYS: 365,
}


def resolve_window(
    rng: AnalyticsRange, now: Optional[dt.datetime] = None
) -> tuple[Optional[dt.datetime], dt.datetime]:
    """Return (start, end) for the range. start is None for ALL_TIME."""
    end = now or timezone.now()
    if rng == AnalyticsRange.ALL_TIME:
        return None, end
    days = _RANGE_DAYS[rng]
    return end - dt.timedelta(days=days), end


def previous_window(
    start: Optional[dt.datetime], end: dt.datetime
) -> tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    """The equivalent-length window immediately before [start, end)."""
    if start is None:
        return None, None
    span = end - start
    return start - span, start


# ---------- Sub-section dataclasses (mirrored as Strawberry types in schema.py)


@dataclass
class CadenceStats:
    current_streak: int
    longest_streak: int
    active_days_in_range: int
    total_activity_events: int


@dataclass
class ActivityPoint:
    day: dt.date
    updates: int
    completed_tasks: int
    total_events: int


@dataclass
class WeekdayBucket:
    weekday: int  # ISO 1=Mon .. 7=Sun
    count: int


@dataclass
class ProjectInteractionRow:
    project_id: uuid.UUID
    name: str
    status: str
    interactions: int
    delta_vs_prev: int


@dataclass
class StatusCount:
    status: str
    count: int


@dataclass
class CategoryRow:
    category_id: Optional[uuid.UUID]
    name: str
    color: str
    project_count: int
    interactions: int


@dataclass
class BacklogHealth:
    overdue_tasks: int
    due_soon_tasks: int
    open_tasks: int
    quick_wins: int
    almost_there: int


@dataclass
class SleepingProjectRow:
    project_id: uuid.UUID
    name: str
    days_idle: int
    bucket: str  # "7-14" | "15-30" | "30+"


@dataclass
class StaleIdeaRow:
    idea_id: uuid.UUID
    title: str
    days_old: int


@dataclass
class IdeaFunnel:
    ideas_created: int
    ideas_promoted: int
    promotion_rate: float


@dataclass
class EffortProjectRow:
    project_id: uuid.UUID
    name: str
    hours: float


@dataclass
class EffortStats:
    effort_hours_total: float
    tasks_with_effort_pct: float
    effort_hours_by_project: list[EffortProjectRow] = field(default_factory=list)


@dataclass
class AnalyticsResult:
    range: AnalyticsRange
    range_start: Optional[dt.datetime]
    range_end: dt.datetime
    cadence: CadenceStats
    activity_series: list[ActivityPoint]
    weekday_heatmap: list[WeekdayBucket]
    top_projects: list[ProjectInteractionRow]
    status_counts: list[StatusCount]
    category_breakdown: list[CategoryRow]
    backlog: BacklogHealth
    sleeping_projects: list[SleepingProjectRow]
    stale_ideas: list[StaleIdeaRow]
    idea_funnel: IdeaFunnel
    effort: EffortStats


# ---------- Pure helpers


def _activity_day_set(days_iter: Iterable[dt.date]) -> set[dt.date]:
    return {d for d in days_iter if d is not None}


def compute_streak(days: set[dt.date], today: dt.date) -> int:
    """Consecutive days ending at today (or yesterday) with activity."""
    if not days:
        return 0
    cursor = today if today in days else today - dt.timedelta(days=1)
    if cursor not in days:
        return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def compute_longest_streak(days: set[dt.date]) -> int:
    if not days:
        return 0
    sorted_days = sorted(days)
    best = 1
    cur = 1
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i - 1]).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


# ---------- Resolver


def compute_analytics(user_id: uuid.UUID, rng: AnalyticsRange) -> AnalyticsResult:
    now = timezone.now()
    start, end = resolve_window(rng, now=now)
    prev_start, prev_end = previous_window(start, end)

    # Base querysets (user-scoped). Range filters applied per section.
    updates_qs = Update.objects.filter(user_id=user_id)
    tasks_qs = Task.objects.filter(user_id=user_id)
    tasks_done_qs = tasks_qs.filter(done=True, completed_at__isnull=False)
    projects_qs = Project.objects.filter(user_id=user_id)
    ideas_qs = Idea.objects.filter(user_id=user_id)

    if start is not None:
        ranged_updates = updates_qs.filter(date__gte=start, date__lt=end)
        ranged_tasks_done = tasks_done_qs.filter(
            completed_at__gte=start, completed_at__lt=end
        )
    else:
        ranged_updates = updates_qs
        ranged_tasks_done = tasks_done_qs

    cadence = _cadence(updates_qs, tasks_done_qs, ranged_updates, ranged_tasks_done, now)
    activity_series = _activity_series(ranged_updates, ranged_tasks_done, start, end)
    weekday_heatmap = _weekday_heatmap(ranged_updates, ranged_tasks_done)
    top_projects = _top_projects(
        ranged_updates,
        ranged_tasks_done,
        prev_start,
        prev_end,
        updates_qs,
        tasks_done_qs,
        projects_qs,
    )
    status_counts = _status_counts(projects_qs)
    category_breakdown = _category_breakdown(projects_qs, ranged_updates, ranged_tasks_done)
    backlog = _backlog(tasks_qs, projects_qs, now)
    sleeping_projects = _sleeping_projects(projects_qs, now)
    stale_ideas = _stale_ideas(ideas_qs, now)
    idea_funnel = _idea_funnel(ideas_qs, projects_qs, start, end)
    effort = _effort(tasks_qs, ranged_tasks_done, projects_qs, start, end)

    return AnalyticsResult(
        range=rng,
        range_start=start,
        range_end=end,
        cadence=cadence,
        activity_series=activity_series,
        weekday_heatmap=weekday_heatmap,
        top_projects=top_projects,
        status_counts=status_counts,
        category_breakdown=category_breakdown,
        backlog=backlog,
        sleeping_projects=sleeping_projects,
        stale_ideas=stale_ideas,
        idea_funnel=idea_funnel,
        effort=effort,
    )


# ---------- Per-section helpers


def _cadence(
    updates_all,
    tasks_done_all,
    ranged_updates,
    ranged_tasks_done,
    now: dt.datetime,
) -> CadenceStats:
    # Streaks use the full history; "active days in range" and total events
    # use the windowed querysets so the user can see how the chosen range
    # compares.
    all_days_updates = updates_all.annotate(d=TruncDate("date")).values_list(
        "d", flat=True
    )
    all_days_tasks = tasks_done_all.annotate(d=TruncDate("completed_at")).values_list(
        "d", flat=True
    )
    all_days = _activity_day_set(list(all_days_updates) + list(all_days_tasks))

    today = now.date()
    current = compute_streak(all_days, today)
    longest = compute_longest_streak(all_days)

    range_days_updates = ranged_updates.annotate(d=TruncDate("date")).values_list(
        "d", flat=True
    )
    range_days_tasks = ranged_tasks_done.annotate(
        d=TruncDate("completed_at")
    ).values_list("d", flat=True)
    range_days = _activity_day_set(
        list(range_days_updates) + list(range_days_tasks)
    )

    total = ranged_updates.count() + ranged_tasks_done.count()

    return CadenceStats(
        current_streak=current,
        longest_streak=longest,
        active_days_in_range=len(range_days),
        total_activity_events=total,
    )


def _activity_series(
    ranged_updates,
    ranged_tasks_done,
    start: Optional[dt.datetime],
    end: dt.datetime,
) -> list[ActivityPoint]:
    update_counts = {
        row["d"]: row["c"]
        for row in ranged_updates.annotate(d=TruncDate("date"))
        .values("d")
        .annotate(c=Count("id"))
    }
    task_counts = {
        row["d"]: row["c"]
        for row in ranged_tasks_done.annotate(d=TruncDate("completed_at"))
        .values("d")
        .annotate(c=Count("id"))
    }

    if start is None:
        # ALL_TIME: span from earliest event to today, capped at 365 days
        # to keep payload sane.
        all_days = sorted(set(update_counts.keys()) | set(task_counts.keys()))
        if not all_days:
            return []
        first = all_days[0]
        last = end.date()
        span = (last - first).days
        if span > 365:
            first = last - dt.timedelta(days=365)
        cursor = first
    else:
        cursor = start.date()

    points: list[ActivityPoint] = []
    end_date = end.date()
    while cursor <= end_date:
        u = update_counts.get(cursor, 0)
        t = task_counts.get(cursor, 0)
        points.append(
            ActivityPoint(day=cursor, updates=u, completed_tasks=t, total_events=u + t)
        )
        cursor += dt.timedelta(days=1)
    return points


def _weekday_heatmap(ranged_updates, ranged_tasks_done) -> list[WeekdayBucket]:
    buckets: dict[int, int] = {i: 0 for i in range(1, 8)}
    for row in (
        ranged_updates.annotate(wd=ExtractIsoWeekDay("date"))
        .values("wd")
        .annotate(c=Count("id"))
    ):
        if row["wd"] is not None:
            buckets[int(row["wd"])] += row["c"]
    for row in (
        ranged_tasks_done.annotate(wd=ExtractIsoWeekDay("completed_at"))
        .values("wd")
        .annotate(c=Count("id"))
    ):
        if row["wd"] is not None:
            buckets[int(row["wd"])] += row["c"]
    return [WeekdayBucket(weekday=k, count=v) for k, v in sorted(buckets.items())]


def _top_projects(
    ranged_updates,
    ranged_tasks_done,
    prev_start: Optional[dt.datetime],
    prev_end: Optional[dt.datetime],
    updates_qs,
    tasks_done_qs,
    projects_qs,
) -> list[ProjectInteractionRow]:
    counts: dict[uuid.UUID, int] = {}
    for row in (
        ranged_updates.values("project_id").annotate(c=Count("id"))
    ):
        if row["project_id"]:
            counts[row["project_id"]] = counts.get(row["project_id"], 0) + row["c"]
    for row in (
        ranged_tasks_done.exclude(project_id__isnull=True)
        .values("project_id")
        .annotate(c=Count("id"))
    ):
        counts[row["project_id"]] = counts.get(row["project_id"], 0) + row["c"]

    if not counts:
        return []

    top_ids = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[
        :TOP_N_PROJECTS
    ]
    project_ids = [pid for pid, _ in top_ids]

    # Previous-window counts for delta. Only fetch for the top N to keep
    # things cheap.
    prev_counts: dict[uuid.UUID, int] = {}
    if prev_start is not None and prev_end is not None and project_ids:
        prev_updates = updates_qs.filter(
            project_id__in=project_ids,
            date__gte=prev_start,
            date__lt=prev_end,
        )
        prev_tasks = tasks_done_qs.filter(
            project_id__in=project_ids,
            completed_at__gte=prev_start,
            completed_at__lt=prev_end,
        )
        for row in prev_updates.values("project_id").annotate(c=Count("id")):
            prev_counts[row["project_id"]] = (
                prev_counts.get(row["project_id"], 0) + row["c"]
            )
        for row in prev_tasks.values("project_id").annotate(c=Count("id")):
            prev_counts[row["project_id"]] = (
                prev_counts.get(row["project_id"], 0) + row["c"]
            )

    project_map = {p.id: p for p in projects_qs.filter(id__in=project_ids)}

    rows: list[ProjectInteractionRow] = []
    for pid, c in top_ids:
        proj = project_map.get(pid)
        if not proj:
            continue
        rows.append(
            ProjectInteractionRow(
                project_id=pid,
                name=proj.name,
                status=proj.status,
                interactions=c,
                delta_vs_prev=c - prev_counts.get(pid, 0),
            )
        )
    return rows


def _status_counts(projects_qs) -> list[StatusCount]:
    rows = projects_qs.values("status").annotate(c=Count("id"))
    return [StatusCount(status=r["status"], count=r["c"]) for r in rows]


def _category_breakdown(
    projects_qs, ranged_updates, ranged_tasks_done
) -> list[CategoryRow]:
    project_rows = projects_qs.values(
        "category_id", "category__name", "category__color"
    ).annotate(c=Count("id"))

    interactions: dict[Optional[uuid.UUID], int] = {}
    for row in ranged_updates.values("project__category_id").annotate(c=Count("id")):
        interactions[row["project__category_id"]] = (
            interactions.get(row["project__category_id"], 0) + row["c"]
        )
    for row in ranged_tasks_done.values("project__category_id").annotate(
        c=Count("id")
    ):
        interactions[row["project__category_id"]] = (
            interactions.get(row["project__category_id"], 0) + row["c"]
        )

    out: list[CategoryRow] = []
    for r in project_rows:
        cat_id = r["category_id"]
        out.append(
            CategoryRow(
                category_id=cat_id,
                name=r["category__name"] or "Sin categoría",
                color=r["category__color"] or "zinc",
                project_count=r["c"],
                interactions=interactions.get(cat_id, 0),
            )
        )
    out.sort(key=lambda x: (-x.interactions, -x.project_count))
    return out


def _backlog(tasks_qs, projects_qs, now: dt.datetime) -> BacklogHealth:
    open_tasks_qs = tasks_qs.filter(done=False)
    overdue = open_tasks_qs.filter(due_date__lt=now, due_date__isnull=False).count()
    due_soon = open_tasks_qs.filter(
        due_date__gte=now, due_date__lt=now + dt.timedelta(days=DUE_SOON_DAYS)
    ).count()
    open_count = open_tasks_qs.count()

    # Per-project task aggregates for quick_wins / almost_there.
    project_aggs = (
        projects_qs.filter(status__in=["active", "idea"])
        .annotate(
            total=Count("tasks"),
            done_count=Count("tasks", filter=Q(tasks__done=True)),
            open_count=Count("tasks", filter=Q(tasks__done=False)),
        )
        .values("id", "total", "done_count", "open_count")
    )
    quick_wins = 0
    almost_there = 0
    for p in project_aggs:
        if p["total"] == 0 or p["open_count"] == 0:
            continue
        done_pct = p["done_count"] / p["total"] if p["total"] else 0
        if done_pct >= ALMOST_THERE_PCT:
            almost_there += 1
        elif p["open_count"] <= QUICK_WIN_OPEN_TASKS_MAX:
            quick_wins += 1

    return BacklogHealth(
        overdue_tasks=overdue,
        due_soon_tasks=due_soon,
        open_tasks=open_count,
        quick_wins=quick_wins,
        almost_there=almost_there,
    )


def _sleeping_projects(projects_qs, now: dt.datetime) -> list[SleepingProjectRow]:
    cutoff = now - dt.timedelta(days=SLEEPING_THRESHOLD_DAYS)
    rows = (
        projects_qs.filter(status__in=["active", "idea"], last_activity__lt=cutoff)
        .order_by("last_activity")
        .values("id", "name", "last_activity")[:SLEEPING_LIMIT]
    )
    out: list[SleepingProjectRow] = []
    for r in rows:
        days = (now - r["last_activity"]).days
        if days <= SLEEPING_BUCKET_MID:
            bucket = "7-14"
        elif days <= SLEEPING_BUCKET_LATE:
            bucket = "15-30"
        else:
            bucket = "30+"
        out.append(
            SleepingProjectRow(
                project_id=r["id"], name=r["name"], days_idle=days, bucket=bucket
            )
        )
    return out


def _stale_ideas(ideas_qs, now: dt.datetime) -> list[StaleIdeaRow]:
    cutoff = now - dt.timedelta(days=STALE_IDEA_DAYS)
    rows = (
        ideas_qs.filter(created__lt=cutoff)
        .order_by("created")
        .values("id", "title", "created")[:STALE_LIMIT]
    )
    return [
        StaleIdeaRow(
            idea_id=r["id"],
            title=r["title"],
            days_old=(now - r["created"]).days,
        )
        for r in rows
    ]


def _idea_funnel(
    ideas_qs, projects_qs, start: Optional[dt.datetime], end: dt.datetime
) -> IdeaFunnel:
    if start is None:
        ideas_created = ideas_qs.count()
        ideas_promoted = projects_qs.filter(
            promoted_from_idea_at__isnull=False
        ).count()
    else:
        ideas_created = ideas_qs.filter(created__gte=start, created__lt=end).count()
        ideas_promoted = projects_qs.filter(
            promoted_from_idea_at__gte=start, promoted_from_idea_at__lt=end
        ).count()
    denom = ideas_created + ideas_promoted
    rate = ideas_promoted / denom if denom else 0.0
    return IdeaFunnel(
        ideas_created=ideas_created,
        ideas_promoted=ideas_promoted,
        promotion_rate=rate,
    )


def _effort(
    tasks_qs,
    ranged_tasks_done,
    projects_qs,
    start: Optional[dt.datetime],
    end: dt.datetime,
) -> EffortStats:
    total = ranged_tasks_done.aggregate(s=Sum("effort_hours"))["s"] or 0.0

    done_in_range = ranged_tasks_done.count()
    done_with_effort = ranged_tasks_done.exclude(effort_hours__isnull=True).count()
    coverage = (done_with_effort / done_in_range) if done_in_range else 0.0

    by_project_rows = (
        ranged_tasks_done.exclude(effort_hours__isnull=True)
        .exclude(project_id__isnull=True)
        .values("project_id")
        .annotate(h=Sum("effort_hours"))
        .order_by("-h")[:TOP_N_EFFORT_PROJECTS]
    )
    project_ids = [r["project_id"] for r in by_project_rows]
    project_map = {p.id: p for p in projects_qs.filter(id__in=project_ids)}
    by_project = [
        EffortProjectRow(
            project_id=r["project_id"],
            name=project_map[r["project_id"]].name
            if r["project_id"] in project_map
            else "(deleted)",
            hours=round(float(r["h"] or 0.0), 2),
        )
        for r in by_project_rows
    ]

    return EffortStats(
        effort_hours_total=round(float(total), 2),
        tasks_with_effort_pct=round(coverage, 4),
        effort_hours_by_project=by_project,
    )

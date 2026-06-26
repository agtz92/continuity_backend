"""Analytics aggregations for the dashboard's Analytics view.

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

from .models import Activity, ActivityKind, Idea, Project, Task

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
TOP_N_LOOP_TOOLS = 8
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
class LoopToolRow:
    tool: str
    count: int


@dataclass
class LoopDailyPoint:
    day: dt.date
    messages: int
    deep_messages: int


@dataclass
class LoopStats:
    """Usage of the AI assistant ("Loop") for one user over the range.

    Counts only — never message content. Two surfaces are tracked:
    in-app chat (``UsageDay`` / ``Message``) and the Claude.ai connector
    (``InteractionDay`` source=connector). ``actions_taken`` is the number
    of tool_use blocks Loop emitted in-app (what it *did*, not just chatted).
    """

    messages_sent: int
    messages_delta_vs_prev: int
    conversations: int
    actions_taken: int
    active_days: int
    deep_messages: int
    connector_interactions: int
    daily: list[LoopDailyPoint] = field(default_factory=list)
    top_tools: list[LoopToolRow] = field(default_factory=list)


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
    sleeping_projects: list[SleepingProjectRow]  # deprecated: derived 7d idle
    stalled_projects: list[SleepingProjectRow]  # persisted status=stalled (D7)
    stale_ideas: list[StaleIdeaRow]
    idea_funnel: IdeaFunnel
    effort: EffortStats
    loop: LoopStats


# ---------- Pure helpers


def _activity_day_set(days_iter: Iterable[dt.date]) -> set[dt.date]:
    return {d for d in days_iter if d is not None}


# ---------- Resolver


def compute_analytics(user_id: uuid.UUID, rng: AnalyticsRange) -> AnalyticsResult:
    now = timezone.now()
    start, end = resolve_window(rng, now=now)
    prev_start, prev_end = previous_window(start, end)

    # Base querysets (user-scoped). Range filters applied per section.
    activity_qs = Activity.objects.filter(user_id=user_id)
    tasks_qs = Task.objects.filter(user_id=user_id)
    tasks_done_qs = tasks_qs.filter(done=True, completed_at__isnull=False)
    projects_qs = Project.objects.filter(user_id=user_id)
    ideas_qs = Idea.objects.filter(user_id=user_id)

    if start is not None:
        ranged_activity = activity_qs.filter(created__gte=start, created__lt=end)
        ranged_tasks_done = tasks_done_qs.filter(
            completed_at__gte=start, completed_at__lt=end
        )
    else:
        ranged_activity = activity_qs
        ranged_tasks_done = tasks_done_qs

    cadence = _cadence(ranged_activity)
    activity_series = _activity_series(ranged_activity, start, end)
    weekday_heatmap = _weekday_heatmap(ranged_activity)
    top_projects = _top_projects(
        ranged_activity, prev_start, prev_end, activity_qs, projects_qs,
    )
    status_counts = _status_counts(projects_qs)
    category_breakdown = _category_breakdown(projects_qs, ranged_activity)
    backlog = _backlog(tasks_qs, projects_qs, now)
    sleeping_projects = _sleeping_projects(projects_qs, now)
    stalled_projects = _stalled_projects(projects_qs, now)
    stale_ideas = _stale_ideas(ideas_qs, now)
    idea_funnel = _idea_funnel(ideas_qs, projects_qs, start, end)
    effort = _effort(tasks_qs, ranged_tasks_done, projects_qs, start, end)
    loop = _loop_stats(user_id, start, end, prev_start, prev_end)

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
        stalled_projects=stalled_projects,
        stale_ideas=stale_ideas,
        idea_funnel=idea_funnel,
        effort=effort,
        loop=loop,
    )


# ---------- Per-section helpers


def _cadence(ranged_activity) -> CadenceStats:
    # "Active days in range" and total events use the windowed queryset so
    # the user can see how the chosen range compares.
    range_days = _activity_day_set(
        list(ranged_activity.annotate(d=TruncDate("created")).values_list("d", flat=True))
    )

    return CadenceStats(
        active_days_in_range=len(range_days),
        total_activity_events=ranged_activity.count(),
    )


def _activity_series(
    ranged_activity,
    start: Optional[dt.datetime],
    end: dt.datetime,
) -> list[ActivityPoint]:
    # Per-day counts split by kind so the chart can distinguish notes
    # (writing) from task completions (achievements) while `total_events`
    # captures everything else (creates/deletes/changes).
    rows = (
        ranged_activity.annotate(d=TruncDate("created"))
        .values("d", "kind")
        .annotate(c=Count("id"))
    )
    note_counts: dict[dt.date, int] = {}
    completed_counts: dict[dt.date, int] = {}
    total_counts: dict[dt.date, int] = {}
    for r in rows:
        day = r["d"]
        kind = r["kind"]
        count = r["c"]
        total_counts[day] = total_counts.get(day, 0) + count
        if kind == ActivityKind.NOTE:
            note_counts[day] = note_counts.get(day, 0) + count
        elif kind == ActivityKind.TASK_COMPLETED:
            completed_counts[day] = completed_counts.get(day, 0) + count

    if start is None:
        # ALL_TIME: span from earliest event to today, capped at 365 days
        # to keep payload sane.
        all_days = sorted(total_counts.keys())
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
        points.append(
            ActivityPoint(
                day=cursor,
                updates=note_counts.get(cursor, 0),
                completed_tasks=completed_counts.get(cursor, 0),
                total_events=total_counts.get(cursor, 0),
            )
        )
        cursor += dt.timedelta(days=1)
    return points


def _weekday_heatmap(ranged_activity) -> list[WeekdayBucket]:
    buckets: dict[int, int] = {i: 0 for i in range(1, 8)}
    for row in (
        ranged_activity.annotate(wd=ExtractIsoWeekDay("created"))
        .values("wd")
        .annotate(c=Count("id"))
    ):
        if row["wd"] is not None:
            buckets[int(row["wd"])] += row["c"]
    return [WeekdayBucket(weekday=k, count=v) for k, v in sorted(buckets.items())]


def _top_projects(
    ranged_activity,
    prev_start: Optional[dt.datetime],
    prev_end: Optional[dt.datetime],
    activity_qs,
    projects_qs,
) -> list[ProjectInteractionRow]:
    counts: dict[uuid.UUID, int] = {}
    for row in (
        ranged_activity.exclude(project_id__isnull=True)
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
        prev_rows = activity_qs.filter(
            project_id__in=project_ids,
            created__gte=prev_start,
            created__lt=prev_end,
        )
        for row in prev_rows.values("project_id").annotate(c=Count("id")):
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


def _category_breakdown(projects_qs, ranged_activity) -> list[CategoryRow]:
    project_rows = projects_qs.values(
        "category_id", "category__name", "category__color"
    ).annotate(c=Count("id"))

    # Activity has a denormalized `project_id` (no FK), so we join manually
    # against the project list to map activity counts to categories.
    project_to_category: dict[uuid.UUID, Optional[uuid.UUID]] = {
        p["id"]: p["category_id"]
        for p in projects_qs.values("id", "category_id")
    }
    interactions: dict[Optional[uuid.UUID], int] = {}
    for row in (
        ranged_activity.exclude(project_id__isnull=True)
        .values("project_id")
        .annotate(c=Count("id"))
    ):
        cat = project_to_category.get(row["project_id"])
        interactions[cat] = interactions.get(cat, 0) + row["c"]

    out: list[CategoryRow] = []
    for r in project_rows:
        cat_id = r["category_id"]
        out.append(
            CategoryRow(
                category_id=cat_id,
                name=r["category__name"] or "Uncategorized",
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


def _stalled_projects(projects_qs, now: dt.datetime) -> list[SleepingProjectRow]:
    """Persisted stalled projects (status=stalled), reusing the sleeping row
    shape so clients can migrate field-for-field (D7)."""
    rows = (
        projects_qs.filter(status="stalled")
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


def _loop_daily_series(
    by_day: dict[dt.date, dict],
    start: Optional[dt.datetime],
    end: dt.datetime,
) -> list[LoopDailyPoint]:
    """Gap-filled per-day Loop message series (mirrors `_activity_series`)."""
    if start is None:
        if not by_day:
            return []
        all_days = sorted(by_day.keys())
        first = all_days[0]
        last = end.date()
        if (last - first).days > 365:
            first = last - dt.timedelta(days=365)
        cursor = first
    else:
        cursor = start.date()

    points: list[LoopDailyPoint] = []
    end_date = end.date()
    while cursor <= end_date:
        row = by_day.get(cursor)
        points.append(
            LoopDailyPoint(
                day=cursor,
                messages=int(row["m"] or 0) if row else 0,
                deep_messages=int(row["d"] or 0) if row else 0,
            )
        )
        cursor += dt.timedelta(days=1)
    return points


def _loop_stats(
    user_id: uuid.UUID,
    start: Optional[dt.datetime],
    end: dt.datetime,
    prev_start: Optional[dt.datetime],
    prev_end: Optional[dt.datetime],
) -> LoopStats:
    """Aggregate the user's AI-assistant ("Loop") usage for the range.

    Counts only — privacy by design. Reads three sources, all user-scoped:
    `UsageDay` (in-app messages per day), `Message` (tool_use blocks =
    actions Loop took), and `InteractionDay` source=connector (Claude.ai).
    Imports are local to avoid a cross-app import at module load.
    """
    # Local imports: assistant is a sibling app; keep load order simple.
    from .assistant.models import Conversation, Message, UsageDay
    from .models import InteractionDay, InteractionSource

    # ---- In-app messages (UsageDay, per day) ----
    usage_qs = UsageDay.objects.filter(user_id=user_id)
    if start is not None:
        ranged_usage = usage_qs.filter(date__gte=start.date(), date__lte=end.date())
    else:
        ranged_usage = usage_qs

    agg = ranged_usage.aggregate(m=Sum("messages_sent"), d=Sum("deep_messages"))
    messages_sent = int(agg["m"] or 0)
    deep_messages = int(agg["d"] or 0)
    active_days = ranged_usage.filter(messages_sent__gt=0).count()

    messages_delta = 0
    if prev_start is not None and prev_end is not None:
        prev_m = (
            usage_qs.filter(
                date__gte=prev_start.date(), date__lte=prev_end.date()
            ).aggregate(m=Sum("messages_sent"))["m"]
            or 0
        )
        messages_delta = messages_sent - int(prev_m)

    # ---- Conversations touched in the range ----
    conv_qs = Conversation.objects.filter(user_id=user_id)
    if start is not None:
        conversations = conv_qs.filter(
            updated_at__gte=start, updated_at__lt=end
        ).count()
    else:
        conversations = conv_qs.count()

    # ---- Actions Loop took: tool_use blocks in assistant messages ----
    msg_qs = Message.objects.filter(
        conversation__user_id=user_id, role="assistant"
    )
    if start is not None:
        msg_qs = msg_qs.filter(created__gte=start, created__lt=end)
    tool_counts: dict[str, int] = {}
    actions_taken = 0
    for content in msg_qs.values_list("content", flat=True):
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                actions_taken += 1
                name = block.get("name") or "unknown"
                tool_counts[name] = tool_counts.get(name, 0) + 1
    top_tools = [
        LoopToolRow(tool=name, count=c)
        for name, c in sorted(
            tool_counts.items(), key=lambda kv: kv[1], reverse=True
        )[:TOP_N_LOOP_TOOLS]
    ]

    # ---- Connector interactions (Claude.ai MCP) ----
    conn_qs = InteractionDay.objects.filter(
        user_id=user_id, source=InteractionSource.CONNECTOR
    )
    if start is not None:
        conn_qs = conn_qs.filter(date__gte=start.date(), date__lte=end.date())
    connector_interactions = int(conn_qs.aggregate(s=Sum("count"))["s"] or 0)

    # ---- Daily message series (gap-filled) ----
    by_day = {
        r["date"]: r
        for r in ranged_usage.values("date").annotate(
            m=Sum("messages_sent"), d=Sum("deep_messages")
        )
    }
    daily = _loop_daily_series(by_day, start, end)

    return LoopStats(
        messages_sent=messages_sent,
        messages_delta_vs_prev=messages_delta,
        conversations=conversations,
        actions_taken=actions_taken,
        active_days=active_days,
        deep_messages=deep_messages,
        connector_interactions=connector_interactions,
        daily=daily,
        top_tools=top_tools,
    )

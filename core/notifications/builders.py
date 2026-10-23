"""Render notification messages from the analytics module.

Each builder returns a `BuiltMessage`: the Telegram MarkdownV2 body (the full
read) plus a `PushContent` (title + one or two lines, deep link, action
category) so a phone never receives the whole digest. Locale is resolved from
the user's `NotificationSettings.locale` (defaults to English).

Design rules both versions follow: lead with the number that matters, name the
one thing to do first, cap every list (`_LIST_CAP`, then "…and N more"), and
one emoji per section, not per line.
"""

from __future__ import annotations

import datetime as dt
import uuid
import zoneinfo
from dataclasses import dataclass
from typing import Sequence

from django.db.models import Q
from django.utils import timezone

from core import analytics
from core.analytics import AnalyticsRange
from core.models import Routine, Task
from core.services import routines as routines_service
from core.services.projects import DAILY_VIEW_PROJECT_STATUSES

from . import i18n as i18n_strings
from .models import NotificationSettings
from .providers.base import PushContent
from .providers.telegram import md_escape

DASHBOARD_URL = "https://continuu.it"

# Max rows per Telegram section; the rest collapse into "…and N more".
_LIST_CAP = 5
_WEEKLY_CAP = 3

# Action sets the mobile app registers (src/lib/notifications.ts). Keep in sync.
CATEGORY_TASK_FOCUS = "task_focus"  # Marcar hecha · Pasar a mañana (one task)
CATEGORY_TASKS_BULK = "tasks_bulk"  # Pasar todas a mañana (several tasks)


@dataclass
class BuiltMessage:
    text: str
    push: PushContent


def _esc(text: str) -> str:
    return md_escape(text or "")


def _bullet(line: str) -> str:
    return f"• {line}"


def _plural(s: dict, key: str, count: int, **kw) -> str:
    form = "one" if count == 1 else "other"
    return s[f"{key}.{form}"].format(count=count, **kw)


def _resolve_locale(user_id: uuid.UUID) -> str:
    s = NotificationSettings.objects.filter(user_id=user_id).only("locale").first()
    return s.locale if s and s.locale else "en"


def _short_date(s: dict, day: dt.date) -> str:
    """Locale-aware "lun 20 oct" / "Mon, Oct 20" (strftime follows the server
    locale, which is always English on Render)."""
    weekdays = s["date.weekdays"].split(",")
    months = s["date.months"].split(",")
    return s["date.short"].format(
        weekday=weekdays[day.weekday()], day=day.day, month=months[day.month - 1]
    )


def _capped(rows: Sequence[str], s: dict, cap: int = _LIST_CAP) -> list[str]:
    out = [_bullet(r) for r in rows[:cap]]
    if len(rows) > cap:
        out.append(s["list.more"].format(count=len(rows) - cap))
    return out


def _quoted_names(s: dict, names: Sequence[str]) -> str:
    """Plain-text "«A»", "«A» y «B»", "«A», «B» y 3 más" for push bodies."""
    if len(names) == 1:
        return s["push.list.one"].format(a=names[0])
    if len(names) == 2:
        return s["push.list.two"].format(a=names[0], b=names[1])
    return s["push.list.more"].format(a=names[0], b=names[1], count=len(names) - 2)


# ---------- Weekly ----------


def build_weekly_digest(user_id: uuid.UUID) -> BuiltMessage:
    locale = _resolve_locale(user_id)
    s = i18n_strings.get(locale)

    r = analytics.compute_analytics(user_id, AnalyticsRange.LAST_7_DAYS)
    active_days = r.cadence.active_days_in_range
    events = r.cadence.total_activity_events

    lines: list[str] = [f"📊 *{_esc(s['weekly.title'])}*"]
    if not active_days:
        lines.append(s["weekly.quiet"])
    else:
        lines.append(s["weekly.summary"].format(days=active_days, events=events))
    lines.append("")

    if r.top_projects:
        lines.append(f"📈 *{_esc(s['weekly.progressHeader'])}*")
        rows = []
        for row in r.top_projects:
            delta = row.delta_vs_prev
            if delta > 0:
                arrow = f" \\(↑{delta}\\)"
            elif delta < 0:
                arrow = f" \\(↓{abs(delta)}\\)"
            else:
                arrow = ""
            interactions = s["weekly.interactions"].format(count=row.interactions)
            rows.append(f"{_esc(row.name)} — {interactions}{arrow}")
        lines.extend(_capped(rows, s, _WEEKLY_CAP))
        lines.append("")

    b = r.backlog
    attention: list[str] = []
    if b.overdue_tasks or b.due_soon_tasks:
        parts = []
        if b.overdue_tasks:
            parts.append(s["weekly.overdue"].format(count=b.overdue_tasks))
        if b.due_soon_tasks:
            parts.append(s["weekly.dueSoon"].format(count=b.due_soon_tasks))
        parts.append(s["weekly.open"].format(count=b.open_tasks))
        attention.append(s["weekly.backlog"] + ", ".join(parts))
    sleeping = sorted(r.sleeping_projects, key=lambda p: -p.days_idle)
    attention.extend(
        s["weekly.sleepingRow"].format(name=_esc(p.name), days=p.days_idle)
        for p in sleeping
    )
    if r.stale_ideas:
        attention.append(s["weekly.staleRow"].format(count=len(r.stale_ideas)))
    if attention:
        lines.append(f"👀 *{_esc(s['weekly.attentionHeader'])}*")
        lines.extend(_capped(attention, s, _WEEKLY_CAP + 1))
        lines.append("")

    closers: list[str] = []
    if b.quick_wins:
        closers.append(s["weekly.quickWins"].format(count=b.quick_wins))
    if b.almost_there:
        closers.append(s["weekly.almostThere"].format(count=b.almost_there))
    if closers:
        lines.append(f"✅ *{_esc(s['weekly.closeHeader'])}*")
        lines.extend(_bullet(c) for c in closers)
        lines.append("")

    footer: list[str] = []
    if r.effort.effort_hours_total:
        footer.append(
            s["weekly.effort"].format(hours=_esc(f"{r.effort.effort_hours_total:.1f}"))
        )
    funnel = r.idea_funnel
    if funnel.ideas_created or funnel.ideas_promoted:
        footer.append(
            s["weekly.funnel"].format(
                created=funnel.ideas_created,
                promoted=funnel.ideas_promoted,
                rate=int(round(funnel.promotion_rate * 100)),
            )
        )
    if footer:
        lines.append(" · ".join(footer))

    return BuiltMessage(
        text="\n".join(lines).strip(),
        push=_weekly_push(s, r, active_days, events, sleeping),
    )


def _weekly_push(s: dict, r, active_days: int, events: int, sleeping) -> PushContent:
    common = {"path": "/analytics", "android_channel": "weekly", "quiet": True}
    if not active_days:
        return PushContent(
            title=s["push.weekly.quietTitle"], body=s["push.weekly.quietBody"], **common
        )
    parts: list[str] = []
    if r.top_projects and r.top_projects[0].interactions:
        parts.append(s["push.weekly.top"].format(name=r.top_projects[0].name))
    if sleeping:
        parts.append(
            s["push.weekly.sleeping"].format(name=sleeping[0].name, days=sleeping[0].days_idle)
        )
    elif r.backlog.overdue_tasks:
        parts.append(_plural(s, "push.weekly.overdue", r.backlog.overdue_tasks))
    if not parts:
        parts.append(_plural(s, "push.weekly.events", events))
    return PushContent(
        title=s["push.weekly.title"].format(days=active_days),
        body=" ".join(parts),
        **common,
    )


# ---------- Daily + end-of-day warning ----------


def build_daily_digest(user_id: uuid.UUID, *, today: dt.date | None = None) -> BuiltMessage:
    """Render the daily pending-tasks-and-routines digest for `user_id`.

    `today` is the user's local date; if omitted we resolve it from the
    user's `NotificationSettings.timezone` (the command passes it explicitly
    so the cutoff matches the user's schedule).
    """
    ctx = _daily_context(user_id, today)
    s = ctx.strings

    lines: list[str] = [
        f"📋 *{_esc(s['daily.title'])}* — {_esc(_short_date(s, ctx.today))}"
    ]

    if not ctx.total:
        lines.append(s["daily.empty"])
        return BuiltMessage(
            text="\n".join(lines),
            push=PushContent(
                title=s["push.daily.emptyTitle"],
                body=s["push.daily.emptyBody"],
                android_channel="daily",
            ),
        )

    summary = _plural(s, "daily.summary", ctx.total)
    if ctx.overdue:
        summary += _plural(s, "daily.summaryOverdue", len(ctx.overdue))
    lines.append(summary)
    lines.append("")

    focus = ctx.focus
    if focus is not None:
        lines.append(s["daily.focus"].format(task=_task_row(s, ctx, focus)))
        lines.append("")

    lines.extend(_render_pending_sections(ctx, skip=focus))
    return BuiltMessage(text="\n".join(lines).strip(), push=_daily_push(ctx))


def _daily_push(ctx: "_DailyContext") -> PushContent:
    s = ctx.strings
    title = _plural(s, "push.daily.title", ctx.total)
    if ctx.overdue:
        title = _plural(s, "push.daily.titleOverdue", len(ctx.overdue), base=title)

    focus = ctx.focus
    if focus is None:
        names = [r.title for r in ctx.routines_pending]
        return PushContent(
            title=title,
            body=s["push.daily.routinesOnly"].format(names=_quoted_names(s, names)),
            android_channel="daily",
        )

    days_late = ctx.days_late(focus)
    if days_late > 0:
        body = _plural(s, "push.daily.focusOverdue", days_late, title=focus.title)
    elif focus.project_id:
        body = s["push.daily.focusTodayProject"].format(
            title=focus.title, project=focus.project.name
        )
    else:
        body = s["push.daily.focusToday"].format(title=focus.title)
    return PushContent(
        title=title,
        body=body,
        android_channel="daily",
        category=CATEGORY_TASK_FOCUS,
        data={"taskIds": [str(focus.id)]},
    )


def build_due_warning(
    user_id: uuid.UUID, *, today: dt.date | None = None
) -> BuiltMessage | None:
    """End-of-day warning when items are still pending. Returns None when
    nothing's open so the command can skip the send."""
    ctx = _daily_context(user_id, today)
    if not ctx.total:
        return None
    s = ctx.strings

    lines: list[str] = [f"⚠️ *{_esc(s['due.title'])}*"]
    lines.append(_plural(s, "due.lead", ctx.total))
    lines.append("")
    lines.extend(_render_pending_sections(ctx))
    return BuiltMessage(text="\n".join(lines).strip(), push=_due_push(ctx))


def _due_push(ctx: "_DailyContext") -> PushContent:
    s = ctx.strings
    tasks = ctx.overdue + ctx.due_today
    names = [t.title for t in tasks] + [r.title for r in ctx.routines_pending]
    body = _quoted_names(s, names) + "."
    push = PushContent(
        title=_plural(s, "push.due.title", ctx.total),
        body=body,
        android_channel="reminders",
    )
    if tasks:
        push.body = f"{body} {_plural(s, 'push.due.ask', len(tasks))}"
        push.category = CATEGORY_TASK_FOCUS if len(tasks) == 1 else CATEGORY_TASKS_BULK
        push.data = {"taskIds": [str(t.id) for t in tasks]}
    return push


@dataclass
class _DailyContext:
    today: dt.date
    tz: zoneinfo.ZoneInfo
    strings: dict
    overdue: list[Task]
    due_today: list[Task]
    routines_pending: list["Routine"]

    @property
    def total(self) -> int:
        return len(self.overdue) + len(self.due_today) + len(self.routines_pending)

    @property
    def focus(self) -> Task | None:
        """The one task to start with: the longest-overdue, else the first due
        today. Routines are never the focus (they recur anyway)."""
        if self.overdue:
            return self.overdue[0]
        return self.due_today[0] if self.due_today else None

    def days_late(self, task: Task) -> int:
        return (self.today - task.due_date.astimezone(self.tz).date()).days


def _daily_context(user_id: uuid.UUID, today: dt.date | None) -> _DailyContext:
    setting = (
        NotificationSettings.objects.filter(user_id=user_id)
        .only("locale", "timezone")
        .first()
    )
    locale = (setting.locale if setting else "en") or "en"
    tz_name = (setting.timezone if setting else "UTC") or "UTC"
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except zoneinfo.ZoneInfoNotFoundError:
        tz = zoneinfo.ZoneInfo("UTC")
    if today is None:
        today = timezone.now().astimezone(tz).date()

    end_of_today_local = dt.datetime.combine(today, dt.time.max, tzinfo=tz)
    start_of_today_local = dt.datetime.combine(today, dt.time.min, tzinfo=tz)

    open_tasks = list(
        Task.objects.filter(
            user_id=user_id,
            done=False,
            due_date__isnull=False,
            due_date__lte=end_of_today_local,
        )
        .filter(
            Q(project__isnull=True)
            | Q(project__status__in=DAILY_VIEW_PROJECT_STATUSES)
        )
        .select_related("project")
        .order_by("due_date")
    )
    overdue = [t for t in open_tasks if t.due_date < start_of_today_local]
    due_today = [t for t in open_tasks if t.due_date >= start_of_today_local]

    return _DailyContext(
        today=today,
        tz=tz,
        strings=i18n_strings.get(locale),
        overdue=overdue,
        due_today=due_today,
        routines_pending=_pending_routines_for_day(user_id, today),
    )


def _render_pending_sections(ctx: _DailyContext, *, skip: Task | None = None) -> list[str]:
    """Shared section rendering for daily digest and due-warning. `skip` is the
    focus task, already shown on its own line above the sections."""
    s = ctx.strings
    lines: list[str] = []

    sections = (
        ("⏰", "daily.overdueHeader", [t for t in ctx.overdue if t is not skip]),
        ("📌", "daily.dueTodayHeader", [t for t in ctx.due_today if t is not skip]),
    )
    for emoji, header, tasks in sections:
        if not tasks:
            continue
        lines.append(f"{emoji} *{_esc(s[header])}*")
        lines.extend(_capped([_task_row(s, ctx, t) for t in tasks], s))
        lines.append("")

    if ctx.routines_pending:
        lines.append(f"🔁 *{_esc(s['daily.routinesHeader'])}*")
        lines.extend(_capped([_esc(r.title) for r in ctx.routines_pending], s))
        lines.append("")

    return lines


def _task_row(s: dict, ctx: _DailyContext, task: Task) -> str:
    if task.project_id:
        row = s["daily.rowWithProject"].format(
            title=_esc(task.title), project=_esc(task.project.name)
        )
    else:
        row = _esc(task.title)
    days_late = ctx.days_late(task)
    if days_late > 0:
        row += s["daily.rowOverdueSuffix"].format(days=days_late)
    return row


def _pending_routines_for_day(user_id: uuid.UUID, day: dt.date) -> list[Routine]:
    """Routines scheduled for `day` that don't have a completed occurrence yet."""
    items = routines_service.list_due_in_range(user_id, day, day)
    pending_ids = [
        item["routine_id"] for item in items if item["occurrence_id"] is None
    ]
    if not pending_ids:
        return []
    by_id = {
        r.id: r
        for r in Routine.objects.filter(user_id=user_id, id__in=pending_ids).only(
            "id", "title"
        )
    }
    # Preserve list_due_in_range's deterministic ordering.
    return [by_id[rid] for rid in pending_ids if rid in by_id]

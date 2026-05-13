"""Render notification bodies from the analytics module.

Each builder returns a Telegram MarkdownV2-safe string. Locale is resolved
from the user's `NotificationSettings.locale` (defaults to English).
"""

from __future__ import annotations

import datetime as dt
import uuid
import zoneinfo

from django.utils import timezone

from core import analytics
from core.analytics import AnalyticsRange
from core.models import Routine, Task
from core.services import routines as routines_service

from . import i18n as i18n_strings
from .models import NotificationSettings
from .providers.telegram import md_escape

DASHBOARD_URL = "https://continuu.it"


def _esc(text: str) -> str:
    return md_escape(text or "")


def _bullet(line: str) -> str:
    return f"• {line}"


def _resolve_locale(user_id: uuid.UUID) -> str:
    s = NotificationSettings.objects.filter(user_id=user_id).only("locale").first()
    return s.locale if s and s.locale else "en"


def build_weekly_digest(user_id: uuid.UUID) -> str:
    locale = _resolve_locale(user_id)
    s = i18n_strings.get(locale)

    r = analytics.compute_analytics(user_id, AnalyticsRange.LAST_7_DAYS)

    lines: list[str] = []
    lines.append(f"📊 *{_esc(s['weekly.title'])}*")
    lines.append("")

    streak = r.cadence.current_streak
    longest = r.cadence.longest_streak
    active_days = r.cadence.active_days_in_range
    streak_emoji = "🔥" if streak > 0 else "💤"
    lines.append(
        f"{streak_emoji} " + s["weekly.streak"].format(streak=streak, longest=longest)
    )
    lines.append("✅ " + s["weekly.activeDays"].format(days=active_days))
    lines.append(
        "📝 " + s["weekly.events"].format(count=r.cadence.total_activity_events)
    )
    lines.append("")

    if r.top_projects:
        lines.append(f"🏆 *{_esc(s['weekly.topProjects'])}*")
        for row in r.top_projects[:3]:
            delta = row.delta_vs_prev
            if delta > 0:
                arrow = f" \\(↑{delta}\\)"
            elif delta < 0:
                arrow = f" \\(↓{abs(delta)}\\)"
            else:
                arrow = ""
            interactions_str = s["weekly.interactions"].format(count=row.interactions)
            lines.append(_bullet(f"{_esc(row.name)} — {interactions_str}{arrow}"))
        lines.append("")

    b = r.backlog
    if b.open_tasks or b.overdue_tasks or b.due_soon_tasks:
        parts = []
        if b.overdue_tasks:
            parts.append(s["weekly.overdue"].format(count=b.overdue_tasks))
        if b.due_soon_tasks:
            parts.append(s["weekly.dueSoon"].format(count=b.due_soon_tasks))
        parts.append(s["weekly.open"].format(count=b.open_tasks))
        lines.append("📋 " + s["weekly.backlog"] + _esc(", ").join(parts))
        if b.quick_wins:
            lines.append(_bullet(s["weekly.quickWins"].format(count=b.quick_wins)))
        if b.almost_there:
            lines.append(_bullet(s["weekly.almostThere"].format(count=b.almost_there)))
        lines.append("")

    if r.sleeping_projects:
        lines.append(
            "😴 " + s["weekly.sleepingHeader"].format(count=len(r.sleeping_projects))
        )
        for row in r.sleeping_projects[:3]:
            lines.append(
                _bullet(
                    s["weekly.sleepingRow"].format(
                        name=_esc(row.name), days=row.days_idle
                    )
                )
            )
        lines.append("")

    if r.stale_ideas:
        lines.append("💡 " + s["weekly.staleHeader"].format(count=len(r.stale_ideas)))
        for row in r.stale_ideas[:3]:
            lines.append(_bullet(f"{_esc(row.title)} — {row.days_old}d"))
        lines.append("")

    funnel = r.idea_funnel
    if funnel.ideas_created or funnel.ideas_promoted:
        rate_pct = int(round(funnel.promotion_rate * 100))
        lines.append(
            "🚀 "
            + s["weekly.funnel"].format(
                created=funnel.ideas_created,
                promoted=funnel.ideas_promoted,
                rate=rate_pct,
            )
        )
        lines.append("")

    if r.effort.effort_hours_total:
        hours = r.effort.effort_hours_total
        hrs_str = _esc(f"{hours:.1f}")
        lines.append("⏱ " + s["weekly.effort"].format(hours=hrs_str))
        lines.append("")

    lines.append(f"[{_esc(s['weekly.openDashboard'])}]({DASHBOARD_URL})")

    return "\n".join(lines).strip()


def build_daily_digest(user_id: uuid.UUID, *, today: dt.date | None = None) -> str:
    """Render the daily pending-tasks-and-routines digest for `user_id`.

    `today` is the user's local date; if omitted we resolve it from the
    user's `NotificationSettings.timezone` (the command passes it explicitly
    so the cutoff matches the user's schedule).
    """
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
    s = i18n_strings.get(locale)

    end_of_today_local = dt.datetime.combine(today, dt.time.max, tzinfo=tz)
    start_of_today_local = dt.datetime.combine(today, dt.time.min, tzinfo=tz)

    open_tasks = list(
        Task.objects.filter(
            user_id=user_id,
            done=False,
            due_date__isnull=False,
            due_date__lte=end_of_today_local,
        )
        .select_related("project")
        .order_by("due_date")
    )
    overdue = [t for t in open_tasks if t.due_date < start_of_today_local]
    due_today = [t for t in open_tasks if t.due_date >= start_of_today_local]

    routines_pending = _pending_routines_for_day(user_id, today)

    lines: list[str] = []
    date_str = today.strftime("%a %d %b")
    lines.append(f"📋 *{_esc(s['daily.title'])}* — {_esc(date_str)}")
    lines.append("")

    if not overdue and not due_today and not routines_pending:
        lines.append(s["daily.empty"])
        return "\n".join(lines).strip()

    if overdue:
        lines.append("⏰ " + s["daily.overdueHeader"].format(count=len(overdue)))
        for task in overdue:
            days_late = (
                start_of_today_local.date() - task.due_date.astimezone(tz).date()
            ).days
            suffix = s["daily.rowOverdueSuffix"].format(days=days_late)
            lines.append(_bullet(_daily_task_row(s, task) + suffix))
        lines.append("")

    if due_today:
        lines.append("📌 " + s["daily.dueTodayHeader"].format(count=len(due_today)))
        for task in due_today:
            lines.append(_bullet(_daily_task_row(s, task)))
        lines.append("")

    if routines_pending:
        lines.append(
            "🔁 " + s["daily.routinesHeader"].format(count=len(routines_pending))
        )
        for routine in routines_pending:
            lines.append(
                _bullet(s["daily.routineRow"].format(title=_esc(routine.title)))
            )
        lines.append("")

    lines.append(s["daily.cta"])
    return "\n".join(lines).strip()


def _daily_task_row(s: dict, task: Task) -> str:
    project_name = task.project.name if task.project_id else ""
    if project_name:
        return s["daily.rowWithProject"].format(
            title=_esc(task.title), project=_esc(project_name)
        )
    return s["daily.rowNoProject"].format(title=_esc(task.title))


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

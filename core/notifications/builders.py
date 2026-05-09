"""Render notification bodies from the analytics module.

Each builder returns a Telegram MarkdownV2-safe string. Locale is resolved
from the user's `NotificationSettings.locale` (defaults to English).
"""

from __future__ import annotations

import uuid

from core import analytics
from core.analytics import AnalyticsRange

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

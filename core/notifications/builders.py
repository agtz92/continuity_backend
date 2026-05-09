"""Render notification bodies from the analytics module.

Each builder returns a Telegram MarkdownV2-safe string. When WhatsApp lands
(Phase 4) these will return a richer object that also produces HSM template
variables; for now Telegram only.
"""

from __future__ import annotations

import uuid

from core import analytics
from core.analytics import AnalyticsRange

from .providers.telegram import md_escape

DASHBOARD_URL = "https://continuu.it"


def _esc(text: str) -> str:
    return md_escape(text or "")


def _bullet(line: str) -> str:
    return f"• {line}"


def build_weekly_digest(user_id: uuid.UUID) -> str:
    r = analytics.compute_analytics(user_id, AnalyticsRange.LAST_7_DAYS)

    lines: list[str] = []
    lines.append("📊 *Your week on Continuity*")
    lines.append("")

    streak = r.cadence.current_streak
    longest = r.cadence.longest_streak
    active_days = r.cadence.active_days_in_range
    streak_emoji = "🔥" if streak > 0 else "💤"
    lines.append(
        f"{streak_emoji} Streak: *{streak}* days "
        f"\\(best: {longest}\\)"
    )
    lines.append(f"✅ Active *{active_days}* of 7 days this week")
    lines.append(f"📝 *{r.cadence.total_activity_events}* total events")
    lines.append("")

    if r.top_projects:
        lines.append("🏆 *Top projects*")
        for row in r.top_projects[:3]:
            delta = row.delta_vs_prev
            if delta > 0:
                arrow = f" \\(↑{delta}\\)"
            elif delta < 0:
                arrow = f" \\(↓{abs(delta)}\\)"
            else:
                arrow = ""
            lines.append(
                _bullet(f"{_esc(row.name)} — {row.interactions} interactions{arrow}")
            )
        lines.append("")

    b = r.backlog
    if b.open_tasks or b.overdue_tasks or b.due_soon_tasks:
        parts = []
        if b.overdue_tasks:
            parts.append(f"*{b.overdue_tasks}* overdue")
        if b.due_soon_tasks:
            parts.append(f"*{b.due_soon_tasks}* due soon")
        parts.append(f"*{b.open_tasks}* open")
        lines.append("📋 Backlog: " + _esc(", ").join(parts))
        if b.quick_wins:
            lines.append(_bullet(f"{b.quick_wins} *quick wins* ready to close"))
        if b.almost_there:
            lines.append(_bullet(f"{b.almost_there} projects *almost there*"))
        lines.append("")

    if r.sleeping_projects:
        lines.append(
            f"😴 *{len(r.sleeping_projects)}* sleeping projects"
        )
        for row in r.sleeping_projects[:3]:
            lines.append(
                _bullet(f"{_esc(row.name)} — {row.days_idle}d idle")
            )
        lines.append("")

    if r.stale_ideas:
        lines.append(f"💡 *{len(r.stale_ideas)}* ideas untouched for 30\\+ days")
        for row in r.stale_ideas[:3]:
            lines.append(_bullet(f"{_esc(row.title)} — {row.days_old}d"))
        lines.append("")

    funnel = r.idea_funnel
    if funnel.ideas_created or funnel.ideas_promoted:
        rate_pct = int(round(funnel.promotion_rate * 100))
        lines.append(
            f"🚀 Funnel: {funnel.ideas_created} ideas created, "
            f"{funnel.ideas_promoted} promoted \\({rate_pct}%\\)"
        )
        lines.append("")

    if r.effort.effort_hours_total:
        hours = r.effort.effort_hours_total
        hrs_str = _esc(f"{hours:.1f}")
        lines.append(f"⏱ *{hrs_str}*h of logged effort")
        lines.append("")

    lines.append(f"[Open dashboard]({DASHBOARD_URL})")

    return "\n".join(lines).strip()

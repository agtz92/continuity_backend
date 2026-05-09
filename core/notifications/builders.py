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
    lines.append("📊 *Tu semana en Continuity*")
    lines.append("")

    streak = r.cadence.current_streak
    longest = r.cadence.longest_streak
    active_days = r.cadence.active_days_in_range
    streak_emoji = "🔥" if streak > 0 else "💤"
    lines.append(
        f"{streak_emoji} Racha: *{streak}* d{_esc('í')}as "
        f"\\(mejor: {longest}\\)"
    )
    lines.append(f"✅ Activo *{active_days}* de 7 d{_esc('í')}as esta semana")
    lines.append(f"📝 *{r.cadence.total_activity_events}* eventos en total")
    lines.append("")

    if r.top_projects:
        lines.append("🏆 *Top proyectos*")
        for row in r.top_projects[:3]:
            delta = row.delta_vs_prev
            if delta > 0:
                arrow = f" \\(↑{delta}\\)"
            elif delta < 0:
                arrow = f" \\(↓{abs(delta)}\\)"
            else:
                arrow = ""
            lines.append(
                _bullet(f"{_esc(row.name)} — {row.interactions} interacciones{arrow}")
            )
        lines.append("")

    b = r.backlog
    if b.open_tasks or b.overdue_tasks or b.due_soon_tasks:
        parts = []
        if b.overdue_tasks:
            parts.append(f"*{b.overdue_tasks}* vencidas")
        if b.due_soon_tasks:
            parts.append(f"*{b.due_soon_tasks}* por vencer")
        parts.append(f"*{b.open_tasks}* abiertas")
        lines.append("📋 Backlog: " + _esc(", ").join(parts))
        if b.quick_wins:
            lines.append(_bullet(f"{b.quick_wins} *quick wins* listos para cerrar"))
        if b.almost_there:
            lines.append(_bullet(f"{b.almost_there} proyectos *casi terminados*"))
        lines.append("")

    if r.sleeping_projects:
        lines.append(
            f"😴 *{len(r.sleeping_projects)}* proyectos durmiendo"
        )
        for row in r.sleeping_projects[:3]:
            lines.append(
                _bullet(f"{_esc(row.name)} — {row.days_idle}d sin actividad")
            )
        lines.append("")

    if r.stale_ideas:
        lines.append(f"💡 *{len(r.stale_ideas)}* ideas sin tocar hace 30\\+ d{_esc('í')}as")
        for row in r.stale_ideas[:3]:
            lines.append(_bullet(f"{_esc(row.title)} — {row.days_old}d"))
        lines.append("")

    funnel = r.idea_funnel
    if funnel.ideas_created or funnel.ideas_promoted:
        rate_pct = int(round(funnel.promotion_rate * 100))
        lines.append(
            f"🚀 Funnel: {funnel.ideas_created} ideas creadas, "
            f"{funnel.ideas_promoted} promovidas \\({rate_pct}%\\)"
        )
        lines.append("")

    if r.effort.effort_hours_total:
        hours = r.effort.effort_hours_total
        hrs_str = _esc(f"{hours:.1f}")
        lines.append(f"⏱ *{hrs_str}*h de esfuerzo registrado")
        lines.append("")

    lines.append(f"[Ver dashboard]({DASHBOARD_URL})")

    return "\n".join(lines).strip()

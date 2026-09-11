"""Loop's deterministic catalogue — the Pro tier's chat.

A fixed set of read-only questions. Each one runs a real query against the
user's data and renders the answer from a template, **server-side, in the
user's language, without ever calling Anthropic**. That is the whole
point: nothing here can hallucinate, rate-limit, cost money, or stall
halfway through.

Why it calls `core.services.*` directly instead of the assistant's read
tools: the `@tool` decorator truncates every result to 2 KB / 10 items so
a model doesn't drown in context. That is right for a model and wrong for
a list a person is reading — "you have 14 overdue tasks" must show 14.
Same data, same services, no cap.

Adding an action is one entry in `ACTIONS` plus its labels in `STRINGS`.
The client renders whatever `catalogue()` returns, so no frontend change
is needed for a new question.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from django.utils import timezone

from core.services import activities as activities_svc
from core.services import ideas as ideas_svc
from core.services import projects as projects_svc
from core.services import routines as routines_svc
from core.services import search as search_svc
from core.services import tasks as tasks_svc
from core.services.summary import get_dashboard_summary


# --------------------------------------------------------------------------
# Copy
#
# Server-rendered because the answer is content, not chrome: the client
# only knows how to paint markdown blocks. Labels are here too so the
# catalogue endpoint can hand the client ready-to-show buttons and the two
# never drift.
# --------------------------------------------------------------------------

STRINGS: dict[str, dict[str, str]] = {
    "es": {
        "group.today": "Hoy",
        "group.work": "Trabajo abierto",
        "group.review": "Revisión",
        "today_summary": "Resumen de hoy",
        "overdue": "Qué tengo vencido",
        "due_this_week": "Qué vence esta semana",
        "blocked": "Tareas bloqueadas",
        "routines_today": "Rutinas de hoy",
        "active_projects": "Proyectos activos por prioridad",
        "stalled_projects": "Proyectos estancados",
        "last_7_days": "En qué trabajé estos 7 días",
        "stale_ideas": "Ideas estancadas",
        "search": "Buscar en todo",
        "search.placeholder": "Escribe qué buscar…",
        "empty.overdue": "No tienes nada vencido. Todo al día.",
        "empty.due_this_week": "No vence nada en los próximos 7 días.",
        "empty.blocked": "No tienes tareas bloqueadas.",
        "empty.routines_today": "No hay rutinas programadas para hoy.",
        "empty.active_projects": "No tienes proyectos activos ahora mismo.",
        "empty.stalled_projects": "Ningún proyecto lleva 14 días sin movimiento.",
        "empty.last_7_days": "No hay actividad registrada en los últimos 7 días.",
        "empty.stale_ideas": "No tienes ideas de más de 30 días sin tocar.",
        "empty.search": "No encontré nada con **{query}**.",
        "head.overdue": "**{n}** vencidas",
        "head.due_this_week": "**{n}** vencen esta semana",
        "head.blocked": "**{n}** bloqueadas",
        "head.routines_today": "Rutinas de hoy",
        "head.active_projects": "**{n}** proyectos activos",
        "head.stalled_projects": "**{n}** estancados",
        "head.last_7_days": "Últimos 7 días",
        "head.stale_ideas": "**{n}** ideas de más de 30 días",
        "head.search": "**{n}** resultados para **{query}**",
        "summary.projects": "Proyectos",
        "summary.tasks": "Tareas",
        "summary.ideas": "Ideas",
        "summary.active": "{n} activos",
        "summary.stalled": "{n} estancados",
        "summary.open": "{n} abiertas",
        "summary.overdue": "{n} vencidas",
        "summary.due_soon": "{n} vencen pronto",
        "summary.blocked": "{n} bloqueadas",
        "summary.open_ideas": "{n} sin promover",
        "days_overdue": "vencida hace {n} d",
        "due_today": "vence hoy",
        "due_in": "vence en {n} d",
        "no_due": "sin fecha",
        "idle_days": "{n} d sin movimiento",
        "blocked_by_task": "espera otra tarea",
        "done_mark": "hecha",
        "pending_mark": "pendiente",
        "events": "{n} movimientos",
        "standalone": "suelta",
    },
    "en": {
        "group.today": "Today",
        "group.work": "Open work",
        "group.review": "Review",
        "today_summary": "Today's summary",
        "overdue": "What's overdue",
        "due_this_week": "What's due this week",
        "blocked": "Blocked tasks",
        "routines_today": "Today's routines",
        "active_projects": "Active projects by priority",
        "stalled_projects": "Stalled projects",
        "last_7_days": "What I worked on this week",
        "stale_ideas": "Stale ideas",
        "search": "Search everything",
        "search.placeholder": "Type what to look for…",
        "empty.overdue": "Nothing overdue. You're current.",
        "empty.due_this_week": "Nothing due in the next 7 days.",
        "empty.blocked": "No blocked tasks.",
        "empty.routines_today": "No routines scheduled for today.",
        "empty.active_projects": "No active projects right now.",
        "empty.stalled_projects": "No project has been idle for 14 days.",
        "empty.last_7_days": "No activity recorded in the last 7 days.",
        "empty.stale_ideas": "No ideas older than 30 days.",
        "empty.search": "Nothing found for **{query}**.",
        "head.overdue": "**{n}** overdue",
        "head.due_this_week": "**{n}** due this week",
        "head.blocked": "**{n}** blocked",
        "head.routines_today": "Today's routines",
        "head.active_projects": "**{n}** active projects",
        "head.stalled_projects": "**{n}** stalled",
        "head.last_7_days": "Last 7 days",
        "head.stale_ideas": "**{n}** ideas older than 30 days",
        "head.search": "**{n}** results for **{query}**",
        "summary.projects": "Projects",
        "summary.tasks": "Tasks",
        "summary.ideas": "Ideas",
        "summary.active": "{n} active",
        "summary.stalled": "{n} stalled",
        "summary.open": "{n} open",
        "summary.overdue": "{n} overdue",
        "summary.due_soon": "{n} due soon",
        "summary.blocked": "{n} blocked",
        "summary.open_ideas": "{n} unpromoted",
        "days_overdue": "{n}d overdue",
        "due_today": "due today",
        "due_in": "due in {n}d",
        "no_due": "no date",
        "idle_days": "idle {n}d",
        "blocked_by_task": "waiting on another task",
        "done_mark": "done",
        "pending_mark": "pending",
        "events": "{n} events",
        "standalone": "standalone",
    },
}

#: How many rows a single answer shows before it stops. Generous — this is
#: a person reading a list, not a model consuming context — but not
#: unbounded, because a 400-row answer is not an answer.
MAX_ROWS = 40


def _t(locale: str, key: str, **fmt) -> str:
    table = STRINGS.get(locale) or STRINGS["en"]
    text = table.get(key) or STRINGS["en"].get(key) or key
    return text.format(**fmt) if fmt else text


# --------------------------------------------------------------------------
# Rendering helpers
#
# The client paints the same markdown subset the model is told to use, so
# these emit exactly that: `- **label**: text` bullets and
# `[Name](task:uuid)` entity links, which become clickable chips.
# --------------------------------------------------------------------------


def _link(kind: str, obj_id, label: str) -> str:
    safe = (label or "").replace("[", "(").replace("]", ")").strip() or "—"
    return f"[{safe}]({kind}:{obj_id})"


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def _overflow(locale: str, shown: int, total: int) -> str:
    if total <= shown:
        return ""
    more = total - shown
    tail = f"\n\n+{more} más." if locale == "es" else f"\n\n+{more} more."
    return tail


def _answer(locale: str, head: str, lines: list[str], total: int) -> str:
    body = _bullets(lines[:MAX_ROWS])
    return f"{head}\n\n{body}{_overflow(locale, min(len(lines), MAX_ROWS), total)}"


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CannedAction:
    id: str
    group: str
    #: True for the one action that takes free text (search). The client
    #: shows an input for it instead of a plain button.
    needs_query: bool
    run: Callable[[uuid.UUID, str, Optional[str]], str]


def _today(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    s = get_dashboard_summary(user_id)
    return _bullets(
        [
            f"**{_t(locale, 'summary.projects')}**: "
            + ", ".join(
                [
                    _t(locale, "summary.active", n=s.active_projects),
                    # `stalled_projects`, not `sleeping_projects`: stalled is
                    # the stored state the product actually names.
                    _t(locale, "summary.stalled", n=s.stalled_projects),
                ]
            ),
            f"**{_t(locale, 'summary.tasks')}**: "
            + ", ".join(
                [
                    _t(locale, "summary.open", n=s.open_tasks),
                    _t(locale, "summary.overdue", n=s.overdue_tasks),
                    _t(locale, "summary.due_soon", n=s.due_soon_tasks),
                    _t(locale, "summary.blocked", n=s.blocked_tasks),
                ]
            ),
            f"**{_t(locale, 'summary.ideas')}**: "
            + _t(locale, "summary.open_ideas", n=s.open_ideas),
        ]
    )


def _due_on(task) -> Optional[dt.date]:
    """`Task.due_date` is a DateTimeField even though the product treats it
    as a day. Compare dates, in the user's zone, or you get an off-by-one
    around midnight — and a TypeError the moment you forget."""
    if not task.due_date:
        return None
    return timezone.localtime(task.due_date).date()


def _due_label(locale: str, task, today: dt.date) -> str:
    due = _due_on(task)
    if due is None:
        return _t(locale, "no_due")
    delta = (due - today).days
    if delta < 0:
        return _t(locale, "days_overdue", n=-delta)
    if delta == 0:
        return _t(locale, "due_today")
    return _t(locale, "due_in", n=delta)


def _task_line(locale: str, task, today: dt.date) -> str:
    return (
        f"**{_due_label(locale, task, today)}**: "
        f"{_link('task', task.id, task.title)}"
    )


def _overdue(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    today = timezone.localdate()
    rows = [
        t
        for t in tasks_svc.list_tasks(user_id, done=False, daily_view=True, limit=500)
        if (_due_on(t) or today) < today
    ]
    rows.sort(key=lambda t: _due_on(t) or today)
    if not rows:
        return _t(locale, "empty.overdue")
    return _answer(
        locale,
        _t(locale, "head.overdue", n=len(rows)),
        [_task_line(locale, t, today) for t in rows],
        len(rows),
    )


def _due_this_week(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    today = timezone.localdate()
    rows = [
        t
        for t in tasks_svc.list_tasks(
            user_id, done=False, due_within_days=7, daily_view=True, limit=500
        )
        if _due_on(t) is not None and _due_on(t) >= today
    ]
    rows.sort(key=lambda t: _due_on(t))
    if not rows:
        return _t(locale, "empty.due_this_week")
    return _answer(
        locale,
        _t(locale, "head.due_this_week", n=len(rows)),
        [_task_line(locale, t, today) for t in rows],
        len(rows),
    )


def _blocked(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    rows = [
        t
        for t in tasks_svc.list_tasks(user_id, done=False, daily_view=True, limit=500)
        if t.blockers.all()
    ]
    if not rows:
        return _t(locale, "empty.blocked")

    lines = []
    for t in rows:
        reasons = []
        for b in t.blockers.all():
            if b.blocking_task_id:
                reasons.append(_t(locale, "blocked_by_task"))
            elif b.external_description:
                reasons.append(b.external_description.strip())
        why = " · ".join(reasons) or "—"
        lines.append(f"**{why}**: {_link('task', t.id, t.title)}")

    return _answer(
        locale, _t(locale, "head.blocked", n=len(rows)), lines, len(rows)
    )


def _routines_today(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    today = timezone.localdate()
    routines = {
        r.id: r for r in routines_svc.list_routines(user_id, include_archived=False)
    }
    items = routines_svc.list_due_in_range(user_id, today, today)
    if not items:
        return _t(locale, "empty.routines_today")

    lines = []
    for it in items:
        r = routines.get(it["routine_id"])
        mark = _t(locale, "done_mark" if it["occurrence_id"] else "pending_mark")
        title = r.title if r else "—"
        lines.append(f"**{mark}**: {title}")

    return _answer(
        locale, _t(locale, "head.routines_today"), lines, len(items)
    )


_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _active_projects(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    rows = projects_svc.list_projects(user_id, status="active", limit=50)
    if not rows:
        return _t(locale, "empty.active_projects")
    rows.sort(key=lambda p: _PRIORITY_ORDER.get(p.priority, 9))
    lines = [
        f"**{p.priority}**: {_link('project', p.id, p.name)}" for p in rows
    ]
    return _answer(
        locale, _t(locale, "head.active_projects", n=len(rows)), lines, len(rows)
    )


def _stalled_projects(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    rows = projects_svc.list_projects(user_id, status="stalled", limit=50)
    if not rows:
        return _t(locale, "empty.stalled_projects")
    now = timezone.now()

    def idle(p) -> int:
        if not p.last_activity:
            return 0
        return max(0, int((now - p.last_activity).total_seconds() // 86400))

    rows.sort(key=idle, reverse=True)
    lines = [
        f"**{_t(locale, 'idle_days', n=idle(p))}**: {_link('project', p.id, p.name)}"
        for p in rows
    ]
    return _answer(
        locale, _t(locale, "head.stalled_projects", n=len(rows)), lines, len(rows)
    )


def _last_7_days(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    since = timezone.now() - dt.timedelta(days=7)
    events = activities_svc.list_activity(user_id, since=since, limit=500)
    if not events:
        return _t(locale, "empty.last_7_days")

    by_project: dict[object, int] = {}
    names: dict[object, str] = {}
    for e in events:
        key = e.project_id
        by_project[key] = by_project.get(key, 0) + 1

    for p in projects_svc.list_projects(user_id, limit=50):
        names[p.id] = p.name

    ordered = sorted(by_project.items(), key=lambda kv: kv[1], reverse=True)
    lines = []
    for pid, count in ordered:
        label = _t(locale, "events", n=count)
        if pid is None:
            lines.append(f"**{label}**: {_t(locale, 'standalone')}")
        else:
            lines.append(
                f"**{label}**: {_link('project', pid, names.get(pid, '—'))}"
            )

    return _answer(
        locale, _t(locale, "head.last_7_days"), lines, len(ordered)
    )


def _stale_ideas(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    cutoff = timezone.now() - dt.timedelta(days=30)
    rows = [
        i
        for i in ideas_svc.list_ideas(user_id, limit=100)
        if i.created and i.created < cutoff
    ]
    if not rows:
        return _t(locale, "empty.stale_ideas")
    now = timezone.now()
    lines = [
        "**"
        + _t(
            locale,
            "idle_days",
            n=max(0, int((now - i.created).total_seconds() // 86400)),
        )
        + f"**: {_link('idea', i.id, i.title)}"
        for i in rows
    ]
    return _answer(
        locale, _t(locale, "head.stale_ideas", n=len(rows)), lines, len(rows)
    )


_SEARCH_KIND_LINK = {
    "project": "project",
    "task": "task",
    "idea": "idea",
    "note": "note",
    "quick_note": "note",
}


def _search(user_id: uuid.UUID, locale: str, query: Optional[str]) -> str:
    q = (query or "").strip()
    if not q:
        return _t(locale, "empty.search", query="")
    hits = search_svc.search(user_id, query=q, limit=MAX_ROWS)
    if not hits:
        return _t(locale, "empty.search", query=q)
    lines = [
        f"**{h.kind}**: "
        + _link(_SEARCH_KIND_LINK.get(h.kind, h.kind), h.id, h.title)
        for h in hits
    ]
    return _answer(
        locale, _t(locale, "head.search", n=len(hits), query=q), lines, len(hits)
    )


ACTIONS: dict[str, CannedAction] = {
    a.id: a
    for a in [
        CannedAction("today_summary", "today", False, _today),
        CannedAction("overdue", "today", False, _overdue),
        CannedAction("routines_today", "today", False, _routines_today),
        CannedAction("due_this_week", "work", False, _due_this_week),
        CannedAction("blocked", "work", False, _blocked),
        CannedAction("active_projects", "work", False, _active_projects),
        CannedAction("stalled_projects", "review", False, _stalled_projects),
        CannedAction("last_7_days", "review", False, _last_7_days),
        CannedAction("stale_ideas", "review", False, _stale_ideas),
        CannedAction("search", "review", True, _search),
    ]
}

GROUP_ORDER = ["today", "work", "review"]


def catalogue(locale: str) -> list[dict]:
    """What the client renders. Grouped, labelled, ready to show."""
    out = []
    for group in GROUP_ORDER:
        out.append(
            {
                "group": group,
                "label": _t(locale, f"group.{group}"),
                "actions": [
                    {
                        "id": a.id,
                        "label": _t(locale, a.id),
                        "needs_query": a.needs_query,
                        "placeholder": (
                            _t(locale, f"{a.id}.placeholder")
                            if a.needs_query
                            else ""
                        ),
                    }
                    for a in ACTIONS.values()
                    if a.group == group
                ],
            }
        )
    return out


class UnknownAction(Exception):
    pass


def run(action_id: str, user_id: uuid.UUID, *, locale: str, query: str = "") -> dict:
    """Execute one catalogue action. Returns Anthropic-shaped content blocks.

    Same shape as an assistant turn (`[{"type": "text", "text": ...}]`) so
    it persists into `Message.content` and renders through the same client
    component as an `llm`-tier answer. A user upgrading mid-conversation
    sees one continuous thread, not two chat products stitched together.
    """
    action = ACTIONS.get(action_id)
    if action is None:
        raise UnknownAction(action_id)
    text = action.run(user_id, locale if locale in STRINGS else "en", query)
    return {
        "action_id": action_id,
        "label": _t(locale if locale in STRINGS else "en", action_id),
        "content": [{"type": "text", "text": text}],
    }

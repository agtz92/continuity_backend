"""Phase 1 read-only tools.

Each handler:
- takes `(user_id, args)` where args matches the JSON schema declared
  alongside the tool;
- delegates to a `core.services.*` function so business logic is shared
  with the GraphQL resolvers;
- returns a JSON-serializable dict (the @tool decorator handles
  truncation and error wrapping).
"""

from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone

from core.services import categories as categories_svc
from core.services import ideas as ideas_svc
from core.services import notes as notes_svc
from core.services import projects as projects_svc
from core.services import search as search_svc
from core.services import tasks as tasks_svc
from core.services import updates as updates_svc
from core.services.analytics import AnalyticsRange, compute_analytics
from core.services.projects import NotFoundError
from core.services.summary import get_dashboard_summary

from . import days_between, short_text, tool


# ---------- Schemas as constants ----------

_LIMIT = {"type": "integer", "minimum": 1, "maximum": 50}


# ---------- Dashboard summary ----------


@tool(
    name="get_dashboard_summary",
    description=(
        "Top-level counts: active vs sleeping vs launched vs archived projects, "
        "open / overdue / due-soon tasks, and ideas. Use this when the user asks "
        "'how am I doing' or 'what's my workload' style questions."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)
def _get_dashboard_summary(user_id: uuid.UUID, args: dict) -> dict:
    s = get_dashboard_summary(user_id)
    return {
        "active_projects": s.active_projects,
        "sleeping_projects": s.sleeping_projects,
        "launched_projects": s.launched_projects,
        "archived_projects": s.archived_projects,
        "open_tasks": s.open_tasks,
        "overdue_tasks": s.overdue_tasks,
        "due_soon_tasks": s.due_soon_tasks,
        "open_ideas": s.open_ideas,
        "categories": s.categories,
        "last_activity": s.last_activity.isoformat() if s.last_activity else None,
    }


# ---------- Projects ----------


@tool(
    name="list_projects",
    description=(
        "List the user's projects. Filter by status, priority, or category. "
        "Returns id, name, status, priority, days_idle, and a short description "
        "snippet. Sorted by most-recent activity. Default limit 20, max 50."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["idea", "active", "stalled", "paused", "launched", "archived"],
            },
            "priority": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low"],
            },
            "category_id": {"type": "string", "format": "uuid"},
            "limit": {**_LIMIT, "default": 20},
        },
        "additionalProperties": False,
    },
)
def _list_projects(user_id: uuid.UUID, args: dict) -> dict:
    now = timezone.now()
    rows = projects_svc.list_projects(
        user_id,
        status=args.get("status"),
        priority=args.get("priority"),
        category_id=args.get("category_id"),
        limit=int(args.get("limit") or 20),
    )
    return {
        "projects": [
            {
                "id": str(p.id),
                "name": p.name,
                "status": p.status,
                "priority": p.priority,
                "category_id": str(p.category_id) if p.category_id else None,
                "days_idle": days_between(p.last_activity, now=now),
                "description": short_text(p.description),
                "next_step": short_text(p.next_step),
            }
            for p in rows
        ],
        "count": len(rows),
    }


@tool(
    name="get_project_detail",
    description=(
        "Fetch one project plus its 10 most-recent tasks, 5 most-recent "
        "updates, and the titles of any project-notes. Use after the user "
        "narrows down to a specific project."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _get_project_detail(user_id: uuid.UUID, args: dict) -> dict:
    now = timezone.now()
    try:
        p = projects_svc.get_project(user_id, args["id"])
    except NotFoundError:
        return {"error": "Project not found"}

    tasks = tasks_svc.list_tasks(user_id, project_id=p.id, limit=10)
    updates = updates_svc.list_updates(user_id, project_id=p.id, limit=5)
    notes = notes_svc.list_notes(user_id, project_id=p.id, limit=10)

    return {
        "project": {
            "id": str(p.id),
            "name": p.name,
            "description": short_text(p.description, 600),
            "why": short_text(p.why, 400),
            "next_step": short_text(p.next_step, 400),
            "status": p.status,
            "priority": p.priority,
            "category_id": str(p.category_id) if p.category_id else None,
            "days_idle": days_between(p.last_activity, now=now),
            "last_activity": p.last_activity.isoformat(),
            "created": p.created.isoformat(),
        },
        "tasks": [
            {
                "id": str(t.id),
                "title": short_text(t.title),
                "done": t.done,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "effort_hours": t.effort_hours,
            }
            for t in tasks
        ],
        "updates": [
            {
                "id": str(u.id),
                "note": short_text(u.note),
                "date": u.date.isoformat(),
            }
            for u in updates
        ],
        "notes": [
            {
                "id": str(n.id),
                "title": n.title or short_text(n.body, 60),
                "preview": short_text(n.body, 120),
            }
            for n in notes
        ],
    }


# ---------- Tasks ----------


@tool(
    name="list_tasks",
    description=(
        "List tasks. Filter by project, by `done`, or by `due_within_days` "
        "to find what's coming up. Default limit 20, max 50."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "format": "uuid"},
            "done": {"type": "boolean"},
            "due_within_days": {"type": "integer", "minimum": 0, "maximum": 365},
            "limit": {**_LIMIT, "default": 20},
        },
        "additionalProperties": False,
    },
)
def _list_tasks(user_id: uuid.UUID, args: dict) -> dict:
    rows = tasks_svc.list_tasks(
        user_id,
        project_id=args.get("project_id"),
        done=args.get("done"),
        due_within_days=args.get("due_within_days"),
        limit=int(args.get("limit") or 20),
    )
    return {
        "tasks": [
            {
                "id": str(t.id),
                "title": short_text(t.title),
                "project_id": str(t.project_id) if t.project_id else None,
                "done": t.done,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "effort_hours": t.effort_hours,
            }
            for t in rows
        ],
        "count": len(rows),
    }


# ---------- Ideas ----------


@tool(
    name="list_ideas",
    description=(
        "List the user's open ideas (not yet promoted to projects). "
        "Sorted newest first. Default limit 20, max 50."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "limit": {**_LIMIT, "default": 20},
        },
        "additionalProperties": False,
    },
)
def _list_ideas(user_id: uuid.UUID, args: dict) -> dict:
    rows = ideas_svc.list_ideas(user_id, limit=int(args.get("limit") or 20))
    return {
        "ideas": [
            {
                "id": str(i.id),
                "title": i.title,
                "description": short_text(i.description),
                "why": short_text(i.why),
                "created": i.created.isoformat(),
            }
            for i in rows
        ],
        "count": len(rows),
    }


# ---------- Categories ----------


@tool(
    name="list_categories",
    description="List the user's project categories.",
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)
def _list_categories(user_id: uuid.UUID, args: dict) -> dict:
    rows = categories_svc.list_categories(user_id)
    return {
        "categories": [
            {"id": str(c.id), "name": c.name, "color": c.color} for c in rows
        ],
        "count": len(rows),
    }


# ---------- Analytics ----------


_ANALYTICS_VIEWS = (
    "cadence",
    "top_projects",
    "backlog_health",
    "sleeping",
    "stale_ideas",
    "idea_funnel",
    "effort",
    "weekday_heatmap",
)


@tool(
    name="get_analytics",
    description=(
        "Fetch a slice of the user's analytics. Use `view` to pick the "
        "section: cadence (streaks), top_projects, backlog_health (overdue / "
        "quick-wins), sleeping (idle projects), stale_ideas, idea_funnel "
        "(promotion rate), effort (hours by project), weekday_heatmap. "
        "Use `range` to pick the time window."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "view": {"type": "string", "enum": list(_ANALYTICS_VIEWS)},
            "range": {
                "type": "string",
                "enum": [
                    "LAST_7_DAYS",
                    "LAST_30_DAYS",
                    "LAST_90_DAYS",
                    "LAST_365_DAYS",
                    "ALL_TIME",
                ],
                "default": "LAST_30_DAYS",
            },
        },
        "required": ["view"],
        "additionalProperties": False,
    },
)
def _get_analytics(user_id: uuid.UUID, args: dict) -> dict:
    view = args["view"]
    range_str = args.get("range", "LAST_30_DAYS")
    try:
        rng = AnalyticsRange(range_str)
    except ValueError:
        return {"error": f"Unknown range: {range_str}"}

    result = compute_analytics(user_id, rng)

    if view == "cadence":
        c = result.cadence
        return {
            "view": view,
            "range": range_str,
            "current_streak": c.current_streak,
            "longest_streak": c.longest_streak,
            "active_days_in_range": c.active_days_in_range,
            "total_activity_events": c.total_activity_events,
        }
    if view == "top_projects":
        return {
            "view": view,
            "range": range_str,
            "rows": [
                {
                    "project_id": str(r.project_id),
                    "name": r.name,
                    "status": r.status,
                    "interactions": r.interactions,
                    "delta_vs_prev": r.delta_vs_prev,
                }
                for r in result.top_projects
            ],
        }
    if view == "backlog_health":
        b = result.backlog
        return {
            "view": view,
            "range": range_str,
            "overdue_tasks": b.overdue_tasks,
            "due_soon_tasks": b.due_soon_tasks,
            "open_tasks": b.open_tasks,
            "quick_wins": b.quick_wins,
            "almost_there": b.almost_there,
        }
    if view == "sleeping":
        return {
            "view": view,
            "range": range_str,
            "rows": [
                {
                    "project_id": str(r.project_id),
                    "name": r.name,
                    "days_idle": r.days_idle,
                    "bucket": r.bucket,
                }
                for r in result.sleeping_projects
            ],
        }
    if view == "stale_ideas":
        return {
            "view": view,
            "range": range_str,
            "rows": [
                {
                    "idea_id": str(r.idea_id),
                    "title": r.title,
                    "days_old": r.days_old,
                }
                for r in result.stale_ideas
            ],
        }
    if view == "idea_funnel":
        f = result.idea_funnel
        return {
            "view": view,
            "range": range_str,
            "ideas_created": f.ideas_created,
            "ideas_promoted": f.ideas_promoted,
            "promotion_rate": f.promotion_rate,
        }
    if view == "effort":
        e = result.effort
        return {
            "view": view,
            "range": range_str,
            "effort_hours_total": e.effort_hours_total,
            "tasks_with_effort_pct": e.tasks_with_effort_pct,
            "by_project": [
                {
                    "project_id": str(r.project_id),
                    "name": r.name,
                    "hours": r.hours,
                }
                for r in e.effort_hours_by_project
            ],
        }
    if view == "weekday_heatmap":
        return {
            "view": view,
            "range": range_str,
            "buckets": [
                {"weekday": b.weekday, "count": b.count}
                for b in result.weekday_heatmap
            ],
        }

    return {"error": f"Unknown view: {view}"}


# ---------- Search ----------


@tool(
    name="search",
    description=(
        "Case-insensitive substring search across the user's projects, "
        "tasks, ideas, and notes. Use for open-ended 'where did I write "
        "about X' questions. Default limit 10, max 50."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "kind": {
                "type": "string",
                "enum": ["project", "task", "idea", "note"],
            },
            "limit": {**_LIMIT, "default": 10},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)
def _search(user_id: uuid.UUID, args: dict) -> dict:
    hits = search_svc.search(
        user_id,
        query=args.get("query") or "",
        kind=args.get("kind"),
        limit=int(args.get("limit") or 10),
    )
    return {
        "hits": [
            {
                "kind": h.kind,
                "id": str(h.id),
                "title": h.title,
                "snippet": h.snippet,
                "project_id": str(h.project_id) if h.project_id else None,
            }
            for h in hits
        ],
        "count": len(hits),
    }

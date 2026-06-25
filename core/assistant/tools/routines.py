"""Read-only tools for routines.

Routines are recurring (or one-off) activities that stand on their own —
they are NOT tied to a project and are distinct from project Tasks.
Pending occurrences are computed on the fly; completed ones are stored as
RoutineOccurrence rows. See `core.services.routines`.

Each handler takes `(user_id, args)`, delegates to `core.services.routines`
so business logic is shared with the GraphQL resolvers, and returns a
JSON-serializable dict (the @tool decorator handles truncation/errors).
"""

from __future__ import annotations

import datetime as dt
import uuid

from django.utils import timezone

from core.services import routines as routines_svc

from . import short_text, tool


_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _describe_recurrence(r) -> str:
    """Render a routine's recurrence rule as a short human-readable string."""
    rtype = r.recurrence_type
    if rtype == "once":
        return f"One-time on {r.start_date.isoformat()}"
    if rtype == "weekly_days":
        days = ", ".join(
            _WEEKDAY_NAMES[d] for d in sorted(r.weekdays or []) if 0 <= d <= 6
        )
        return f"Weekly on {days}" if days else "Weekly"
    if rtype == "every_n":
        return f"Every {r.interval_n or 1} {r.interval_unit or 'days'}"
    if rtype == "monthly_day":
        return f"Monthly on day {r.monthly_day}"
    return rtype


@tool(
    name="list_routines",
    description=(
        "List the user's routines — recurring or one-off activities that "
        "are NOT tied to a project (distinct from project tasks). Returns "
        "id, title, the recurrence rule, start/end dates, effort, optional "
        "time_of_day (clock time, null = all-day), and whether the routine is "
        "archived. Set include_archived=false to hide archived routines."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "include_archived": {"type": "boolean", "default": True},
        },
        "additionalProperties": False,
    },
)
def _list_routines(user_id: uuid.UUID, args: dict) -> dict:
    rows = routines_svc.list_routines(
        user_id, include_archived=bool(args.get("include_archived", True))
    )
    return {
        "routines": [
            {
                "id": str(r.id),
                "title": r.title,
                "description": short_text(r.description),
                "recurrence": _describe_recurrence(r),
                "recurrence_type": r.recurrence_type,
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "effort_hours": r.effort_hours,
                "time_of_day": (
                    r.time_of_day.isoformat() if r.time_of_day else None
                ),
                "archived": r.archived,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@tool(
    name="list_routine_occurrences",
    description=(
        "List routine occurrences in a date window: what each (non-archived) "
        "routine is scheduled for and whether it has been completed. Use for "
        "'what routines are due this week' or 'did I keep up with X'. "
        "`days_ahead` looks forward from today, `days_back` looks backward."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "minimum": 0,
                "maximum": 365,
                "default": 14,
            },
            "days_back": {
                "type": "integer",
                "minimum": 0,
                "maximum": 365,
                "default": 0,
            },
        },
        "additionalProperties": False,
    },
)
def _list_routine_occurrences(user_id: uuid.UUID, args: dict) -> dict:
    today = timezone.localdate()
    from_date = today - dt.timedelta(days=int(args.get("days_back") or 0))
    to_date = today + dt.timedelta(days=int(args.get("days_ahead") or 14))

    routines = {
        r.id: r
        for r in routines_svc.list_routines(user_id, include_archived=False)
    }
    items = routines_svc.list_due_in_range(user_id, from_date, to_date)
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "occurrences": [
            {
                "routine_id": str(it["routine_id"]),
                "title": (
                    routines[it["routine_id"]].title
                    if it["routine_id"] in routines
                    else ""
                ),
                "scheduled_date": it["scheduled_date"].isoformat(),
                "completed": it["occurrence_id"] is not None,
            }
            for it in items
        ],
        "count": len(items),
    }

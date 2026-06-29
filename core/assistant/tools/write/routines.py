"""Write tools — routines."""

from __future__ import annotations

import uuid

from core.services import routines as routines_svc
from core.services.projects import NotFoundError

from .. import tool
from ..datetime_utils import _parse_date, _parse_time

_RECURRENCE = ["once", "weekly_days", "every_n", "monthly_day"]
_INTERVAL_UNIT = ["days", "weeks", "months"]

_ROUTINE_RULE_PROPS = {
    "recurrence_type": {"type": "string", "enum": _RECURRENCE},
    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
    "end_date": {"type": "string", "description": "YYYY-MM-DD (optional)"},
    "weekdays": {
        "type": "array",
        "items": {"type": "integer", "minimum": 0, "maximum": 6},
        "description": "For weekly_days only: 0=Monday .. 6=Sunday.",
    },
    "interval_n": {
        "type": "integer",
        "minimum": 1,
        "description": "For every_n only: units between occurrences.",
    },
    "interval_unit": {
        "type": "string",
        "enum": _INTERVAL_UNIT,
        "description": "For every_n only.",
    },
    "monthly_day": {
        "type": "integer",
        "minimum": 1,
        "maximum": 31,
        "description": "For monthly_day only: day of the month.",
    },
    "effort_hours": {"type": "number", "minimum": 0},
    "time_of_day": {
        "type": "string",
        "description": (
            "Optional clock time 'HH:MM' (24h) for the routine; omit for "
            "all-day. When set, occurrences land on the calendar's hourly day view."
        ),
    },
    "duration_minutes": {"type": "integer", "minimum": 0},
}



@tool(
    name="create_routine",
    description=(
        "Create a routine — a recurring (or one-off) activity. Required: "
        "title, recurrence_type, start_date. Optionally link it to a project "
        "with `project_id` (omit for a standalone routine). The recurrence_type "
        "drives which extra fields apply: weekly_days needs `weekdays`; every_n "
        "needs `interval_n` + `interval_unit`; monthly_day needs `monthly_day`; "
        "once needs nothing more."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string"},
            "project_id": {
                "type": "string",
                "format": "uuid",
                "description": "Link the routine to a project (optional).",
            },
            **_ROUTINE_RULE_PROPS,
        },
        "required": ["title", "recurrence_type", "start_date"],
        "additionalProperties": False,
    },
)
def _create_routine(user_id: uuid.UUID, args: dict) -> dict:
    try:
        r = routines_svc.create_routine(
            user_id,
            title=args["title"],
            description=args.get("description", ""),
            recurrence_type=args["recurrence_type"],
            start_date=_parse_date(args["start_date"]),
            end_date=_parse_date(args.get("end_date")),
            weekdays=args.get("weekdays"),
            interval_n=args.get("interval_n"),
            interval_unit=args.get("interval_unit"),
            monthly_day=args.get("monthly_day"),
            effort_hours=args.get("effort_hours"),
            project_id=args.get("project_id"),
            time_of_day=_parse_time(args.get("time_of_day")),
            duration_minutes=args.get("duration_minutes"),
        )
    except NotFoundError:
        return {"error": "Project not found"}
    return {
        "ok": True,
        "id": str(r.id),
        "title": r.title,
        "recurrence_type": r.recurrence_type,
        "project_id": str(r.project_id) if r.project_id else None,
    }


@tool(
    name="update_routine",
    description=(
        "Update a routine. `id` is required; omitted fields keep their "
        "current value. If you change `recurrence_type`, also pass the "
        "fields the new type needs. Use `clear_end_date` to unset the end "
        "date. Use `project_id` to link/change the project, or "
        "`clear_project` to unlink it."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string"},
            "project_id": {
                "type": "string",
                "format": "uuid",
                "description": "Link to a project (optional).",
            },
            "clear_project": {
                "type": "boolean",
                "description": "Set true to remove the project association.",
            },
            "clear_end_date": {"type": "boolean"},
            "clear_time_of_day": {"type": "boolean"},
            **_ROUTINE_RULE_PROPS,
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _update_routine(user_id: uuid.UUID, args: dict) -> dict:
    try:
        r = routines_svc.get_routine(user_id, args["id"])
    except NotFoundError:
        return {"error": "Routine not found"}

    if args.get("clear_end_date"):
        end_date = None
    elif "end_date" in args:
        end_date = _parse_date(args["end_date"])
    else:
        end_date = r.end_date

    start_date = (
        _parse_date(args["start_date"])
        if "start_date" in args
        else r.start_date
    )

    if args.get("clear_time_of_day"):
        time_of_day = None
    elif "time_of_day" in args:
        time_of_day = _parse_time(args["time_of_day"])
    else:
        time_of_day = r.time_of_day

    project_id = None if args.get("clear_project") else (
        args.get("project_id") or r.project_id
    )

    try:
        updated = routines_svc.update_routine(
            user_id,
            r.id,
            title=args.get("title", r.title),
            description=args.get("description", r.description),
            recurrence_type=args.get("recurrence_type") or r.recurrence_type,
            start_date=start_date,
            end_date=end_date,
            weekdays=args["weekdays"] if "weekdays" in args else r.weekdays,
            interval_n=args["interval_n"] if "interval_n" in args else r.interval_n,
            interval_unit=(
                args["interval_unit"]
                if "interval_unit" in args
                else r.interval_unit
            ),
            monthly_day=(
                args["monthly_day"] if "monthly_day" in args else r.monthly_day
            ),
            effort_hours=(
                args["effort_hours"]
                if "effort_hours" in args
                else r.effort_hours
            ),
            project_id=project_id,
            time_of_day=time_of_day,
            duration_minutes=(
                args["duration_minutes"]
                if "duration_minutes" in args
                else r.duration_minutes
            ),
        )
    except NotFoundError:
        return {"error": "Project not found"}
    return {
        "ok": True,
        "id": str(updated.id),
        "title": updated.title,
        "recurrence_type": updated.recurrence_type,
        "project_id": str(updated.project_id) if updated.project_id else None,
    }


@tool(
    name="delete_routine",
    description=(
        "Permanently delete a routine and its completion history. "
        "Irreversible. Do NOT call this until the user has explicitly "
        "confirmed; set `confirm` to true only then."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "confirm": {
                "type": "boolean",
                "description": "Must be true; set only after the user confirms.",
            },
        },
        "required": ["id", "confirm"],
        "additionalProperties": False,
    },
)
def _delete_routine(user_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {
            "needs_confirmation": True,
            "message": "Name the routine and ask the user to confirm before "
            "deleting it.",
        }
    try:
        r = routines_svc.get_routine(user_id, args["id"])
    except NotFoundError:
        return {"error": "Routine not found"}
    title = r.title
    routines_svc.delete_routine(user_id, r.id)
    return {"ok": True, "deleted": "routine", "title": title}



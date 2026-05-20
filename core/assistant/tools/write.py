"""Read-write tools — the Pro tier.

Every tool here is `plan_required="pro"`, so it is invisible to free-plan
users (see `schemas_for_anthropic` / `call` in this package's __init__).
Handlers delegate to `core.services.*` so validation and activity logging
stay shared with the GraphQL resolvers.

The service-layer `update_*` functions are full-replace (omitted fields
reset to their defaults), so the update tools here fetch the current row
first and merge the caller's changes onto it — a tool can pass just the
fields it wants to change.

Destructive tools (`delete_*`) require an explicit `confirm: true`. If it
is missing they return a `needs_confirmation` payload instead of deleting,
so the model is forced to round-trip a confirmation through the user.
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from core.notifications.models import NotificationSettings
from core.services import activities as activities_svc
from core.services import categories as categories_svc
from core.services import ideas as ideas_svc
from core.services import notes as notes_svc
from core.services import projects as projects_svc
from core.services import routines as routines_svc
from core.services import tasks as tasks_svc
from core.services.projects import NotFoundError

from . import tool


# ---------- Shared schema fragments ----------

_STATUS = ["idea", "active", "stalled", "paused", "launched", "archived"]
_PRIORITY = ["critical", "high", "medium", "low"]
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
}


# ---------- Date helpers ----------

_DEFAULT_TZ = "America/Mexico_City"


def _parse_date(value) -> dt.date | None:
    """'YYYY-MM-DD' (or longer ISO) -> date; empty -> None."""
    if value in (None, ""):
        return None
    return dt.date.fromisoformat(str(value)[:10])


def _user_timezone(user_id: uuid.UUID) -> ZoneInfo | None:
    """The user's configured timezone, or None if zone data is unavailable."""
    row = (
        NotificationSettings.objects.filter(user_id=user_id)
        .only("timezone")
        .first()
    )
    name = (getattr(row, "timezone", "") or "").strip() or _DEFAULT_TZ
    for candidate in (name, _DEFAULT_TZ):
        try:
            return ZoneInfo(candidate)
        except Exception:  # noqa: BLE001 — bad/unknown zone, try the fallback
            continue
    return None


def _parse_due_dt(value, user_id: uuid.UUID) -> dt.datetime | None:
    """'YYYY-MM-DD' -> aware datetime at midnight of that day; empty -> None.

    Project/Task `due_date` columns are DateTimeFields. The rest of the app
    stores a picked date as midnight of the user's LOCAL day; anchoring it
    anywhere else (e.g. midnight UTC) makes the date render as the previous
    day for users west of UTC. So we anchor to midnight in the user's
    timezone. If zone data can't be loaded, noon UTC is a safe fallback —
    it lands on the intended calendar day in every realistic timezone.
    """
    d = _parse_date(value)
    if d is None:
        return None
    tz = _user_timezone(user_id)
    if tz is not None:
        return dt.datetime.combine(d, dt.time.min, tzinfo=tz)
    return dt.datetime.combine(d, dt.time(12, 0), tzinfo=dt.timezone.utc)


# ================= Projects =================


@tool(
    name="create_project",
    description=(
        "Create a new project. Only `name` is required. `due_date` is a "
        "'YYYY-MM-DD' string. Returns the new project's id. Briefly restate "
        "what you will create before calling."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string"},
            "why": {"type": "string"},
            "next_step": {"type": "string"},
            "status": {"type": "string", "enum": _STATUS},
            "priority": {"type": "string", "enum": _PRIORITY},
            "category_id": {"type": "string", "format": "uuid"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
)
def _create_project(user_id: uuid.UUID, args: dict) -> dict:
    p = projects_svc.create_project(
        user_id,
        name=args["name"],
        description=args.get("description", ""),
        why=args.get("why", ""),
        next_step=args.get("next_step", ""),
        status=args.get("status") or "idea",
        priority=args.get("priority") or "medium",
        category_id=args.get("category_id"),
        due_date=_parse_due_dt(args.get("due_date"), user_id),
    )
    return {"ok": True, "id": str(p.id), "name": p.name, "status": p.status}


@tool(
    name="update_project",
    description=(
        "Update an existing project. `id` is required; pass only the fields "
        "to change — omitted fields keep their current value. Use "
        "`clear_category` / `clear_due_date` to unset those."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string"},
            "why": {"type": "string"},
            "next_step": {"type": "string"},
            "status": {"type": "string", "enum": _STATUS},
            "priority": {"type": "string", "enum": _PRIORITY},
            "category_id": {"type": "string", "format": "uuid"},
            "clear_category": {"type": "boolean"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD"},
            "clear_due_date": {"type": "boolean"},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _update_project(user_id: uuid.UUID, args: dict) -> dict:
    try:
        p = projects_svc.get_project(user_id, args["id"])
    except NotFoundError:
        return {"error": "Project not found"}

    if args.get("clear_due_date"):
        due = None
    elif "due_date" in args:
        due = _parse_due_dt(args["due_date"], user_id)
    else:
        due = p.due_date

    category_id = None if args.get("clear_category") else (
        args.get("category_id") or p.category_id
    )

    updated = projects_svc.update_project(
        user_id,
        p.id,
        name=args.get("name", p.name),
        description=args.get("description", p.description),
        why=args.get("why", p.why),
        next_step=args.get("next_step", p.next_step),
        status=args.get("status") or p.status,
        priority=args.get("priority") or p.priority,
        category_id=category_id,
        clear_category=bool(args.get("clear_category")),
        due_date=due,
    )
    return {
        "ok": True,
        "id": str(updated.id),
        "name": updated.name,
        "status": updated.status,
        "priority": updated.priority,
    }


@tool(
    name="delete_project",
    description=(
        "Permanently delete a project AND all of its tasks. Irreversible. "
        "Do NOT call this until the user has explicitly confirmed this exact "
        "deletion in conversation; set `confirm` to true only then."
    ),
    plan_required="pro",
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
def _delete_project(user_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {
            "needs_confirmation": True,
            "message": "Describe the project and ask the user to confirm "
            "before deleting it.",
        }
    try:
        p = projects_svc.get_project(user_id, args["id"])
    except NotFoundError:
        return {"error": "Project not found"}
    name = p.name
    projects_svc.delete_project(user_id, p.id)
    return {"ok": True, "deleted": "project", "name": name}


# ================= Tasks =================


@tool(
    name="create_task",
    description=(
        "Create a task. `title` is required. `project_id` links it to a "
        "project (omit for a standalone task). `due_date` is 'YYYY-MM-DD'. "
        "`effort_hours` is an estimate. When structuring a project, call "
        "this once per task."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "project_id": {"type": "string", "format": "uuid"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD"},
            "effort_hours": {"type": "number", "minimum": 0},
            "done": {"type": "boolean"},
        },
        "required": ["title"],
        "additionalProperties": False,
    },
)
def _create_task(user_id: uuid.UUID, args: dict) -> dict:
    try:
        t = tasks_svc.create_task(
            user_id,
            title=args["title"],
            project_id=args.get("project_id"),
            due_date=_parse_due_dt(args.get("due_date"), user_id),
            done=bool(args.get("done", False)),
            effort_hours=args.get("effort_hours"),
        )
    except NotFoundError:
        return {"error": "Project not found"}
    return {
        "ok": True,
        "id": str(t.id),
        "title": t.title,
        "project_id": str(t.project_id) if t.project_id else None,
    }


@tool(
    name="update_task",
    description=(
        "Update a task. `id` is required; omitted fields keep their value. "
        "Set `done` to mark it complete/incomplete. Use `clear_due_date` / "
        "`clear_project` to unset those. `due_date` is 'YYYY-MM-DD'."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "project_id": {"type": "string", "format": "uuid"},
            "clear_project": {"type": "boolean"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD"},
            "clear_due_date": {"type": "boolean"},
            "effort_hours": {"type": "number", "minimum": 0},
            "done": {"type": "boolean"},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _update_task(user_id: uuid.UUID, args: dict) -> dict:
    try:
        t = tasks_svc.get_task(user_id, args["id"])
    except NotFoundError:
        return {"error": "Task not found"}

    if args.get("clear_due_date"):
        due = None
    elif "due_date" in args:
        due = _parse_due_dt(args["due_date"], user_id)
    else:
        due = t.due_date

    project_id = None if args.get("clear_project") else (
        args.get("project_id") or t.project_id
    )

    try:
        updated = tasks_svc.update_task(
            user_id,
            t.id,
            title=args.get("title", t.title),
            project_id=project_id,
            due_date=due,
            done=bool(args["done"]) if "done" in args else t.done,
            effort_hours=(
                args["effort_hours"]
                if "effort_hours" in args
                else t.effort_hours
            ),
        )
    except NotFoundError:
        return {"error": "Project not found"}
    return {
        "ok": True,
        "id": str(updated.id),
        "title": updated.title,
        "done": updated.done,
    }


@tool(
    name="delete_task",
    description=(
        "Permanently delete a task. Irreversible. Do NOT call this until the "
        "user has explicitly confirmed; set `confirm` to true only then."
    ),
    plan_required="pro",
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
def _delete_task(user_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {
            "needs_confirmation": True,
            "message": "Name the task and ask the user to confirm before "
            "deleting it.",
        }
    try:
        t = tasks_svc.get_task(user_id, args["id"])
    except NotFoundError:
        return {"error": "Task not found"}
    title = t.title
    tasks_svc.delete_task(user_id, t.id)
    return {"ok": True, "deleted": "task", "title": title}


# ================= Routines =================


@tool(
    name="create_routine",
    description=(
        "Create a routine — a recurring (or one-off) activity NOT tied to a "
        "project. Required: title, recurrence_type, start_date. The "
        "recurrence_type drives which extra fields apply: weekly_days needs "
        "`weekdays`; every_n needs `interval_n` + `interval_unit`; "
        "monthly_day needs `monthly_day`; once needs nothing more."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string"},
            **_ROUTINE_RULE_PROPS,
        },
        "required": ["title", "recurrence_type", "start_date"],
        "additionalProperties": False,
    },
)
def _create_routine(user_id: uuid.UUID, args: dict) -> dict:
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
    )
    return {
        "ok": True,
        "id": str(r.id),
        "title": r.title,
        "recurrence_type": r.recurrence_type,
    }


@tool(
    name="update_routine",
    description=(
        "Update a routine. `id` is required; omitted fields keep their "
        "current value. If you change `recurrence_type`, also pass the "
        "fields the new type needs. Use `clear_end_date` to unset the end."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string"},
            "clear_end_date": {"type": "boolean"},
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
    )
    return {
        "ok": True,
        "id": str(updated.id),
        "title": updated.title,
        "recurrence_type": updated.recurrence_type,
    }


@tool(
    name="delete_routine",
    description=(
        "Permanently delete a routine and its completion history. "
        "Irreversible. Do NOT call this until the user has explicitly "
        "confirmed; set `confirm` to true only then."
    ),
    plan_required="pro",
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


# ================= Project notes =================


@tool(
    name="create_note",
    description=(
        "Create a project note — free-form notes attached to a project. "
        "This is distinct from a project 'update' (an activity-log entry). "
        "Requires `project_id` and `body`; `title` is optional."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "maxLength": 255},
            "body": {"type": "string", "minLength": 1},
        },
        "required": ["project_id", "body"],
        "additionalProperties": False,
    },
)
def _create_note(user_id: uuid.UUID, args: dict) -> dict:
    try:
        n = notes_svc.create_note(
            user_id,
            project_id=args["project_id"],
            title=args.get("title", ""),
            body=args["body"],
        )
    except NotFoundError:
        return {"error": "Project not found"}
    return {
        "ok": True,
        "id": str(n.id),
        "title": n.title,
        "project_id": str(n.project_id),
    }


@tool(
    name="update_note",
    description=(
        "Update a project note. `id` is required; omitted fields keep their "
        "current value."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "maxLength": 255},
            "body": {"type": "string"},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _update_note(user_id: uuid.UUID, args: dict) -> dict:
    try:
        n = notes_svc.get_note(user_id, args["id"])
        updated = notes_svc.update_note(
            user_id,
            n.id,
            title=args.get("title", n.title),
            body=args.get("body", n.body),
        )
    except NotFoundError:
        return {"error": "Note not found"}
    return {"ok": True, "id": str(updated.id), "title": updated.title}


@tool(
    name="delete_note",
    description=(
        "Permanently delete a project note. Irreversible. Do NOT call this "
        "until the user has explicitly confirmed; set `confirm` to true only "
        "then."
    ),
    plan_required="pro",
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
def _delete_note(user_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {
            "needs_confirmation": True,
            "message": "Ask the user to confirm before deleting this note.",
        }
    try:
        n = notes_svc.get_note(user_id, args["id"])
    except NotFoundError:
        return {"error": "Note not found"}
    title = n.title or "(untitled)"
    notes_svc.delete_note(user_id, n.id)
    return {"ok": True, "deleted": "note", "title": title}


# ================= Project updates (activity log) =================


@tool(
    name="add_project_update",
    description=(
        "Add a progress update to a project — a timestamped entry in the "
        "project's activity log. Distinct from a project note. Requires "
        "`project_id` and `note` text."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "format": "uuid"},
            "note": {"type": "string", "minLength": 1},
        },
        "required": ["project_id", "note"],
        "additionalProperties": False,
    },
)
def _add_project_update(user_id: uuid.UUID, args: dict) -> dict:
    try:
        a = activities_svc.add_note(
            user_id, project_id=args["project_id"], note=args["note"]
        )
    except NotFoundError:
        return {"error": "Project not found"}
    return {"ok": True, "id": str(a.id), "project_id": str(args["project_id"])}


@tool(
    name="edit_project_update",
    description=(
        "Edit the text of an existing project update (activity-log entry). "
        "`id` is the update's id; `note` is the new text."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "note": {"type": "string", "minLength": 1},
        },
        "required": ["id", "note"],
        "additionalProperties": False,
    },
)
def _edit_project_update(user_id: uuid.UUID, args: dict) -> dict:
    try:
        a = activities_svc.update_note(user_id, args["id"], note=args["note"])
    except NotFoundError:
        return {"error": "Update not found"}
    return {"ok": True, "id": str(a.id)}


@tool(
    name="delete_project_update",
    description=(
        "Permanently delete a project update (activity-log entry). "
        "Irreversible. Do NOT call this until the user has explicitly "
        "confirmed; set `confirm` to true only then."
    ),
    plan_required="pro",
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
def _delete_project_update(user_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {
            "needs_confirmation": True,
            "message": "Ask the user to confirm before deleting this update.",
        }
    try:
        activities_svc.delete_note(user_id, args["id"])
    except NotFoundError:
        return {"error": "Update not found"}
    return {"ok": True, "deleted": "project_update"}


# ================= Ideas =================


@tool(
    name="create_idea",
    description=(
        "Create an idea — a lightweight thought not yet committed to as a "
        "project. `title` is required."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["title"],
        "additionalProperties": False,
    },
)
def _create_idea(user_id: uuid.UUID, args: dict) -> dict:
    i = ideas_svc.create_idea(
        user_id,
        title=args["title"],
        description=args.get("description", ""),
        why=args.get("why", ""),
    )
    return {"ok": True, "id": str(i.id), "title": i.title}


@tool(
    name="update_idea",
    description=(
        "Update an idea. `id` is required; omitted fields keep their "
        "current value."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _update_idea(user_id: uuid.UUID, args: dict) -> dict:
    try:
        i = ideas_svc.get_idea(user_id, args["id"])
        updated = ideas_svc.update_idea(
            user_id,
            i.id,
            title=args.get("title", i.title),
            description=args.get("description", i.description),
            why=args.get("why", i.why),
        )
    except NotFoundError:
        return {"error": "Idea not found"}
    return {"ok": True, "id": str(updated.id), "title": updated.title}


@tool(
    name="delete_idea",
    description=(
        "Permanently delete an idea. Irreversible. Do NOT call this until "
        "the user has explicitly confirmed; set `confirm` to true only then."
    ),
    plan_required="pro",
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
def _delete_idea(user_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {
            "needs_confirmation": True,
            "message": "Ask the user to confirm before deleting this idea.",
        }
    try:
        i = ideas_svc.get_idea(user_id, args["id"])
    except NotFoundError:
        return {"error": "Idea not found"}
    title = i.title
    ideas_svc.delete_idea(user_id, i.id)
    return {"ok": True, "deleted": "idea", "title": title}


@tool(
    name="promote_idea",
    description=(
        "Promote an idea into a full project: creates a new project from "
        "the idea's title/description/why and REMOVES the idea. Use when "
        "the user decides to commit to an idea."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _promote_idea(user_id: uuid.UUID, args: dict) -> dict:
    try:
        p = ideas_svc.promote_idea(user_id, args["id"])
    except NotFoundError:
        return {"error": "Idea not found"}
    return {"ok": True, "project_id": str(p.id), "name": p.name}


# ================= Categories =================


@tool(
    name="create_category",
    description=(
        "Create a project category. `name` is required; `color` is optional "
        "(defaults to 'emerald'). If a category with that name already "
        "exists it is returned unchanged."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 255},
            "color": {
                "type": "string",
                "description": "Color name, e.g. 'emerald', 'blue', 'amber'.",
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
)
def _create_category(user_id: uuid.UUID, args: dict) -> dict:
    c = categories_svc.create_category(
        user_id, name=args["name"], color=args.get("color") or "emerald"
    )
    return {"ok": True, "id": str(c.id), "name": c.name, "color": c.color}


@tool(
    name="update_category",
    description=(
        "Update a project category. `id` is required; omitted fields keep "
        "their current value."
    ),
    plan_required="pro",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string", "minLength": 1, "maxLength": 255},
            "color": {"type": "string"},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _update_category(user_id: uuid.UUID, args: dict) -> dict:
    try:
        c = categories_svc.get_category(user_id, args["id"])
        updated = categories_svc.update_category(
            user_id,
            c.id,
            name=args.get("name", c.name),
            color=args.get("color", ""),
        )
    except NotFoundError:
        return {"error": "Category not found"}
    return {
        "ok": True,
        "id": str(updated.id),
        "name": updated.name,
        "color": updated.color,
    }


@tool(
    name="delete_category",
    description=(
        "Permanently delete a project category; projects in it are left "
        "uncategorized. Irreversible. Do NOT call this until the user has "
        "explicitly confirmed; set `confirm` to true only then."
    ),
    plan_required="pro",
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
def _delete_category(user_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {
            "needs_confirmation": True,
            "message": "Ask the user to confirm before deleting this category.",
        }
    try:
        c = categories_svc.get_category(user_id, args["id"])
    except NotFoundError:
        return {"error": "Category not found"}
    name = c.name
    categories_svc.delete_category(user_id, c.id)
    return {"ok": True, "deleted": "category", "name": name}

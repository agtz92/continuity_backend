"""Write tools — tasks and task blockers."""

from __future__ import annotations

import uuid

from core.services import tasks as tasks_svc
from core.services.projects import NotFoundError

from .. import tool
from ..datetime_utils import _parse_due_dt, _parse_time


@tool(
    name="create_task",
    description=(
        "Create a task. `title` is required. `project_id` links it to a "
        "project (omit for a standalone task). `due_date` is 'YYYY-MM-DD'. "
        "`effort_hours` is an estimate. Optionally set `due_time` ('HH:MM', "
        "24-hour) to give the task a clock time — it then shows on the "
        "calendar's hourly day view; omit it for an all-day task. When "
        "structuring a project, call this once per task."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "project_id": {"type": "string", "format": "uuid"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD"},
            "due_time": {
                "type": "string",
                "description": "Optional clock time 'HH:MM' (24h). Omit for all-day.",
            },
            "effort_hours": {"type": "number", "minimum": 0},
            "duration_minutes": {"type": "integer", "minimum": 0},
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
            due_time=_parse_time(args.get("due_time")),
            duration_minutes=args.get("duration_minutes"),
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
        "`clear_project` / `clear_due_time` to unset those. `due_date` is "
        "'YYYY-MM-DD'; `due_time` is 'HH:MM' (24h)."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "project_id": {"type": "string", "format": "uuid"},
            "clear_project": {"type": "boolean"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD"},
            "clear_due_date": {"type": "boolean"},
            "due_time": {
                "type": "string",
                "description": "Clock time 'HH:MM' (24h).",
            },
            "clear_due_time": {"type": "boolean"},
            "effort_hours": {"type": "number", "minimum": 0},
            "duration_minutes": {"type": "integer", "minimum": 0},
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

    if args.get("clear_due_time"):
        due_time = None
    elif "due_time" in args:
        due_time = _parse_time(args["due_time"])
    else:
        due_time = t.due_time

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
            due_time=due_time,
            duration_minutes=(
                args["duration_minutes"]
                if "duration_minutes" in args
                else t.duration_minutes
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



# ================= Task Blockers =================


@tool(
    name="add_task_blocker",
    description=(
        "Mark a task as blocked. Provide either `blocking_task_id` (another "
        "task the user must complete first) OR `external_description` (a "
        "free-text external dependency like 'waiting on client approval') — "
        "but not both. Returns the new blocker's id. Circular dependencies "
        "are rejected automatically."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "blocked_task_id": {
                "type": "string",
                "format": "uuid",
                "description": "The task that is being blocked.",
            },
            "blocking_task_id": {
                "type": "string",
                "format": "uuid",
                "description": "The task that must be completed first (mutually exclusive with external_description).",
            },
            "external_description": {
                "type": "string",
                "maxLength": 500,
                "description": "Free-text external blocker (mutually exclusive with blocking_task_id).",
            },
        },
        "required": ["blocked_task_id"],
        "additionalProperties": False,
    },
)
def _add_task_blocker(user_id: uuid.UUID, args: dict) -> dict:
    has_task = bool(args.get("blocking_task_id"))
    has_ext = bool((args.get("external_description") or "").strip())
    if has_task == has_ext:
        return {
            "error": "Provide exactly one of blocking_task_id or external_description."
        }
    try:
        b = tasks_svc.add_task_blocker(
            user_id,
            args["blocked_task_id"],
            blocking_task_id=args.get("blocking_task_id"),
            external_description=args.get("external_description", ""),
        )
    except NotFoundError:
        return {"error": "Task not found"}
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True, "id": str(b.id)}


@tool(
    name="remove_task_blocker",
    description=(
        "Remove a blocker from a task. `id` is the blocker record's id "
        "(returned by add_task_blocker or visible in list_tasks output). "
        "Use when the user resolves a blocker manually."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "The blocker record id to remove.",
            },
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _remove_task_blocker(user_id: uuid.UUID, args: dict) -> dict:
    try:
        tasks_svc.remove_task_blocker(user_id, args["id"])
    except NotFoundError:
        return {"error": "Blocker not found"}
    return {"ok": True, "removed": "task_blocker"}



"""Write tools — projects."""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError

from core.services import projects as projects_svc
from core.services.projects import NotFoundError

from .. import tool
from ..datetime_utils import _parse_due_dt

_STATUS = ["idea", "active", "stalled", "paused", "launched", "killed", "archived"]
_PRIORITY = ["critical", "high", "medium", "low"]


@tool(
    name="create_project",
    description=(
        "Create a new project. Only `name` is required. `due_date` is a "
        "'YYYY-MM-DD' string. Returns the new project's id. Briefly restate "
        "what you will create before calling."
    ),
    plan_required="pro",
    mutates=True,
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
        "`clear_category` / `clear_due_date` to unset those. Setting status to "
        "'paused' REQUIRES paused_context + paused_next_action; 'killed' "
        "REQUIRES killed_reason + killed_learnings. Ask the user for these "
        "before calling if missing."
    ),
    plan_required="pro",
    mutates=True,
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
            "paused_context": {"type": "string"},
            "paused_next_action": {"type": "string"},
            "paused_blocker": {"type": "string"},
            "killed_reason": {"type": "string"},
            "killed_learnings": {"type": "string"},
            "killed_would_restart": {"type": "string"},
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

    try:
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
            paused_context=args.get("paused_context"),
            paused_next_action=args.get("paused_next_action"),
            paused_blocker=args.get("paused_blocker"),
            killed_reason=args.get("killed_reason"),
            killed_learnings=args.get("killed_learnings"),
            killed_would_restart=args.get("killed_would_restart"),
        )
    except ValidationError as e:
        # Surface so the model asks the user for the missing closure notes.
        msg = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
        return {"error": msg}
    return {
        "ok": True,
        "id": str(updated.id),
        "name": updated.name,
        "status": updated.status,
        "priority": updated.priority,
    }


@tool(
    name="set_project_priority",
    description=(
        "Set ONLY the priority of an existing project. Narrow-scope tool: it "
        "cannot rename, change status, dates, category or any other field — "
        "use `update_project` for those. `id` and `priority` are required."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "priority": {"type": "string", "enum": _PRIORITY},
        },
        "required": ["id", "priority"],
        "additionalProperties": False,
    },
)
def _set_project_priority(user_id: uuid.UUID, args: dict) -> dict:
    """Change a project's priority and nothing else.

    Mirrors `_update_project`'s field-preservation pattern but only the
    `priority` field is taken from `args`; every other field keeps its
    current value. The connector exposes this on the basic/free tier
    (via `core/mcp/policy.py`) while the full `update_project` bundle
    stays gated to pro+.
    """
    try:
        p = projects_svc.get_project(user_id, args["id"])
    except NotFoundError:
        return {"error": "Project not found"}

    updated = projects_svc.update_project(
        user_id,
        p.id,
        name=p.name,
        description=p.description,
        why=p.why,
        next_step=p.next_step,
        status=p.status,
        priority=args["priority"],
        category_id=p.category_id,
        due_date=p.due_date,
    )
    return {
        "ok": True,
        "id": str(updated.id),
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



"""Write tools — project notes and project updates (activity log)."""

from __future__ import annotations

import uuid

from core.services import activities as activities_svc
from core.services import notes as notes_svc
from core.services.projects import NotFoundError

from .. import tool


@tool(
    name="create_note",
    description=(
        "Create a project note — free-form notes attached to a project. "
        "This is distinct from a project 'update' (an activity-log entry). "
        "Requires `project_id` and `body`; `title` is optional."
    ),
    plan_required="pro",
    mutates=True,
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
    mutates=True,
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
    mutates=True,
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
    mutates=True,
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



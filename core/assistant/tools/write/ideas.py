"""Write tools — ideas."""

from __future__ import annotations

import uuid

from core.services import ideas as ideas_svc
from core.services.projects import NotFoundError

from .. import tool


@tool(
    name="create_idea",
    description=(
        "Create an idea — a lightweight thought not yet committed to as a "
        "project. `title` is required."
    ),
    plan_required="pro",
    mutates=True,
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
    mutates=True,
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
    mutates=True,
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



"""Write tools — categories."""

from __future__ import annotations

import uuid

from core.services import categories as categories_svc
from core.services.projects import NotFoundError

from .. import tool


@tool(
    name="create_category",
    description=(
        "Create a project category. `name` is required; `color` is optional "
        "(defaults to 'emerald'). If a category with that name already "
        "exists it is returned unchanged."
    ),
    plan_required="pro",
    mutates=True,
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
    mutates=True,
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



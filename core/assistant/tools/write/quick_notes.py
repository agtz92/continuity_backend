"""Write tools — Quick Notes (Notion-style notebook notes) and sections."""

from __future__ import annotations

import uuid

from core.services import quick_notes as quick_notes_svc
from core.services.projects import NotFoundError

from .. import tool


@tool(
    name="create_quick_note",
    description=(
        "Create a Quick Note (notebook-style note with sections). Optional: "
        "`category_id`, `project_id` (to link it), `pinned`. Add content with "
        "`add_note_section`."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 255},
            "category_id": {"type": "string", "format": "uuid"},
            "project_id": {"type": "string", "format": "uuid"},
            "pinned": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
)
def _create_quick_note(user_id: uuid.UUID, args: dict) -> dict:
    n = quick_notes_svc.create_quick_note(
        user_id,
        title=args.get("title", ""),
        category_id=args.get("category_id"),
        project_id=args.get("project_id"),
        pinned=bool(args.get("pinned", False)),
    )
    return {"ok": True, "id": str(n.id), "title": n.title}


@tool(
    name="update_quick_note",
    description=(
        "Update a Quick Note's metadata: `title`, `category_id`, `project_id`, "
        "`pinned`. Does not touch sections — use the section tools for content."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "maxLength": 255},
            "category_id": {"type": "string", "format": "uuid"},
            "project_id": {"type": "string", "format": "uuid"},
            "pinned": {"type": "boolean"},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _update_quick_note(user_id: uuid.UUID, args: dict) -> dict:
    try:
        n = quick_notes_svc.update_quick_note(
            user_id,
            args["id"],
            title=args.get("title", ""),
            category_id=args.get("category_id"),
            project_id=args.get("project_id"),
            pinned=bool(args.get("pinned", False)),
        )
    except NotFoundError as e:
        return {"error": str(e)}
    return {"ok": True, "id": str(n.id), "title": n.title}


@tool(
    name="set_quick_note_pinned",
    description="Pin or unpin a Quick Note (floats it to the top of the list).",
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "pinned": {"type": "boolean"},
        },
        "required": ["id", "pinned"],
        "additionalProperties": False,
    },
)
def _set_quick_note_pinned(user_id: uuid.UUID, args: dict) -> dict:
    try:
        n = quick_notes_svc.set_pin(user_id, args["id"], bool(args["pinned"]))
    except NotFoundError as e:
        return {"error": str(e)}
    return {"ok": True, "id": str(n.id), "pinned": n.pinned}


@tool(
    name="delete_quick_note",
    description=(
        "Permanently delete a Quick Note AND all its sections. Irreversible — "
        "confirm with the user first."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "string", "format": "uuid"}},
        "required": ["id"],
        "additionalProperties": False,
    },
)
def _delete_quick_note(user_id: uuid.UUID, args: dict) -> dict:
    try:
        n = quick_notes_svc.get_quick_note(user_id, args["id"])
    except NotFoundError:
        return {"error": "Quick note not found"}
    title = n.title
    quick_notes_svc.delete_quick_note(user_id, n.id)
    return {"ok": True, "deleted": "quick_note", "title": title}


@tool(
    name="add_note_section",
    description=(
        "Add a collapsible section (heading + markdown body) to a Quick Note. "
        "Appended at the end unless `position` is given."
    ),
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "format": "uuid"},
            "heading": {"type": "string"},
            "body": {"type": "string"},
            "position": {"type": "integer", "minimum": 0},
            "collapsed": {"type": "boolean"},
        },
        "required": ["note_id"],
        "additionalProperties": False,
    },
)
def _add_note_section(user_id: uuid.UUID, args: dict) -> dict:
    try:
        s = quick_notes_svc.add_section(
            user_id,
            args["note_id"],
            heading=args.get("heading", ""),
            body=args.get("body", ""),
            position=args.get("position"),
            collapsed=bool(args.get("collapsed", False)),
        )
    except NotFoundError as e:
        return {"error": str(e)}
    return {"ok": True, "id": str(s.id), "note_id": str(s.note_id)}


@tool(
    name="update_note_section",
    description="Update a Quick Note section's `heading`, `body`, or `collapsed` state.",
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {
            "section_id": {"type": "string", "format": "uuid"},
            "heading": {"type": "string"},
            "body": {"type": "string"},
            "collapsed": {"type": "boolean"},
        },
        "required": ["section_id"],
        "additionalProperties": False,
    },
)
def _update_note_section(user_id: uuid.UUID, args: dict) -> dict:
    try:
        s = quick_notes_svc.update_section(
            user_id,
            args["section_id"],
            heading=args.get("heading", ""),
            body=args.get("body", ""),
            collapsed=args.get("collapsed"),
        )
    except NotFoundError as e:
        return {"error": str(e)}
    return {"ok": True, "id": str(s.id)}


@tool(
    name="delete_note_section",
    description="Delete a section from a Quick Note. Irreversible.",
    plan_required="pro",
    mutates=True,
    input_schema={
        "type": "object",
        "properties": {"section_id": {"type": "string", "format": "uuid"}},
        "required": ["section_id"],
        "additionalProperties": False,
    },
)
def _delete_note_section(user_id: uuid.UUID, args: dict) -> dict:
    quick_notes_svc.delete_section(user_id, args["section_id"])
    return {"ok": True, "deleted": "note_section"}

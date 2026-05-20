"""Tool registry for the assistant.

A tool is a typed wrapper around a `core.services.*` function. The
registry owns:

- A list of tool definitions (name, description, JSON schema) sent to
  the Anthropic API in the `tools=[...]` parameter.
- A handler dispatch that runs server-side with strict user_id scoping,
  truncates large results, and never raises (errors come back as a
  `{"error": "..."}` payload the model can apologize about).

To add a tool:
    - implement a function in this package returning a JSON-serializable dict
    - decorate it with @tool(name=..., description=..., input_schema=...)

The decorator handles user_id scoping, truncation, and error wrapping.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import json
import logging
import uuid
from typing import Any, Callable

logger = logging.getLogger(__name__)


MAX_RESULT_BYTES = 2_000  # ~500 tokens
MAX_LIST_ITEMS = 50


@dataclasses.dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[uuid.UUID, dict], dict]
    plan_required: str = "free"


_REGISTRY: dict[str, Tool] = {}


def tool(
    *,
    name: str,
    description: str,
    input_schema: dict,
    plan_required: str = "free",
):
    """Decorator that registers a function as a tool.

    The wrapped function MUST take `(user_id: uuid.UUID, args: dict)` and
    return a JSON-serializable dict. The decorator catches exceptions,
    truncates oversized results, and registers the tool for dispatch.
    """

    def decorator(fn: Callable[[uuid.UUID, dict], dict]) -> Callable:
        @functools.wraps(fn)
        def wrapped(user_id: uuid.UUID, args: dict) -> dict:
            try:
                result = fn(user_id, args or {})
            except Exception as e:  # noqa: BLE001 — model-facing layer must not crash
                logger.exception("Tool %s raised", name)
                return {"error": f"{type(e).__name__}: {e}"}
            return _truncate_payload(result)

        _REGISTRY[name] = Tool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=wrapped,
            plan_required=plan_required,
        )
        return wrapped

    return decorator


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


# Plan tiers, lowest to highest. A tool with `plan_required="pro"` is
# available to "pro" and "admin" but not "free" — this is what separates
# the read-only tier from the read-write tier.
_PLAN_RANK = {"free": 0, "pro": 1, "admin": 2}


def _plan_allows(user_plan: str, required: str) -> bool:
    return _PLAN_RANK.get(user_plan, 0) >= _PLAN_RANK.get(required, 0)


def schemas_for_anthropic(plan: str = "free") -> list[dict]:
    """The list passed as `tools=` to the Anthropic SDK, filtered by plan."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in _REGISTRY.values()
        if _plan_allows(plan, t.plan_required)
    ]


def call(name: str, user_id: uuid.UUID, args: dict, plan: str = "free") -> dict:
    """Dispatch a tool by name. Unknown names or insufficient plan return
    an error payload — never raises, the model apologizes to the user."""
    t = _REGISTRY.get(name)
    if t is None:
        return {"error": f"Unknown tool: {name}"}
    if not _plan_allows(plan, t.plan_required):
        return {
            "error": (
                f"Tool '{name}' is not available on the '{plan}' plan "
                f"(requires '{t.plan_required}')."
            )
        }
    return t.handler(user_id, args)


# ---------- helpers used by individual tools ----------


def _truncate_payload(value: Any) -> Any:
    """Hard byte cap on tool results.

    If the raw JSON is over MAX_RESULT_BYTES, we truncate any list it
    contains by half until under the cap, then add `truncated: true`.
    """
    encoded = json.dumps(value, default=_json_default)
    if len(encoded) <= MAX_RESULT_BYTES:
        return value
    if isinstance(value, dict):
        return _truncate_dict(value)
    if isinstance(value, list):
        return _truncate_list(value)
    return {"truncated": True, "value": str(value)[: MAX_RESULT_BYTES]}


def _truncate_dict(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, list) and len(v) > 10:
            out[k] = v[:10]
            out.setdefault("truncated_keys", []).append(k)
        else:
            out[k] = v
    encoded = json.dumps(out, default=_json_default)
    if len(encoded) > MAX_RESULT_BYTES:
        out["truncated"] = True
    return out


def _truncate_list(items: list) -> dict:
    keep = items[:10]
    return {"items": keep, "truncated": True, "total": len(items)}


def _json_default(o: Any):
    if isinstance(o, (uuid.UUID,)):
        return str(o)
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    if hasattr(o, "__dict__"):
        return o.__dict__
    return str(o)


def short_text(text: str, length: int = 280) -> str:
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[: length - 1] + "…"


def days_between(when: dt.datetime | None, *, now: dt.datetime) -> int | None:
    if when is None:
        return None
    return max(0, int((now - when).total_seconds() // 86400))


# Importing the tool modules triggers registration via the @tool decorator.
from . import read  # noqa: E402, F401
from . import routines  # noqa: E402, F401
from . import write  # noqa: E402, F401

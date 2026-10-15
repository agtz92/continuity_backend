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

#: Re-exported so every write module can write `plan_required=WRITE_TIER`
#: instead of hard-coding a plan name 32 times. The value lives in
#: `core.assistant.tiers`; moving writes between tiers is that one line.
from ..tiers import WRITE_TIER  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


#: Byte cap on one tool result (~4-5k tokens). Big enough for a full page
#: of 50 tasks; the old 2 KB cap silently cut lists to 10 and the model
#: then reported partial lists as totals.
MAX_RESULT_BYTES = 20_000
MAX_LIST_ITEMS = 50


@dataclasses.dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[uuid.UUID, dict], dict]
    plan_required: str = "free"
    # True for tools that create/modify/delete user data. Read-only tools
    # leave this False. The MCP connector's policy layer (core/mcp/policy.py)
    # uses this to gate writes per plan independently of `plan_required`.
    mutates: bool = False


_REGISTRY: dict[str, Tool] = {}


def tool(
    *,
    name: str,
    description: str,
    input_schema: dict,
    plan_required: str = "free",
    mutates: bool = False,
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
            mutates=mutates,
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
_PLAN_RANK = {"free": 0, "pro": 1, "studio": 2, "admin": 3}


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


def paginate(qs, args: dict, *, default_limit: int = 20) -> tuple[list, dict]:
    """Slice a queryset (or list) by the model's `offset` / `limit` args.

    Returns `(rows, meta)` where meta is `{total, offset, returned,
    next_offset}` — `next_offset` is None once the last page is reached, so
    the model knows whether it has seen everything before claiming totals.
    """
    limit = max(1, min(int(args.get("limit") or default_limit), MAX_LIST_ITEMS))
    offset = max(0, int(args.get("offset") or 0))
    total = qs.count() if hasattr(qs, "count") and not isinstance(qs, list) else len(qs)
    rows = list(qs[offset : offset + limit])
    return rows, _page_meta(total, offset, len(rows))


def _page_meta(total: int, offset: int, returned: int) -> dict:
    end = offset + returned
    return {
        "total": total,
        "offset": offset,
        "returned": returned,
        "next_offset": end if end < total else None,
    }


def _encoded_len(value: Any) -> int:
    return len(json.dumps(value, default=_json_default))


def _truncate_payload(value: Any) -> Any:
    """Hard byte cap on tool results.

    Under MAX_RESULT_BYTES the result passes through untouched. Over it,
    the largest list is trimmed to as many items as fit (not a blind cut),
    and a paginated payload's `returned` / `next_offset` are rewritten so
    the model can fetch the rest with `offset`.
    """
    if _encoded_len(value) <= MAX_RESULT_BYTES:
        return value
    if isinstance(value, dict):
        return _truncate_dict(value)
    if isinstance(value, list):
        return _truncate_dict({"items": value, **_page_meta(len(value), 0, len(value))})
    return {"truncated": True, "value": str(value)[:MAX_RESULT_BYTES]}


def _truncate_dict(d: dict) -> dict:
    out = dict(d)
    list_keys = sorted(
        (k for k, v in out.items() if isinstance(v, list) and v),
        key=lambda k: _encoded_len(out[k]),
        reverse=True,
    )
    for k in list_keys:
        if _encoded_len(out) <= MAX_RESULT_BYTES:
            break
        full = out[k]
        # Largest prefix that fits (binary search; keep at least one item).
        lo, hi = 1, len(full)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            out[k] = full[:mid]
            if _encoded_len(out) <= MAX_RESULT_BYTES:
                lo = mid
            else:
                hi = mid - 1
        out[k] = full[:lo]
        if lo < len(full):
            out.setdefault("truncated_keys", []).append(k)
            if "next_offset" in out and "returned" in out:
                offset = int(out.get("offset") or 0)
                out.update(_page_meta(int(out.get("total", len(full))), offset, lo))
    out["truncated"] = True
    return out


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

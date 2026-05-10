"""Wrapper around the Anthropic Python SDK that drives the agent loop.

Public entrypoint: `run_turn(...)`. The view calls this once per user
message; this function then loops over `client.messages.stream(...)`,
executing tools server-side and stopping when the model says
`stop_reason == "end_turn"` or it hits the iteration cap.

Each interesting event (text delta, tool_use start, tool result, usage
totals) is forwarded to the caller via the `on_event(kind, payload)`
callback. The view turns these into SSE frames.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from django.conf import settings

from . import tools as tools_pkg

logger = logging.getLogger(__name__)


@dataclass
class TurnUsage:
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_in: int = 0
    cache_creation_in: int = 0


def _extract_usage(usage_obj) -> TurnUsage:
    """Pull token counts off whatever the SDK gave us (Pydantic v1 / v2 / dict)."""
    if usage_obj is None:
        return TurnUsage()
    get = (
        (lambda k: getattr(usage_obj, k, 0))
        if not isinstance(usage_obj, dict)
        else (lambda k: usage_obj.get(k, 0))
    )
    return TurnUsage(
        tokens_in=int(get("input_tokens") or 0),
        tokens_out=int(get("output_tokens") or 0),
        cache_read_in=int(get("cache_read_input_tokens") or 0),
        cache_creation_in=int(get("cache_creation_input_tokens") or 0),
    )


def _to_dict(block) -> dict:
    """Normalize an Anthropic content block to a plain dict for storage / sending."""
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump()
    if hasattr(block, "dict"):
        return block.dict()
    return dict(block)  # type: ignore[arg-type]


def _build_anthropic_client():
    """Lazy import — avoids forcing the SDK on environments that don't use it."""
    import anthropic  # noqa: WPS433 — deliberately deferred

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


@dataclass
class TurnResult:
    assistant_blocks: list[dict]
    tool_messages: list[dict]  # synthetic user messages carrying tool_result
    final_stop_reason: str
    total_usage: TurnUsage


def run_turn(
    *,
    user_id: uuid.UUID,
    system_blocks: list[dict],
    messages: list[dict],
    model: str,
    max_tokens: int,
    on_event: Callable[[str, dict], None],
    is_cancelled: Callable[[], bool] = lambda: False,
    client=None,
) -> TurnResult:
    """Run one user-input → end_turn agent loop.

    Loops while `stop_reason == "tool_use"`, executing each tool server-side
    against `core.assistant.tools`. Hard-capped at
    settings.ASSISTANT_MAX_TOOL_ITERATIONS to prevent runaway spirals.

    Returns the assistant content blocks, any synthetic tool-result messages
    appended to `messages`, the final stop reason, and aggregated usage.
    """
    cli = client or _build_anthropic_client()
    schemas = tools_pkg.schemas_for_anthropic()
    iterations = 0
    cap = settings.ASSISTANT_MAX_TOOL_ITERATIONS

    total = TurnUsage()
    last_assistant_blocks: list[dict] = []
    tool_messages: list[dict] = []
    stop_reason = "end_turn"

    convo = list(messages)

    while True:
        if is_cancelled():
            on_event("error", {"message": "cancelled"})
            stop_reason = "cancelled"
            break
        iterations += 1
        if iterations > cap:
            on_event(
                "error",
                {"message": f"Tool loop exceeded {cap} iterations"},
            )
            stop_reason = "tool_loop_cap"
            break

        with cli.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            tools=schemas,
            messages=convo,
            metadata={"user_id": str(user_id)},
        ) as stream:
            for event in stream:
                if is_cancelled():
                    break
                kind = getattr(event, "type", None) or (
                    event.get("type") if isinstance(event, dict) else None
                )
                if kind == "content_block_delta":
                    delta = getattr(event, "delta", None) or event.get("delta")
                    delta_type = getattr(delta, "type", None) or (
                        delta.get("type") if isinstance(delta, dict) else None
                    )
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", None) or (
                            delta.get("text") if isinstance(delta, dict) else ""
                        )
                        on_event("text_delta", {"text": text or ""})
                # Other events (content_block_start, message_start, etc.) are
                # ignored at the SSE layer — we forward only what the UI uses.

            final = stream.get_final_message()

        usage = _extract_usage(getattr(final, "usage", None))
        total.tokens_in += usage.tokens_in
        total.tokens_out += usage.tokens_out
        total.cache_read_in += usage.cache_read_in
        total.cache_creation_in += usage.cache_creation_in

        assistant_blocks = [_to_dict(b) for b in (final.content or [])]
        last_assistant_blocks = assistant_blocks
        stop_reason = getattr(final, "stop_reason", "") or "end_turn"

        # Persist the assistant turn into the running conversation BEFORE
        # we run tools — that's how the protocol expects us to thread
        # tool_result blocks back in.
        convo.append({"role": "assistant", "content": assistant_blocks})

        if stop_reason != "tool_use":
            break

        tool_results: list[dict] = []
        for block in assistant_blocks:
            if block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            name = block.get("name")
            args = block.get("input") or {}
            on_event(
                "tool_use_start",
                {"id": tool_id, "name": name, "input": args},
            )
            result = tools_pkg.call(name, user_id, args)
            on_event(
                "tool_result",
                {"id": tool_id, "name": name, "output": result},
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(result),
                }
            )

        if not tool_results:
            # Defensive — model said tool_use but emitted no tool_use blocks.
            break

        synthetic = {"role": "user", "content": tool_results}
        convo.append(synthetic)
        tool_messages.append(synthetic)

    on_event(
        "usage",
        {
            "tokens_in": total.tokens_in,
            "tokens_out": total.tokens_out,
            "cache_read_in": total.cache_read_in,
            "cache_creation_in": total.cache_creation_in,
        },
    )
    return TurnResult(
        assistant_blocks=last_assistant_blocks,
        tool_messages=tool_messages,
        final_stop_reason=stop_reason,
        total_usage=total,
    )

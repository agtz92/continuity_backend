"""Wrapper around the Anthropic Python SDK that drives the agent loop.

Public entrypoint: `run_turn_iter(...)`. The view calls this once per user
message; this function then loops over `client.messages.stream(...)`,
executing tools server-side and stopping when the model says
`stop_reason == "end_turn"` or it runs out of tool budget.

Each interesting event (text delta, tool_use start, tool result, usage
totals) is forwarded to the caller via yielded `(kind, payload)` tuples.
The view turns these into SSE frames.

**Running out of budget is not an error.** When the loop hits its cap it
spends one more call *without tools* so the model closes the turn itself,
naming what it managed to do and what is left. The alternative — the old
behaviour — was an error frame mid-flight, which left the user with
half-applied writes and no idea which ones landed.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from django.conf import settings

from . import tools as tools_pkg

logger = logging.getLogger(__name__)


#: Appended as an extra system block for the closing call only. The model
#: has the whole transcript — including every tool_result — so it can name
#: what landed without us summarising for it.
CLOSING_INSTRUCTION = """You have run out of tool budget for this turn, so no more tools are available to you.

Close the turn now, in the user's language:
1. State plainly what you DID complete, naming each item (use the ids from the tool results so the names become links).
2. State what is still missing.
3. Offer to continue in the next message.

Do not apologise at length and do not claim anything you did not actually do."""


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


class AssistantConfigError(Exception):
    """Surfaces actionable config issues (missing/invalid API key)."""


def _build_anthropic_client():
    """Lazy import — avoids forcing the SDK on environments that don't use it."""
    import anthropic  # noqa: WPS433 — deliberately deferred

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    api_key = api_key.strip()
    if not api_key:
        raise AssistantConfigError(
            "ANTHROPIC_API_KEY is not set on the server. "
            "On Render, add it under the service's Environment tab; "
            "locally, put it in backend/.env and unset any empty shell var."
        )
    if not api_key.startswith("sk-ant-"):
        raise AssistantConfigError(
            "ANTHROPIC_API_KEY is set but malformed "
            "(expected to start with 'sk-ant-'). "
            "Check for stray quotes or whitespace in the value."
        )
    logger.info(
        "Anthropic client built (key prefix=%s, length=%d)",
        api_key[:10],
        len(api_key),
    )
    return anthropic.Anthropic(api_key=api_key)


@dataclass
class AppendedMessage:
    """One message appended to the conversation by `run_turn`.

    `kind` is `"assistant"` for an Anthropic `assistant`-role turn (text
    and/or tool_use blocks), and `"tool"` for the synthetic `user`-role
    message carrying tool_result blocks. The view persists these in
    order, mapping `kind` directly to `Message.role`.

    Pairing invariant: an `assistant` message containing tool_use blocks
    is ALWAYS immediately followed by a `tool` message whose
    tool_use_ids match. This is what `build_messages` and Anthropic's
    API both require.
    """

    kind: str  # "assistant" | "tool"
    content: list[dict]


@dataclass
class TurnResult:
    appended: list[AppendedMessage]
    final_stop_reason: str
    total_usage: TurnUsage
    #: Tool calls that actually ran this turn, in order. Lets the view log
    #: what landed when the budget ran out.
    executed: list[dict] = field(default_factory=list)


def _stream_turn(
    cli,
    *,
    model: str,
    max_tokens: int,
    system: list[dict],
    tools: Optional[list[dict]],
    messages: list[dict],
    user_id: uuid.UUID,
    is_cancelled: Callable[[], bool],
):
    """One streaming call. Yields ("text_delta", …) then ("__final__", msg).

    `tools=None` omits the parameter entirely — that is how the closing
    call guarantees the model cannot ask for another tool.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "metadata": {"user_id": str(user_id)},
    }
    if tools is not None:
        kwargs["tools"] = tools

    with cli.messages.stream(**kwargs) as stream:
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
                    yield ("text_delta", {"text": text or ""})
            # Other events (content_block_start, message_start, etc.) are
            # ignored at the SSE layer — we forward only what the UI uses.

        final = stream.get_final_message()

    yield ("__final__", final)


def run_turn_iter(
    *,
    user_id: uuid.UUID,
    system_blocks: list[dict],
    messages: list[dict],
    model: str,
    max_tokens: int,
    plan: str = "free",
    is_cancelled: Callable[[], bool] = lambda: False,
    on_append: Optional[Callable[[AppendedMessage], None]] = None,
    client=None,
):
    """Generator-based agent loop. Yields events AS THEY HAPPEN.

    Each yielded item is either a `(kind: str, payload: dict)` tuple
    (for events the SSE view forwards to the browser) or a `TurnResult`
    object (the final yield, exactly one per call). The view distinguishes
    by `isinstance` — events go on the wire, the result drives DB
    persistence and quota recording.

    Yielding text_delta / tool_use_start / tool_result chunks as they
    arrive (instead of after the whole turn) is what makes the chat
    feel real-time. Anthropic's SDK already streams; we just stop
    buffering on top of it.
    """
    cli = client or _build_anthropic_client()
    schemas = tools_pkg.schemas_for_anthropic(plan)
    iterations = 0
    cap = settings.ASSISTANT_MAX_TOOL_ITERATIONS

    total = TurnUsage()
    appended: list[AppendedMessage] = []
    executed: list[dict] = []
    stop_reason = "end_turn"

    convo = list(messages)

    def _add(msg: AppendedMessage) -> None:
        """Record a message AND hand it to the caller right away.

        The caller persists it immediately. Collecting everything and
        writing at the end looked tidier and lost the whole turn whenever
        the stream died mid-flight — the tools had already written to the
        database, so the user was left with real projects and tasks and a
        conversation that never mentioned creating them.

        If we die between an assistant tool_use row and its tool_result
        row, the orphan is handled on read by `_trim_to_pair_clean`.
        """
        appended.append(msg)
        if on_append is not None:
            on_append(msg)

    def _account(final) -> None:
        usage = _extract_usage(getattr(final, "usage", None))
        total.tokens_in += usage.tokens_in
        total.tokens_out += usage.tokens_out
        total.cache_read_in += usage.cache_read_in
        total.cache_creation_in += usage.cache_creation_in

    while True:
        if is_cancelled():
            yield ("error", {"message": "cancelled"})
            stop_reason = "cancelled"
            break

        iterations += 1
        if iterations > cap:
            # Budget spent. One more call WITHOUT tools so the model closes
            # the turn itself — the transcript already holds every
            # tool_result, so it can name what landed. Anything already
            # written stays written; the user gets told which.
            yield (
                "budget_exhausted",
                {"iterations": cap, "executed": [e["name"] for e in executed]},
            )
            final = None
            for kind, payload in _stream_turn(
                cli,
                model=model,
                max_tokens=max_tokens,
                system=[*system_blocks, {"type": "text", "text": CLOSING_INSTRUCTION}],
                tools=None,
                messages=convo,
                user_id=user_id,
                is_cancelled=is_cancelled,
            ):
                if kind == "__final__":
                    final = payload
                    break
                yield (kind, payload)

            if final is not None:
                _account(final)
                closing_blocks = [_to_dict(b) for b in (final.content or [])]
                # No tools were offered, so this can only be text — safe to
                # persist without the pairing dance below.
                if closing_blocks:
                    convo.append({"role": "assistant", "content": closing_blocks})
                    _add(AppendedMessage(kind="assistant", content=closing_blocks))
            stop_reason = "tool_budget_closed"
            break

        final = None
        for kind, payload in _stream_turn(
            cli,
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            tools=schemas,
            messages=convo,
            user_id=user_id,
            is_cancelled=is_cancelled,
        ):
            if kind == "__final__":
                final = payload
                break
            yield (kind, payload)

        if final is None:
            # Cancelled mid-stream before the SDK produced a final message.
            stop_reason = "cancelled"
            break

        _account(final)

        assistant_blocks = [_to_dict(b) for b in (final.content or [])]
        stop_reason = getattr(final, "stop_reason", "") or "end_turn"

        has_tool_use = any(b.get("type") == "tool_use" for b in assistant_blocks)

        if stop_reason != "tool_use" and has_tool_use:
            # Truncated mid-tool-use (typically stop_reason == "max_tokens").
            # The calls can't be executed, and an unpaired tool_use 400s
            # every later request — but the prose in front of them is real,
            # and the user already watched it stream in. Keep the text,
            # drop only the unusable calls, so the transcript still shows
            # what was said instead of silently losing the turn.
            text_only = [b for b in assistant_blocks if b.get("type") == "text"]
            if text_only:
                convo.append({"role": "assistant", "content": text_only})
                _add(AppendedMessage(kind="assistant", content=text_only))
            yield (
                "error",
                {
                    "message": (
                        "The response was cut off before its actions "
                        "could run — try again, or ask for a smaller step."
                    )
                },
            )
            break

        # Persist the assistant turn into the running conversation BEFORE
        # we run tools — that's how the protocol expects us to thread
        # tool_result blocks back in.
        convo.append({"role": "assistant", "content": assistant_blocks})
        _add(AppendedMessage(kind="assistant", content=assistant_blocks))

        if stop_reason != "tool_use":
            break

        tool_results: list[dict] = []
        for block in assistant_blocks:
            if block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            name = block.get("name")
            args = block.get("input") or {}
            yield ("tool_use_start", {"id": tool_id, "name": name, "input": args})
            result = tools_pkg.call(name, user_id, args, plan)
            executed.append({"name": name, "ok": "error" not in (result or {})})
            yield ("tool_result", {"id": tool_id, "name": name, "output": result})
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(result),
                }
            )

        if not tool_results:
            # Defensive — the model said tool_use but emitted no tool_use
            # blocks, so there is nothing to run and nothing to pair. The
            # turn we just persisted holds text only, which is harmless.
            break

        synthetic = {"role": "user", "content": tool_results}
        convo.append(synthetic)
        _add(AppendedMessage(kind="tool", content=tool_results))

    yield (
        "usage",
        {
            "tokens_in": total.tokens_in,
            "tokens_out": total.tokens_out,
            "cache_read_in": total.cache_read_in,
            "cache_creation_in": total.cache_creation_in,
        },
    )
    yield TurnResult(
        appended=appended,
        final_stop_reason=stop_reason,
        total_usage=total,
        executed=executed,
    )

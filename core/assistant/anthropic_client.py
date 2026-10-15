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

**Nor do the other ways a turn used to stop halfway.** A response cut off
by `max_tokens` mid-tool_use is retried in smaller pieces (up to
`MAX_TRUNCATION_RETRIES`); a reply that announces work and ends without
doing it gets one nudge; a transient upstream error is retried with
backoff while the attempt has not streamed text yet.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
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


#: Sent as a user-role message after a response hit `max_tokens` in the
#: middle of a tool_use. None of the calls it was writing can run, so the
#: model gets told which ones and asked to redo them in smaller bites.
TRUNCATION_RETRY_INSTRUCTION = """[runtime] Your previous response was cut off by the length limit before it could run: {names}. NONE of those calls were executed.

Redo them now, at most 2 tool calls per response, keeping each call's content short enough to finish. Do not repeat text you already wrote."""

#: Persisted in place of a truncated response that had no prose, so the
#: thread does not end on the user's message as if nothing happened.
TRUNCATION_PLACEHOLDER = "(Response cut off before running {names}; retrying in smaller pieces.)"

#: Retries after a truncated tool_use, per turn. They spend tool budget
#: like any other iteration.
MAX_TRUNCATION_RETRIES = 2

#: Sent as a user-role message, once per turn, when the model announced an
#: action ("voy a…", "let me…") and closed the turn without doing it.
NUDGE_INSTRUCTION = """[runtime] You announced an action but ended your turn without doing it. Either call the tool(s) now to do what you announced, or — if you need the user's input or approval first — ask for it with an explicit question. Do not repeat what you already wrote."""

#: Anthropic errors worth retrying: they say nothing about the request.
#: Matched by class name so the check works without importing the SDK.
TRANSIENT_ERRORS = frozenset(
    {
        "OverloadedError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
    }
)
#: Sleep before each retry; its length is the number of retries.
RETRY_BACKOFF_SECONDS = (1.0, 3.0)


#: Keepalive. While the model writes a long tool_use input (note bodies,
#: detailed prompts) the SDK yields hundreds of `input_json_delta` events
#: and we forward none of them — measured in prod: 63s with no byte on the
#: wire, long enough for any proxy idle-timeout to cut the turn. A `ping`
#: event (an SSE comment on the wire, which clients ignore) goes out after
#: this many seconds of silence...
KEEPALIVE_SECONDS = 10.0
#: ...or after this many SDK events with nothing forwarded, whichever comes
#: first. A comment is 8 bytes; sending one every few hundred tokens of
#: tool input costs nothing and does not depend on the clock.
KEEPALIVE_EVERY_EVENTS = 200


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

    last_emit = time.monotonic()
    silent = 0

    with cli.messages.stream(**kwargs) as stream:
        for event in stream:
            if is_cancelled():
                break
            kind = getattr(event, "type", None) or (
                event.get("type") if isinstance(event, dict) else None
            )
            out = None
            if kind == "content_block_start":
                block = getattr(event, "content_block", None) or (
                    event.get("content_block") if isinstance(event, dict) else None
                )
                block_type = getattr(block, "type", None) or (
                    block.get("type") if isinstance(block, dict) else None
                )
                if block_type == "tool_use":
                    # The input can take a minute to write. Telling the UI
                    # *what* is being written now beats a frozen bubble.
                    name = getattr(block, "name", None) or (
                        block.get("name") if isinstance(block, dict) else None
                    )
                    out = ("tool_use_pending", {"name": name or ""})
            elif kind == "content_block_delta":
                delta = getattr(event, "delta", None) or event.get("delta")
                delta_type = getattr(delta, "type", None) or (
                    delta.get("type") if isinstance(delta, dict) else None
                )
                if delta_type == "text_delta":
                    text = getattr(delta, "text", None) or (
                        delta.get("text") if isinstance(delta, dict) else ""
                    )
                    out = ("text_delta", {"text": text or ""})
            # Other events (message_start, input_json_delta, etc.) are not
            # forwarded — but they still count towards the keepalive.

            if out is not None:
                yield out
                last_emit = time.monotonic()
                silent = 0
                continue
            silent += 1
            if (
                silent >= KEEPALIVE_EVERY_EVENTS
                or time.monotonic() - last_emit >= KEEPALIVE_SECONDS
            ):
                yield ("ping", {})
                last_emit = time.monotonic()
                silent = 0

        final = stream.get_final_message()

    yield ("__final__", final)


def _stream_with_retry(cli, **kwargs):
    """`_stream_turn`, retried with backoff on a transient upstream error.

    Only while the attempt has not streamed any text: the user already saw
    that prose, and a retry would write it a second time.
    """
    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        spoke = False
        try:
            for kind, payload in _stream_turn(cli, **kwargs):
                if kind == "text_delta":
                    spoke = True
                yield (kind, payload)
            return
        except Exception as e:  # noqa: BLE001 — re-raised unless transient
            if (
                spoke
                or type(e).__name__ not in TRANSIENT_ERRORS
                or attempt >= len(RETRY_BACKOFF_SECONDS)
            ):
                raise
            logger.warning(
                "assistant: transient %s, retry %d", type(e).__name__, attempt + 1
            )
            yield ("ping", {})
            time.sleep(RETRY_BACKOFF_SECONDS[attempt])


_ANNOUNCE_RE = re.compile(
    r"\bvoy a\b|\bd[ée]jame\b(?!\s+saber)|\bprocedo\b|\bI['’]ll\b|\blet me\b(?!\s+know)",
    re.IGNORECASE,
)


def _announces_without_acting(blocks: list[dict]) -> bool:
    """True when a tool-less reply promises work instead of doing or asking.

    Looks at the last paragraph only: an earlier "voy a…" followed by a
    finished answer is narration, not a pending promise. A reply ending in
    ":" is announcing by construction.
    """
    text = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
    text = text.strip()
    if not text or text.endswith("?"):
        return False
    if text.endswith(":"):
        return True
    last = text.split("\n\n")[-1]
    return bool(_ANNOUNCE_RE.search(last))


def _call_with_keepalive(fn: Callable[[], Any], *, every: Optional[float] = None):
    """Run `fn` in a helper thread, yielding ("ping", {}) every `every` seconds
    until it finishes. Yields ("__result__", value) last; re-raises its error.

    The view can only write to the socket from its own generator, so a slow
    tool call would otherwise leave the wire silent for its whole duration.

    The helper thread borrows this thread's DB connections (the same trick
    as Django's LiveServerThread): the tool runs inside the request's
    connection and transaction, exactly as if it were called inline. That
    is safe because this thread does nothing with the database meanwhile —
    it only yields pings — and it always joins before returning, even when
    the client vanishes (GeneratorExit), so the connection is never used
    by two threads at once.
    """
    from django.db import connections

    every = KEEPALIVE_SECONDS if every is None else every
    conns = list(connections.all(initialized_only=True))
    box: dict[str, Any] = {}

    def _target() -> None:
        for conn in conns:
            connections[conn.alias] = conn
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 — re-raised in the caller
            box["error"] = e

    for conn in conns:
        conn.inc_thread_sharing()
    worker = threading.Thread(target=_target, name="assistant-tool", daemon=True)
    try:
        worker.start()
        while True:
            worker.join(timeout=every)
            if not worker.is_alive():
                break
            yield ("ping", {})
    finally:
        worker.join()
        for conn in conns:
            conn.dec_thread_sharing()

    if "error" in box:
        raise box["error"]
    yield ("__result__", box.get("value"))


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
    truncation_retries = 0
    nudged = False

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
            for kind, payload in _stream_with_retry(
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
        for kind, payload in _stream_with_retry(
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
            if truncation_retries < MAX_TRUNCATION_RETRIES:
                # Ask for the same work in smaller pieces instead of ending
                # the turn. With no prose, a placeholder keeps the thread
                # from ending on the user; the instruction goes in as a
                # user message so roles keep alternating. It is not
                # persisted — replay merges the two assistant rows.
                truncation_retries += 1
                names = ", ".join(
                    b.get("name") or "?"
                    for b in assistant_blocks
                    if b.get("type") == "tool_use"
                )
                kept = text_only or [
                    {"type": "text", "text": TRUNCATION_PLACEHOLDER.format(names=names)}
                ]
                convo.append({"role": "assistant", "content": kept})
                _add(AppendedMessage(kind="assistant", content=kept))
                convo.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": TRUNCATION_RETRY_INSTRUCTION.format(names=names),
                            }
                        ],
                    }
                )
                continue
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
            if (
                stop_reason == "end_turn"
                and not nudged
                and not has_tool_use
                and _announces_without_acting(assistant_blocks)
            ):
                # "Voy a crear el proyecto…" and the turn ends: the user is
                # left waiting for work that never comes. One push per turn
                # to either do it or ask.
                nudged = True
                convo.append(
                    {"role": "user", "content": [{"type": "text", "text": NUDGE_INSTRUCTION}]}
                )
                continue
            break

        tool_results: list[dict] = []
        for block in assistant_blocks:
            if block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            name = block.get("name")
            args = block.get("input") or {}
            yield ("tool_use_start", {"id": tool_id, "name": name, "input": args})
            result = None
            for kind, payload in _call_with_keepalive(
                lambda: tools_pkg.call(name, user_id, args, plan)
            ):
                if kind == "__result__":
                    result = payload
                else:
                    yield (kind, payload)
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

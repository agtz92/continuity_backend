"""The three ways an instruction used to stall, each pinned by a test.

Before this file none of them had coverage, which is how all three
survived: a cancel flag that outlived its turn, a tool budget that died on
an error frame mid-write, and a history window measured in DB rows.
"""

from __future__ import annotations

import datetime as dt
import json
from unittest import mock

import jwt
import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from core import auth as auth_module
from core.assistant import anthropic_client, prompts
from core.assistant.models import Conversation, Message, MessageRole


@pytest.fixture(autouse=True)
def _force_test_auth_settings(settings, monkeypatch):
    settings.SUPABASE_URL = ""
    settings.SUPABASE_JWT_SECRET = "test-jwt-secret"
    monkeypatch.setattr(auth_module, "_jwks_client", None)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def http():
    return Client()


def _make_jwt(user_id):
    return jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 3600,
        },
        django_settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


def _consume_sse(response) -> list[tuple[str, dict]]:
    body = b"".join(response.streaming_content).decode("utf-8")
    frames: list[tuple[str, dict]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        kind, data = "", {}
        for line in chunk.splitlines():
            if line.startswith("event: "):
                kind = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        frames.append((kind, data))
    return frames


def _post(http, user_a, payload):
    return http.post(
        "/api/assistant/chat/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_make_jwt(user_a)}",
    )


_PLAIN_TURN = {
    "text": "Done.",
    "tool_uses": [],
    "stop_reason": "end_turn",
    "usage": {
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    },
}


# --------------------------------------------------------------------------
# 1. The cancel flag
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_stale_cancel_flag_does_not_kill_the_next_message(
    http, user_a, make_profile, fake_anthropic
):
    """Stop, then send again: the new message must run.

    The flag has a 60s TTL and the stream that set it is already gone, so
    without clearing it at the top of the turn the user's next message
    died before reaching the model — which is exactly what "se frenaba la
    instrucción" looked like.
    """
    make_profile(user_a, plan="studio")
    conv = Conversation.objects.create(user_id=user_a, title="t")

    # A Stop from a turn that has already ended leaves this behind.
    cache.set(f"assistant:cancel:{conv.id}", 1, 60)

    fake = fake_anthropic([_PLAIN_TURN])
    with mock.patch.object(
        anthropic_client, "_build_anthropic_client", return_value=fake
    ):
        response = _post(http, user_a, {"content": "Hi", "conversation_id": str(conv.id)})
        frames = _consume_sse(response)

    kinds = [k for k, _ in frames]
    assert "text_delta" in kinds
    assert not any(
        k == "error" and p.get("message") == "cancelled" for k, p in frames
    )


@pytest.mark.django_db
def test_the_flag_is_cleared_even_when_the_client_walks_away(
    http, user_a, make_profile, fake_anthropic
):
    """Abandoning the stream must not leave the flag behind.

    The browser aborts the fetch on Stop, on navigation and on a dropped
    connection. Closing the generator raises GeneratorExit inside it; the
    `finally` is what guarantees the flag dies with its turn.
    """
    make_profile(user_a, plan="studio")
    conv = Conversation.objects.create(user_id=user_a, title="t")
    key = f"assistant:cancel:{conv.id}"

    fake = fake_anthropic([_PLAIN_TURN])
    with mock.patch.object(
        anthropic_client, "_build_anthropic_client", return_value=fake
    ):
        response = _post(http, user_a, {"content": "Hi", "conversation_id": str(conv.id)})
        next(response.streaming_content)  # read the meta frame, then walk away
        cache.set(key, 1, 60)  # as /cancel/ would
        # Django registered the generator's close() as a resource closer,
        # so this is what a disconnecting client triggers.
        response.close()

    assert cache.get(key) is None


# --------------------------------------------------------------------------
# 2. The tool budget
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_running_out_of_budget_closes_the_turn_instead_of_erroring(
    http, user_a, make_profile, make_project, fake_anthropic, settings
):
    """A model that never stops asking for tools must still get an answer out.

    The old behaviour emitted `Tool loop exceeded N iterations` and
    stopped — leaving whatever had already been written in place, unnamed.
    Now the budget ends with one tool-less call so the model says what it
    managed to do.
    """
    settings.ASSISTANT_MAX_TOOL_ITERATIONS = 2
    make_profile(user_a, plan="studio")
    make_project(user_a, name="Alpha")

    greedy = {
        "text": "",
        "tool_uses": [{"id": "tu_1", "name": "list_projects", "input": {}}],
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    closing = dict(_PLAIN_TURN, text="I listed your projects; nothing else ran.")
    fake = fake_anthropic([greedy, greedy, closing])

    with mock.patch.object(
        anthropic_client, "_build_anthropic_client", return_value=fake
    ):
        response = _post(http, user_a, {"content": "Do everything"})
        frames = _consume_sse(response)

    kinds = [k for k, _ in frames]
    assert "budget_exhausted" in kinds
    # The user gets prose, not a stack of raw errors.
    assert "text_delta" in kinds
    assert not any("exceeded" in str(p.get("message", "")) for k, p in frames if k == "error")

    done = next(p for k, p in frames if k == "done")
    assert done["ok"] is True
    assert done["stop_reason"] == "tool_budget_closed"

    # The closing call must have gone out WITHOUT tools — that is what
    # makes it a closing call and not another chance to dig deeper.
    assert "tools" not in fake.messages.calls[-1]

    conv = Conversation.objects.get(user_id=user_a)
    last = Message.objects.filter(
        conversation=conv, role=MessageRole.ASSISTANT
    ).order_by("created").last()
    assert last.content[0]["text"].startswith("I listed your projects")


@pytest.mark.django_db
def test_the_budget_report_names_what_actually_ran(
    http, user_a, make_profile, make_project, fake_anthropic, settings
):
    settings.ASSISTANT_MAX_TOOL_ITERATIONS = 1
    make_profile(user_a, plan="studio")
    make_project(user_a, name="Alpha")

    greedy = {
        "text": "",
        "tool_uses": [{"id": "tu_1", "name": "list_projects", "input": {}}],
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    fake = fake_anthropic([greedy, _PLAIN_TURN])

    with mock.patch.object(
        anthropic_client, "_build_anthropic_client", return_value=fake
    ):
        frames = _consume_sse(_post(http, user_a, {"content": "go"}))

    payload = next(p for k, p in frames if k == "budget_exhausted")
    assert payload["executed"] == ["list_projects"]


# --------------------------------------------------------------------------
# 3. The history window
# --------------------------------------------------------------------------


def _add(conv, role, content):
    return Message.objects.create(conversation=conv, role=role, content=content)


@pytest.mark.django_db
def test_history_counts_turns_not_rows(user_a, settings):
    """One tool-heavy turn must not evict the rest of the conversation.

    Four tool calls write eight rows. Under the old row-counted window of
    12 that was most of the budget, so the user's own earlier messages
    fell out of context while they were still talking about them.
    """
    settings.ASSISTANT_MAX_HISTORY_TURNS = 3
    conv = Conversation.objects.create(user_id=user_a, title="t")

    _add(conv, MessageRole.USER, [{"type": "text", "text": "first instruction"}])
    for i in range(4):
        _add(
            conv,
            MessageRole.ASSISTANT,
            [{"type": "tool_use", "id": f"tu_{i}", "name": "list_projects", "input": {}}],
        )
        _add(
            conv,
            MessageRole.TOOL,
            [{"type": "tool_result", "tool_use_id": f"tu_{i}", "content": "{}"}],
        )
    _add(conv, MessageRole.ASSISTANT, [{"type": "text", "text": "done"}])

    messages = prompts.build_messages(conv, "and now the follow-up")

    flat = json.dumps(messages)
    assert "first instruction" in flat
    assert messages[-1]["content"] == "and now the follow-up"


@pytest.mark.django_db
def test_history_drops_the_oldest_turns_beyond_the_window(user_a, settings):
    settings.ASSISTANT_MAX_HISTORY_TURNS = 2
    conv = Conversation.objects.create(user_id=user_a, title="t")

    for n in range(4):
        _add(conv, MessageRole.USER, [{"type": "text", "text": f"turn {n}"}])
        _add(conv, MessageRole.ASSISTANT, [{"type": "text", "text": f"reply {n}"}])

    flat = json.dumps(prompts.build_messages(conv, "next"))
    assert "turn 0" not in flat
    assert "turn 1" not in flat
    assert "turn 2" in flat
    assert "turn 3" in flat


@pytest.mark.django_db
def test_old_tool_results_are_compacted_but_never_orphaned(user_a, settings):
    """Shrinking an old result must keep its block — dropping one would
    orphan the matching tool_use and 400 the whole request."""
    settings.ASSISTANT_MAX_HISTORY_TURNS = 8
    conv = Conversation.objects.create(user_id=user_a, title="t")

    big = "x" * 5000
    for n in range(4):
        _add(conv, MessageRole.USER, [{"type": "text", "text": f"turn {n}"}])
        _add(
            conv,
            MessageRole.ASSISTANT,
            [{"type": "tool_use", "id": f"tu_{n}", "name": "search", "input": {}}],
        )
        _add(
            conv,
            MessageRole.TOOL,
            [{"type": "tool_result", "tool_use_id": f"tu_{n}", "content": big}],
        )
        _add(conv, MessageRole.ASSISTANT, [{"type": "text", "text": f"reply {n}"}])

    messages = prompts.build_messages(conv, "next")

    use_ids, result_ids = set(), set()
    for m in messages:
        if not isinstance(m["content"], list):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_use":
                use_ids.add(b["id"])
            elif b.get("type") == "tool_result":
                result_ids.add(b["tool_use_id"])
    assert use_ids == result_ids

    # The oldest bodies shrank; the most recent ones are untouched.
    bodies = [
        b["content"]
        for m in messages
        if isinstance(m["content"], list)
        for b in m["content"]
        if b.get("type") == "tool_result"
    ]
    assert any(len(b) < 200 for b in bodies)
    assert any(len(b) == 5000 for b in bodies)


# --------------------------------------------------------------------------
# 4. A stream that dies mid-turn
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_work_already_done_survives_a_stream_that_never_finishes(
    http, user_a, make_profile, make_project, fake_anthropic
):
    """The killer bug: tools ran, the stream died, the transcript vanished.

    Persisting at the end meant a worker timeout on a long turn threw away
    every message — while the tools had already written real projects and
    tasks. The user was left with work in their account and a conversation
    that never mentioned doing it.
    """
    make_profile(user_a, plan="studio")
    make_project(user_a, name="Alpha")
    conv = Conversation.objects.create(user_id=user_a, title="t")

    turn = {
        "text": "Creating things:",
        "tool_uses": [{"id": "tu_1", "name": "list_projects", "input": {}}],
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    fake = fake_anthropic([turn, _PLAIN_TURN])

    with mock.patch.object(
        anthropic_client, "_build_anthropic_client", return_value=fake
    ):
        response = _post(http, user_a, {"content": "go", "conversation_id": str(conv.id)})
        # Read far enough that the tool has run, then die like a killed
        # worker: consume nothing more and close.
        stream = response.streaming_content
        for _ in range(4):
            next(stream, None)
        response.close()

    rows = list(Message.objects.filter(conversation=conv).order_by("created"))
    roles = [r.role for r in rows]
    assert MessageRole.ASSISTANT in roles, "the turn must survive the cut"
    # And what survived is pair-clean enough to replay without a 400.
    replay = prompts.build_messages(conv, "next")
    use_ids, result_ids = set(), set()
    for m in replay:
        if not isinstance(m["content"], list):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_use":
                use_ids.add(b["id"])
            elif b.get("type") == "tool_result":
                result_ids.add(b["tool_use_id"])
    assert use_ids == result_ids


@pytest.mark.django_db
def test_a_turn_truncated_mid_tool_use_keeps_its_prose(
    http, user_a, make_profile, fake_anthropic
):
    """max_tokens mid-call: drop the unusable calls, keep what was said.

    Dropping the whole turn also deleted the paragraph the user had just
    watched stream in, so the thread ended on their own message as if
    nothing had happened.
    """
    make_profile(user_a, plan="studio")

    truncated = {
        "text": "Ahora agrego las notas con los prompts detallados:",
        "tool_uses": [{"id": "tu_1", "name": "create_note", "input": {}}],
        "stop_reason": "max_tokens",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    fake = fake_anthropic([truncated])

    with mock.patch.object(
        anthropic_client, "_build_anthropic_client", return_value=fake
    ):
        frames = _consume_sse(_post(http, user_a, {"content": "go"}))

    assert any(k == "error" and "cut off" in p.get("message", "") for k, p in frames)

    conv = Conversation.objects.get(user_id=user_a)
    rows = list(
        Message.objects.filter(conversation=conv, role=MessageRole.ASSISTANT)
    )
    assert len(rows) == 1
    blocks = rows[0].content
    assert blocks[0]["text"].startswith("Ahora agrego las notas")
    # The unusable call is gone — keeping it would 400 every later request.
    assert not any(b.get("type") == "tool_use" for b in blocks)

"""Fixtures for the assistant tests."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Iterable

import pytest
from django.utils import timezone

from core.models import Category, Idea, Project, Task, ProjectNote
from core.assistant.models import AccountProfile


@pytest.fixture
def user_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_b() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def make_profile(db):
    def _make(user_id: uuid.UUID, plan: str = "free") -> AccountProfile:
        profile, _ = AccountProfile.objects.update_or_create(
            user_id=user_id, defaults={"plan": plan}
        )
        return profile

    return _make


@pytest.fixture
def make_project(db):
    def _make(user_id: uuid.UUID, **overrides) -> Project:
        defaults = {
            "name": "P",
            "description": "",
            "why": "",
            "next_step": "",
            "status": "active",
            "priority": "medium",
        }
        defaults.update(overrides)
        return Project.objects.create(user_id=user_id, **defaults)

    return _make


@pytest.fixture
def make_task(db):
    def _make(user_id: uuid.UUID, project: Project | None = None, **overrides) -> Task:
        defaults = {"title": "T", "done": False}
        defaults.update(overrides)
        return Task.objects.create(user_id=user_id, project=project, **defaults)

    return _make


@pytest.fixture
def make_idea(db):
    def _make(user_id: uuid.UUID, **overrides) -> Idea:
        defaults = {"title": "I", "description": "", "why": ""}
        defaults.update(overrides)
        return Idea.objects.create(user_id=user_id, **defaults)

    return _make


@pytest.fixture
def fake_anthropic():
    """A scripted stand-in for `anthropic.Anthropic`.

    Pass a list of `turns`, where each turn is a dict like:
        {"text": "...", "tool_uses": [{"id": "tu_1", "name": "list_projects", "input": {}}], "stop_reason": "tool_use"}
    The fake delivers them in order. After the last scripted turn,
    further calls return an empty `end_turn` to keep the loop terminated.
    """

    class _FakeStream:
        def __init__(self, content_blocks: list[dict], stop_reason: str, usage: dict):
            self._content_blocks = content_blocks
            self._stop_reason = stop_reason
            self._usage = usage

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            for block in self._content_blocks:
                if block.get("type") == "text":
                    yield _SimpleEvent(
                        type="content_block_delta",
                        delta=_SimpleEvent(type="text_delta", text=block["text"]),
                    )

        def get_final_message(self):
            return _SimpleEvent(
                content=self._content_blocks,
                stop_reason=self._stop_reason,
                usage=_SimpleEvent(**self._usage),
            )

    class _Messages:
        def __init__(self, scripted: list[dict]):
            self._scripted = list(scripted)
            self.calls: list[dict] = []

        def stream(self, **kwargs) -> _FakeStream:  # noqa: D401
            self.calls.append(kwargs)
            if self._scripted:
                turn = self._scripted.pop(0)
            else:
                turn = {"text": "", "tool_uses": [], "stop_reason": "end_turn"}
            blocks: list[dict] = []
            if turn.get("text"):
                blocks.append({"type": "text", "text": turn["text"]})
            for tu in turn.get("tool_uses") or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu.get("input") or {},
                    }
                )
            return _FakeStream(
                content_blocks=blocks,
                stop_reason=turn.get("stop_reason", "end_turn"),
                usage=turn.get(
                    "usage",
                    {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                ),
            )

    class _Client:
        def __init__(self, scripted: list[dict]):
            self.messages = _Messages(scripted)

    def _factory(turns: Iterable[dict] | None = None) -> _Client:
        return _Client(list(turns or []))

    return _factory


class _SimpleEvent:
    """Tiny stand-in for the SDK's pydantic event objects."""

    def __init__(self, **kwargs: Any):
        for k, v in kwargs.items():
            setattr(self, k, v)

"""Shared fixtures for the GraphQL test suite.

Tests execute against the schema directly via `schema.execute_sync(...)`,
bypassing the HTTP layer entirely. The context object is a tiny stand-in
for what `JWTAuthGraphQLView` would normally produce — only the
`user_id` attribute matters for resolvers.
"""

import uuid
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from core.schema import schema
from core.models import (
    Category,
    Idea,
    Project,
    Task,
)


@pytest.fixture
def user_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_b() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def execute_query():
    """Return a callable that runs a GraphQL document.

    Pass `user_id=None` to simulate an unauthenticated request — that
    matches what the resolvers see when `JWTAuthGraphQLView` lets a
    request through with no auth (which it does NOT in production, but
    we want resolver-level defense-in-depth verified).
    """

    def _run(
        document: str,
        user_id: Optional[uuid.UUID] = None,
        variable_values: Optional[dict[str, Any]] = None,
    ):
        context = SimpleNamespace(user_id=user_id)
        return schema.execute_sync(
            document,
            context_value=context,
            variable_values=variable_values or {},
        )

    return _run


@pytest.fixture
def project_factory(db):
    def _make(user_id: uuid.UUID, **overrides) -> Project:
        defaults = {
            "name": "Test project",
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
def task_factory(db):
    def _make(user_id: uuid.UUID, project: Optional[Project] = None, **overrides) -> Task:
        defaults = {"title": "Test task", "done": False}
        defaults.update(overrides)
        return Task.objects.create(user_id=user_id, project=project, **defaults)

    return _make


@pytest.fixture
def idea_factory(db):
    def _make(user_id: uuid.UUID, **overrides) -> Idea:
        defaults = {"title": "Test idea", "description": "", "why": ""}
        defaults.update(overrides)
        return Idea.objects.create(user_id=user_id, **defaults)

    return _make


@pytest.fixture
def category_factory(db):
    def _make(user_id: uuid.UUID, **overrides) -> Category:
        defaults = {"name": "Test category", "color": "emerald"}
        defaults.update(overrides)
        return Category.objects.create(user_id=user_id, **defaults)

    return _make

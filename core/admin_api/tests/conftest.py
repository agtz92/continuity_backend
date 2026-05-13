"""Local fixtures for admin_api tests.

Mirror the lightweight GraphQL-execution fixtures from
core/tests/conftest.py so admin_api tests can run independently without
importing from a sibling tests package.
"""

import uuid
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from core.schema import schema


@pytest.fixture
def user_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_b() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def execute_query():
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

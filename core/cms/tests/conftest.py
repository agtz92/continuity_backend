"""Mirror of the lightweight GraphQL fixtures used elsewhere."""

import uuid
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from core.cms.views import public_schema
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


@pytest.fixture
def execute_public_query():
    def _run(
        document: str,
        variable_values: Optional[dict[str, Any]] = None,
    ):
        return public_schema.execute_sync(
            document,
            variable_values=variable_values or {},
        )

    return _run

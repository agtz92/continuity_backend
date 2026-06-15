"""Reuse the assistant test fixtures for the connector tests.

Importing the fixture functions into this conftest registers them for
collection under `core/mcp/tests/` (standard pytest pattern).
"""

from core.assistant.tests.conftest import (  # noqa: F401
    make_idea,
    make_profile,
    make_project,
    make_task,
    user_a,
    user_b,
)

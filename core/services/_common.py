"""Shared primitives used across services.

Lives in its own module to keep the dependency graph acyclic:
`projects` and `activities` both need `NotFoundError` and would otherwise
import each other.
"""


class NotFoundError(Exception):
    """Raised when an entity is missing or owned by another user."""

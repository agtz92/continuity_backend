"""Service layer for Continuity core entities.

Pure-Python functions that wrap the Django ORM with consistent user_id
scoping. Both the GraphQL resolvers in `core.schema` and the assistant's
tool handlers in `core.assistant.tools` call into here, so business
logic lives in exactly one place.

Every public function takes `user_id: uuid.UUID` as the first argument
and filters every query by it. There is no path that returns data
belonging to another user, even with a forged primary key.
"""

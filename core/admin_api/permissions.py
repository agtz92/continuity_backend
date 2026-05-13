"""Admin authorization helper.

`_admin_user_id(info)` returns the authenticated user's UUID iff their
AccountProfile.is_admin flag is True. Anything else raises a
GraphQLError with code FORBIDDEN, which the frontend can surface as a
403 (the user is authenticated, just not authorized).
"""

from __future__ import annotations

import uuid

from graphql import GraphQLError
from strawberry.types import Info

from core.assistant.models import AccountProfile


def _admin_user_id(info: Info) -> uuid.UUID:
    user_id = getattr(info.context, "user_id", None)
    if not user_id:
        raise GraphQLError(
            "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
        )
    is_admin = (
        AccountProfile.objects.filter(user_id=user_id)
        .values_list("is_admin", flat=True)
        .first()
    )
    if not is_admin:
        raise GraphQLError(
            "Admin access required", extensions={"code": "FORBIDDEN"}
        )
    return user_id


def is_admin(user_id: uuid.UUID) -> bool:
    return bool(
        AccountProfile.objects.filter(user_id=user_id, is_admin=True).exists()
    )

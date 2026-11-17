"""Admin authorization helper.

`_admin_user_id(info)` returns the authenticated user's UUID iff their
AccountProfile.is_admin flag is True AND the session passed a second factor
(JWT `aal` == "aal2", unless settings.ADMIN_REQUIRE_MFA is off). A non-admin
gets FORBIDDEN; an admin without the second factor gets MFA_REQUIRED, which
the web panel answers by asking for the TOTP code.
"""

from __future__ import annotations

import uuid

from django.conf import settings
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
    # Checked after the role so a non-admin never learns MFA exists here.
    if settings.ADMIN_REQUIRE_MFA and getattr(info.context, "aal", None) != "aal2":
        raise GraphQLError(
            "Two-factor verification required",
            extensions={"code": "MFA_REQUIRED"},
        )
    return user_id


def is_admin(user_id: uuid.UUID) -> bool:
    return bool(
        AccountProfile.objects.filter(user_id=user_id, is_admin=True).exists()
    )

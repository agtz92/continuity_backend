"""Cross-service helper for invalidating the assistant's skinny-context cache.

Kept in a private module so individual service files don't all reimplement
the lazy-import dance (the assistant app is optional from the services'
perspective — they still work in narrow tests that don't install it).
"""

from __future__ import annotations

import uuid


def bump_context_version(user_id: uuid.UUID) -> None:
    """Increment AccountProfile.context_version so the cached skinny-context
    payload for this user is rebuilt on the next assistant turn.

    Silently no-ops if the assistant app is not installed.
    """
    try:
        from django.db.models import F

        from core.assistant.models import AccountProfile
    except Exception:
        return
    AccountProfile.objects.filter(user_id=user_id).update(
        context_version=F("context_version") + 1
    )

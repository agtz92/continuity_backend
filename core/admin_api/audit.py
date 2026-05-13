"""Helper for writing audit log entries from admin mutations."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from .models import AdminAuditLog


def record(
    *,
    actor_user_id: uuid.UUID,
    action: str,
    target_type: str = "",
    target_id: Optional[Any] = None,
    payload: Optional[dict] = None,
) -> AdminAuditLog:
    return AdminAuditLog.objects.create(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else "",
        payload=payload or {},
    )

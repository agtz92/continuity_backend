"""Admin-side persisted models.

Currently just the audit log. CMS content lives in core.cms.
"""

from __future__ import annotations

import uuid

from django.db import models


class AdminAuditLog(models.Model):
    """Append-only log of admin actions.

    `payload` stores a dict like {"before": ..., "after": ...} for
    updates, or just the relevant inputs for creates/deletes. Kept
    small (no model snapshots) to stay cheap and readable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_user_id = models.UUIDField(db_index=True)
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["actor_user_id", "-created"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

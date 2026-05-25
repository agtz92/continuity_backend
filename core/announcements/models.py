"""Admin-managed in-app banners.

Audience targeting:
- `audience_plans` empty + `audience_user_ids` empty → shown to everyone
- `audience_plans` non-empty → shown only to users on those plans
- `audience_user_ids` non-empty → shown only to those user_ids
- Both non-empty → union (user matches plan OR user_id)

Time window:
- If `starts_at` is null → live from creation
- If `ends_at` is null → live indefinitely
- Both nullable so admin can schedule and auto-expire

Lifecycle:
- `status="draft"` → not shown to anyone, even with active dates
- `status="published"` → shown to matching audience within window
- `status="archived"` → hidden forever (kept for audit)
"""

from __future__ import annotations

import uuid

from django.db import models


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARN = "warn", "Warning"
    ERROR = "error", "Error"


class Status(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class Announcement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.INFO
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )

    # Audience. Both nullable / empty means "everyone".
    audience_plans = models.JSONField(default=list, blank=True)  # ["free","pro"]
    audience_user_ids = models.JSONField(default=list, blank=True)  # uuid strings

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    dismissible = models.BooleanField(default=True)
    cta_label = models.CharField(max_length=64, blank=True, default="")
    cta_url = models.CharField(max_length=500, blank=True, default="")

    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "starts_at", "ends_at"]),
        ]

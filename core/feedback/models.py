"""User → admin bug reports (a one-way inbox).

Users submit a bug report (a common topic + a free-text message) from the
web app or the mobile app. Reports land in an admin inbox. There are NO
replies — this channel is strictly user → admin. Admins only triage the
status (new / read / archived).

The reporter's email is intentionally NOT stored here; it lives in Supabase
auth and is resolved on demand in the admin query (same pattern as
`adminUsers` / `adminSubscribers`), so it never goes stale.
"""

from __future__ import annotations

import uuid

from django.db import models


class Platform(models.TextChoices):
    WEB = "web", "Web"
    APP = "app", "App"


class Status(models.TextChoices):
    NEW = "new", "New"
    READ = "read", "Read"
    ARCHIVED = "archived", "Archived"


class BugReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(db_index=True)
    topic = models.CharField(max_length=120)
    message = models.TextField()
    platform = models.CharField(
        max_length=10, choices=Platform.choices, default=Platform.WEB
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.NEW, db_index=True
    )
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["status", "-created"]),
        ]

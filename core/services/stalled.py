"""Auto-detection of stalled projects (STATE_CLOSURE_FINAL.md D4).

An `active` project untouched for STALLED_THRESHOLD_DAYS transitions to
`stalled`. Only `active` projects auto-stall (ideas never do, D9). Runs in the
hourly cron via the `detect_stalled_projects` management command. The in-app
StalledProjectModal then prompts the user to keep / pause / kill.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from ..models import ActivityKind, Project, ProjectStatus
from ._cache import bump_context_version
from .activities import log_event

STALLED_THRESHOLD_DAYS = 14


def detect_and_mark_stalled(user_id: Optional[uuid.UUID] = None) -> list[Project]:
    """Mark active projects idle >= threshold as stalled. Returns the list moved.

    If `user_id` is given, only that user's projects are checked (used by tests
    and on-demand runs); otherwise it sweeps every user.
    """
    cutoff = timezone.now() - timedelta(days=STALLED_THRESHOLD_DAYS)
    qs = Project.objects.filter(status=ProjectStatus.ACTIVE, last_activity__lt=cutoff)
    if user_id:
        qs = qs.filter(user_id=user_id)

    changed = list(qs)
    for project in changed:
        previous = project.status
        project.status = ProjectStatus.STALLED
        project.stalled_at = timezone.now()
        project.save(update_fields=["status", "stalled_at"])
        log_event(
            project.user_id,
            kind=ActivityKind.PROJECT_STATUS_CHANGED,
            entity_id=project.id,
            entity_title=project.name,
            project_id=project.id,
            previous_value=previous,
            new_value=ProjectStatus.STALLED,
            note=f"auto-detected after {STALLED_THRESHOLD_DAYS} days idle",
        )

    for uid in {p.user_id for p in changed}:
        bump_context_version(uid)
    return changed

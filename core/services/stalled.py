"""Auto-detection of stalled projects (docs/_archive/state-closure/STATE_CLOSURE_FINAL.md D4).

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

from ..models import ActivityKind, Project, ProjectStatus, StalledSweepState
from ._cache import bump_context_version
from .activities import log_event

STALLED_THRESHOLD_DAYS = 14


def detect_and_mark_stalled(user_id: Optional[uuid.UUID] = None) -> list[Project]:
    """Mark active projects idle >= threshold as stalled. Returns the list moved.

    If `user_id` is given, only that user's projects are checked (used by tests
    and on-demand runs); otherwise it sweeps every user.

    Avalanche guard (docs/_archive/state-closure/STATE_CLOSURE_FINAL.md §0.1, cutoff): idle is measured from
    `max(last_activity, cutoff_at)`, where `cutoff_at` is stamped automatically on
    the first run. Because the cutoff is global, this is equivalent to stalling
    NOTHING until STALLED_THRESHOLD_DAYS after the feature went live, then
    behaving normally — so existing old projects never get stalled en masse.
    """
    now = timezone.now()
    threshold = now - timedelta(days=STALLED_THRESHOLD_DAYS)

    state, _ = StalledSweepState.objects.get_or_create(
        pk=1, defaults={"cutoff_at": now}
    )
    if state.cutoff_at is None:
        state.cutoff_at = now
        state.save(update_fields=["cutoff_at", "updated_at"])
    # Still inside the grace window: every project's effective idle clock starts
    # at the cutoff, so nothing can be 14 days idle yet.
    if state.cutoff_at > threshold:
        return []

    qs = Project.objects.filter(status=ProjectStatus.ACTIVE, last_activity__lt=threshold)
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

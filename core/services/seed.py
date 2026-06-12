"""One-time example content for brand-new users.

On a user's first touch we seed a small, opinionated set of example content —
one paused project with three tasks, one weekly routine and one idea — so the
app never opens empty. The copy is intentional onboarding voice, not lorem.

Idempotency & the "existing users" rule live here:

- We decide exactly once per user, recorded by `OnboardingProgress.example_seeded_at`.
  Once set, this is a no-op — so deleting the examples never re-seeds them.
- If the user already owns a project, they are NOT new (an existing user who
  already shipped their first project, or anyone mid-flight): we record the
  decision and create nothing.

Seeding goes through the normal create services so Activity events, quotas and
the context-version bump all fire exactly as if the user had created the rows.
"""

from __future__ import annotations

import datetime as dt
import uuid

from django.db import transaction
from django.utils import timezone

from ..models import OnboardingProgress, Project, RecurrenceType
from . import ideas as ideas_svc
from . import projects as projects_svc
from . import quick_notes as quick_notes_svc
from . import routines as routines_svc
from . import tasks as tasks_svc

SUNDAY = 6  # Python date.weekday(): Monday=0 … Sunday=6


def seed_example_content(user_id: uuid.UUID) -> bool:
    """Seed example content for a new user. Idempotent.

    Returns True if content was created, False if it was skipped (already
    decided, or the user is not new).
    """
    progress, _ = OnboardingProgress.objects.get_or_create(user_id=user_id)
    if progress.example_seeded_at is not None:
        return False

    now = timezone.now()

    with transaction.atomic():
        # Re-read under the row so two concurrent first-touches don't both seed.
        progress = OnboardingProgress.objects.select_for_update().get(
            user_id=user_id
        )
        if progress.example_seeded_at is not None:
            return False

        # Existing user (already has a project) → decide "no seed", once.
        if Project.objects.filter(user_id=user_id).exists():
            progress.example_seeded_at = now
            progress.save(update_fields=["example_seeded_at", "updated_at"])
            return False

        _create_example_content(user_id, now)

        progress.example_seeded_at = now
        progress.save(update_fields=["example_seeded_at", "updated_at"])

    return True


def _create_example_content(user_id: uuid.UUID, now: dt.datetime) -> None:
    project = projects_svc.create_project(
        user_id,
        name="Ship the personal site redesign",
        description=(
            "Paused 18 days ago. You stopped because the hero copy felt flat "
            "and you didn't want to ship something generic. The design is done. "
            "It's the words that are stuck. Next step: write 3 opening lines, "
            "pick the least clever one, move on."
        ),
        why="Today you'll close your first of many projects",
        next_step="Write 3 opening lines, pick the least clever one, move on.",
        status="paused",
    )

    # Three tasks on different dates: one overdue, one today, one ahead.
    tasks_svc.create_task(
        user_id,
        title="Write opening line #1 — the honest one",
        project_id=project.id,
        due_date=now - dt.timedelta(days=1),
    )
    tasks_svc.create_task(
        user_id,
        title="Write opening line #2 — the clever one",
        project_id=project.id,
        due_date=now,
    )
    tasks_svc.create_task(
        user_id,
        title="Write opening line #3 — the plain one, then pick",
        project_id=project.id,
        due_date=now + dt.timedelta(days=3),
    )

    routines_svc.create_routine(
        user_id,
        title="Sunday Review",
        description=(
            "Look at every active project and ask one thing: did this move this "
            "week?"
        ),
        recurrence_type=RecurrenceType.WEEKLY_DAYS,
        start_date=timezone.localdate(now),
        weekdays=[SUNDAY],
    )

    ideas_svc.create_idea(
        user_id,
        title="Newsletter for people who quit things",
        description=(
            "Captured, not started. If it's still itching in two weeks, it earns "
            "a project. Most ideas won't. That's fine. That's the point."
        ),
    )

    # One example note so the Notes tab opens with something to learn from —
    # a couple of collapsible sections (the second folded) to show the toggle.
    note = quick_notes_svc.create_quick_note(
        user_id,
        title="How to use Notes",
    )
    quick_notes_svc.add_section(
        user_id,
        note.id,
        heading="What this is",
        body=(
            "Your notebook, inside Continuity. Capture references and group them "
            "into collapsible sections. Link a note to a project, or leave it "
            "standalone. This is where Notion-shaped notes finally live next to "
            "the work they're about."
        ),
    )
    quick_notes_svc.add_section(
        user_id,
        note.id,
        heading="Try it (this section starts folded)",
        body=(
            "Click a section heading to fold or unfold it. Drag the handle to "
            "reorder. Tag a note with a category, pin the important ones, and "
            "search runs across every section's text. Delete this example when "
            "it stops being useful."
        ),
        collapsed=True,
    )

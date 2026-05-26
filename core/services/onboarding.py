"""Onboarding services. Per-user singleton row tracking onboarding progress.

The absence of a row means the user has not started; calls below lazy-create
the row on first read so callers can always assume one exists.
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.core.exceptions import ValidationError
from django.utils import timezone

from ..models import (
    OnboardingCompletionMode,
    OnboardingProgress,
    OnboardingStatus,
    TourStatus,
)

# Total visible steps in the flow. Bumping this number means the new last
# step won't auto-trigger `completed` until reached, but existing users in
# `current_step=4` will still be considered done — completion is tracked by
# `status`, not by step count.
TOTAL_STEPS = 4


def get_progress(user_id: uuid.UUID) -> OnboardingProgress:
    progress, _ = OnboardingProgress.objects.get_or_create(user_id=user_id)
    return progress


def set_step(user_id: uuid.UUID, step: int) -> OnboardingProgress:
    if step < 1 or step > TOTAL_STEPS:
        raise ValidationError(f"step must be in [1, {TOTAL_STEPS}]")
    progress = get_progress(user_id)
    # Only persist forward progress so that re-entering an earlier step on
    # the same session doesn't rewind the resume point if the user closes
    # the tab.
    if step > progress.current_step:
        progress.current_step = step
    if progress.status == OnboardingStatus.PENDING:
        progress.status = OnboardingStatus.IN_PROGRESS
    progress.save()
    return progress


def complete(
    user_id: uuid.UUID,
    mode: str = OnboardingCompletionMode.FINISHED,
) -> OnboardingProgress:
    if mode not in (
        OnboardingCompletionMode.FINISHED,
        OnboardingCompletionMode.SKIPPED,
    ):
        raise ValidationError("mode must be 'finished' or 'skipped'")
    progress = get_progress(user_id)
    progress.status = (
        OnboardingStatus.SKIPPED
        if mode == OnboardingCompletionMode.SKIPPED
        else OnboardingStatus.COMPLETED
    )
    progress.completed_via = mode
    progress.completed_at = timezone.now()
    if mode == OnboardingCompletionMode.SKIPPED:
        # Skipping the onboarding also dismisses the tour — we never want to
        # spring the tour on someone who chose to skip the intro.
        if progress.tour_status == TourStatus.PENDING:
            progress.tour_status = TourStatus.SKIPPED
            progress.tour_completed_at = timezone.now()
    progress.save()
    return progress


def mark_tour(user_id: uuid.UUID, seen: bool) -> OnboardingProgress:
    progress = get_progress(user_id)
    progress.tour_status = TourStatus.SEEN if seen else TourStatus.SKIPPED
    progress.tour_completed_at = timezone.now()
    progress.save()
    return progress

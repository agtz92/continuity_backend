"""Tests for one-time example content seeding (core/services/seed.py)."""

import pytest

from core.models import (
    Idea,
    OnboardingProgress,
    Project,
    Routine,
    Task,
)
from core.services import onboarding as onboarding_svc
from core.services.seed import seed_example_content


def _counts(user_id):
    return (
        Project.objects.filter(user_id=user_id).count(),
        Task.objects.filter(user_id=user_id).count(),
        Routine.objects.filter(user_id=user_id).count(),
        Idea.objects.filter(user_id=user_id).count(),
    )


@pytest.mark.django_db
def test_new_user_gets_example_content(user_a):
    created = seed_example_content(user_a)

    assert created is True
    assert _counts(user_a) == (1, 3, 1, 1)

    project = Project.objects.get(user_id=user_a)
    assert project.name == "Ship the personal site redesign"
    assert project.status == "paused"
    assert project.why == "Today you'll close your first of many projects"

    # Three tasks on distinct dates, all attached to the example project.
    due_dates = sorted(
        t.due_date for t in Task.objects.filter(user_id=user_a)
    )
    assert len(set(due_dates)) == 3
    assert all(t.project_id == project.id for t in project.tasks.all())

    routine = Routine.objects.get(user_id=user_a)
    assert routine.title == "Sunday Review"
    assert routine.recurrence_type == "weekly_days"
    assert routine.weekdays == [6]  # Sunday

    idea = Idea.objects.get(user_id=user_a)
    assert idea.title == "Newsletter for people who quit things"

    assert OnboardingProgress.objects.get(user_id=user_a).example_seeded_at


@pytest.mark.django_db
def test_seeding_is_idempotent(user_a):
    assert seed_example_content(user_a) is True
    # A second call (e.g. next app load) must not duplicate anything.
    assert seed_example_content(user_a) is False
    assert _counts(user_a) == (1, 3, 1, 1)


@pytest.mark.django_db
def test_existing_user_with_project_is_not_seeded(user_a, project_factory):
    # "Usuarios actuales" — already shipped their first project.
    project_factory(user_a, name="Real project")

    created = seed_example_content(user_a)

    assert created is False
    assert _counts(user_a) == (1, 0, 0, 0)  # only their own project
    assert not Project.objects.filter(
        user_id=user_a, name="Ship the personal site redesign"
    ).exists()
    # Decision recorded so we never reconsider.
    assert OnboardingProgress.objects.get(user_id=user_a).example_seeded_at


@pytest.mark.django_db
def test_deleting_examples_does_not_reseed(user_a):
    assert seed_example_content(user_a) is True

    Task.objects.filter(user_id=user_a).delete()
    Project.objects.filter(user_id=user_a).delete()
    Routine.objects.filter(user_id=user_a).delete()
    Idea.objects.filter(user_id=user_a).delete()
    assert _counts(user_a) == (0, 0, 0, 0)

    # User now has zero projects again, but the marker prevents re-seeding.
    assert seed_example_content(user_a) is False
    assert _counts(user_a) == (0, 0, 0, 0)


@pytest.mark.django_db
def test_get_progress_seeds_on_first_touch(user_a):
    # The onboarding first-read is the production hook.
    onboarding_svc.get_progress(user_a)
    assert _counts(user_a) == (1, 3, 1, 1)

    # Subsequent reads don't duplicate.
    onboarding_svc.get_progress(user_a)
    assert _counts(user_a) == (1, 3, 1, 1)

"""Tests for the prompt-cache layout."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.utils import timezone

from core.assistant import prompts
from core.assistant.models import AccountProfile


@pytest.mark.django_db
def test_system_blocks_have_cache_control(user_a, make_profile):
    make_profile(user_a)
    blocks = prompts.build_system_blocks(user_a, plan="free", now=timezone.now())
    assert len(blocks) == 2
    for b in blocks:
        assert b["type"] == "text"
        assert b.get("cache_control") == {"type": "ephemeral"}


@pytest.mark.django_db
def test_skinny_context_cached_until_version_bumps(user_a, make_profile):
    """Writes that bump context_version invalidate the cached payload."""
    from core.services import projects as projects_svc

    make_profile(user_a)
    cache.clear()
    now = timezone.now()
    projects_svc.create_project(user_a, name="One")
    first = prompts.get_or_build_skinny_context(user_a, plan="free", now=now)

    # Going through the service bumps context_version.
    projects_svc.create_project(user_a, name="Two")
    profile = AccountProfile.objects.get(user_id=user_a)
    assert profile.context_version >= 1

    second = prompts.get_or_build_skinny_context(user_a, plan="free", now=now)
    assert "Two" in second
    # The first cached block should not have included "Two".
    assert "Two" not in first


@pytest.mark.django_db
def test_skinny_context_cache_hit_for_same_version(user_a, make_profile):
    make_profile(user_a)
    cache.clear()
    now = timezone.now()
    a = prompts.get_or_build_skinny_context(user_a, plan="free", now=now)
    b = prompts.get_or_build_skinny_context(user_a, plan="free", now=now)
    assert a == b

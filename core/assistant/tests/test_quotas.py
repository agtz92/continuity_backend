"""Tests for `core.assistant.quotas`."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from core.assistant import quotas
from core.assistant.models import AccountProfile, UsageDay


@pytest.mark.django_db
def test_free_plan_default(user_a, make_profile):
    make_profile(user_a, "free")
    snap = quotas.check(user_a)
    assert snap.plan == "free"
    assert snap.daily_message_cap == 20
    assert snap.monthly_token_cap == 200_000
    assert snap.messages_sent_today == 0


@pytest.mark.django_db
def test_admin_plan_uncapped(user_a, make_profile):
    make_profile(user_a, "admin")
    snap = quotas.check(user_a)
    assert snap.daily_message_cap is None
    assert snap.monthly_token_cap is None


@pytest.mark.django_db
def test_check_raises_when_daily_cap_hit(user_a, make_profile):
    make_profile(user_a, "free")
    UsageDay.objects.create(
        user_id=user_a, date=timezone.now().date(), messages_sent=20
    )
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.check(user_a)
    assert exc.value.kind == "daily_messages"


@pytest.mark.django_db
def test_check_raises_when_monthly_cap_hit(user_a, make_profile):
    make_profile(user_a, "free")
    today = timezone.now().date()
    UsageDay.objects.create(
        user_id=user_a,
        date=today,
        messages_sent=1,
        tokens_in=150_000,
        tokens_out=60_000,
    )
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.check(user_a)
    assert exc.value.kind == "monthly_tokens"


@pytest.mark.django_db
def test_record_increments_counters(user_a, make_profile):
    make_profile(user_a, "free")
    quotas.record(user_a, tokens_in=100, tokens_out=50, cache_read_in=10)
    quotas.record(user_a, tokens_in=200, tokens_out=70, cache_read_in=20)
    today = timezone.now().date()
    row = UsageDay.objects.get(user_id=user_a, date=today)
    assert row.messages_sent == 2
    assert row.tokens_in == 300
    assert row.tokens_out == 120
    assert row.cache_read_in == 30


@pytest.mark.django_db
def test_get_or_create_profile_lazy(user_a):
    assert AccountProfile.objects.filter(user_id=user_a).count() == 0
    profile = quotas.get_or_create_profile(user_a)
    assert profile.plan == "free"

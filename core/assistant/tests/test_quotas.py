"""Tests for `core.assistant.quotas`."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from core.assistant import quotas
from core.assistant.models import AccountProfile, UsageDay


@pytest.mark.django_db
def test_free_and_pro_are_uncapped_because_they_cannot_spend(user_a, make_profile):
    """Neither tier can reach the Anthropic API, so neither carries a cap.

    Free has no assistant; Pro's chat is the deterministic catalogue,
    which never leaves our servers. A cap on an unspendable budget would
    only mislead whoever reads it next.
    """
    for plan in ("free", "pro"):
        make_profile(user_a, plan)
        snap = quotas.check(user_a)
        assert snap.plan == plan
        assert snap.daily_message_cap is None
        assert snap.monthly_token_cap is None
        assert snap.messages_sent_today == 0


@pytest.mark.django_db
def test_admin_plan_uncapped(user_a, make_profile):
    make_profile(user_a, "admin")
    snap = quotas.check(user_a)
    assert snap.daily_message_cap is None
    assert snap.monthly_token_cap is None


@pytest.mark.django_db
def test_check_raises_when_daily_cap_hit(user_a, make_profile):
    make_profile(user_a, "studio")
    UsageDay.objects.create(
        user_id=user_a, date=timezone.now().date(), messages_sent=600
    )
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.check(user_a)
    assert exc.value.kind == "daily_messages"


@pytest.mark.django_db
def test_no_plan_is_cut_off_mid_month_by_tokens(user_a, make_profile):
    """The monthly token ceiling is gone on purpose.

    It used to stop Studio mid-month with no warning and no way to see it
    coming. The daily message count is the legible limit; the deep-model
    cap bounds the expensive half.
    """
    make_profile(user_a, "studio")
    UsageDay.objects.create(
        user_id=user_a,
        date=timezone.now().date(),
        messages_sent=1,
        tokens_in=50_000_000,
        tokens_out=50_000_000,
    )
    snap = quotas.check(user_a)  # does not raise
    assert snap.monthly_token_cap is None


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
def test_signup_enrollment_closed_is_regular(user_a):
    from core.services import app_config

    app_config.set("beta_enrollment_open", False)
    profile = quotas.get_or_create_profile(user_a)
    assert profile.beta_cohort is False
    assert profile.is_billing_exempt is False
    assert profile.plan == "free"


@pytest.mark.django_db
def test_signup_enrollment_open_enrolls_beta(user_a):
    from core.services import app_config

    app_config.set("beta_enrollment_open", True)
    profile = quotas.get_or_create_profile(user_a)
    assert profile.beta_cohort is True
    assert profile.beta_status == "active"
    assert profile.beta_enrolled_at is not None
    assert profile.is_billing_exempt is True
    assert profile.billing_exempt_reason == "beta"
    assert profile.plan == "studio"


@pytest.mark.django_db
def test_signup_enrollment_open_cap_reached_is_regular(user_a):
    import uuid as _uuid

    from core.services import app_config

    app_config.set("beta_enrollment_open", True)
    app_config.set("beta_spot_cap", 1)
    # Fill the single spot with an active beta member.
    AccountProfile.objects.create(
        user_id=_uuid.uuid4(), beta_cohort=True, beta_status="active"
    )
    profile = quotas.get_or_create_profile(user_a)
    assert profile.beta_cohort is False
    assert profile.is_billing_exempt is False


@pytest.mark.django_db
def test_get_or_create_profile_existing_profile_untouched(user_a):
    AccountProfile.objects.create(
        user_id=user_a, plan="free", is_billing_exempt=False
    )
    profile = quotas.get_or_create_profile(user_a)
    assert profile.plan == "free"
    assert profile.is_billing_exempt is False

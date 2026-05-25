"""Tests for the Stripe billing services.

We don't hit Stripe — `stripe_client.get_stripe()` is patched with a fake
that records calls. The point of these tests is the *logic on our side*
when webhooks arrive and when service functions mutate Stripe.

The most important regression captured here is the "incomplete checkout
silently downgraded the user" bug we hit during local testing: a parallel
subscription in `incomplete` status used to clear the user's plan_id and
demote them to Free. The fix added two guards (only act on terminal
states, only mutate when the event's subscription_id matches the
profile's current one).
"""

from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import MagicMock, patch

import pytest

from core.assistant.models import AccountProfile, Plan
from core.billing.services import (
    NoActiveSubscriptionError,
    RetentionAlreadyUsedError,
    apply_retention_coupon,
    cancel_subscription,
    downgrade_subscription,
    reactivate_subscription,
    sync_subscription_to_profile,
)


# ---------- Fixtures ----------


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def free_profile(db, user_id):
    return AccountProfile.objects.create(
        user_id=user_id,
        plan="free",
        stripe_customer_id="cus_test",
    )


@pytest.fixture
def pro_profile(db, user_id):
    return AccountProfile.objects.create(
        user_id=user_id,
        plan="pro",
        stripe_customer_id="cus_test",
        stripe_subscription_id="sub_pro_active",
        stripe_price_id="price_pro_monthly",
    )


@pytest.fixture
def pro_settings(settings):
    settings.STRIPE_PRICE_PRO_MONTHLY = "price_pro_monthly"
    settings.STRIPE_PRICE_PRO_ANNUAL = "price_pro_annual"
    settings.STRIPE_PRICE_STUDIO_MONTHLY = "price_studio_monthly"
    settings.STRIPE_PRICE_STUDIO_ANNUAL = "price_studio_annual"
    settings.STRIPE_COUPON_RETENTION_30_3M = "ret_30"
    settings.STRIPE_COUPON_RETENTION_25_3M = "ret_25"
    settings.STRIPE_COUPON_RETENTION_20_3M = "ret_20"
    return settings


# ---------- sync_subscription_to_profile ----------


class TestSyncSubscription:
    @pytest.mark.django_db
    def test_active_pro_subscription_upgrades_profile(
        self, pro_settings, free_profile
    ):
        sync_subscription_to_profile(
            user_id=free_profile.user_id,
            customer_id="cus_test",
            subscription_id="sub_new",
            price_id="price_pro_monthly",
            status="active",
            current_period_end=int(
                dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc).timestamp()
            ),
        )
        free_profile.refresh_from_db()
        assert free_profile.plan == "pro"
        assert free_profile.stripe_subscription_id == "sub_new"
        assert free_profile.stripe_price_id == "price_pro_monthly"

    @pytest.mark.django_db
    def test_canceled_status_downgrades_to_free(self, pro_settings, pro_profile):
        sync_subscription_to_profile(
            user_id=pro_profile.user_id,
            customer_id="cus_test",
            subscription_id="sub_pro_active",  # matches current
            price_id="price_pro_monthly",
            status="canceled",
            current_period_end=None,
        )
        pro_profile.refresh_from_db()
        assert pro_profile.plan == "free"
        assert pro_profile.stripe_subscription_id == ""

    @pytest.mark.django_db
    def test_incomplete_status_does_not_downgrade(self, pro_settings, pro_profile):
        """An `incomplete` subscription (checkout still in progress or
        failed payment) is NOT terminal — must leave the active plan alone."""
        sync_subscription_to_profile(
            user_id=pro_profile.user_id,
            customer_id="cus_test",
            subscription_id="sub_pro_active",
            price_id="price_pro_monthly",
            status="incomplete",
            current_period_end=None,
        )
        pro_profile.refresh_from_db()
        assert pro_profile.plan == "pro"  # unchanged
        assert pro_profile.stripe_subscription_id == "sub_pro_active"

    @pytest.mark.django_db
    def test_terminal_event_for_stale_sub_ignored(self, pro_settings, pro_profile):
        """Regression: when a user tries to upgrade Pro → Studio and the
        new Studio checkout fails, Stripe creates a parallel `incomplete`
        sub. Webhook events for THAT sub used to wipe the user's real Pro
        plan. Now they must be ignored — only events for the profile's
        active sub can mutate plan/price."""
        sync_subscription_to_profile(
            user_id=pro_profile.user_id,
            customer_id="cus_test",
            subscription_id="sub_paralela_fallida",  # NOT the active one
            price_id="price_studio_monthly",
            status="canceled",
            current_period_end=None,
        )
        pro_profile.refresh_from_db()
        assert pro_profile.plan == "pro"  # unchanged
        assert pro_profile.stripe_subscription_id == "sub_pro_active"

    @pytest.mark.django_db
    def test_billing_exempt_never_downgraded(self, pro_settings, pro_profile):
        pro_profile.is_billing_exempt = True
        pro_profile.save()
        sync_subscription_to_profile(
            user_id=pro_profile.user_id,
            customer_id="cus_test",
            subscription_id="sub_pro_active",
            price_id="price_pro_monthly",
            status="canceled",
            current_period_end=None,
        )
        pro_profile.refresh_from_db()
        assert pro_profile.plan == "pro"  # exempt keeps the perks

    @pytest.mark.django_db
    def test_cancel_at_period_end_flag_is_synced(self, pro_settings, pro_profile):
        sync_subscription_to_profile(
            user_id=pro_profile.user_id,
            customer_id="cus_test",
            subscription_id="sub_pro_active",
            price_id="price_pro_monthly",
            status="active",
            current_period_end=int(
                dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc).timestamp()
            ),
            cancel_at_period_end=True,
        )
        pro_profile.refresh_from_db()
        assert pro_profile.cancel_at_period_end is True
        assert pro_profile.plan == "pro"  # still on plan until period end


# ---------- cancel_subscription ----------


class TestCancelSubscription:
    @pytest.mark.django_db
    @patch("core.billing.services.get_stripe")
    def test_calls_stripe_with_cancel_at_period_end(
        self, mock_get_stripe, pro_settings, pro_profile
    ):
        mock_stripe = MagicMock()
        mock_stripe.Subscription.modify.return_value = {"current_period_end": 9999}
        mock_get_stripe.return_value = mock_stripe

        cancel_subscription(
            pro_profile.user_id,
            reason="too_expensive",
            feedback_text="too pricey",
        )
        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_pro_active", cancel_at_period_end=True
        )
        pro_profile.refresh_from_db()
        assert pro_profile.cancel_at_period_end is True

    @pytest.mark.django_db
    def test_rejects_when_no_subscription(self, pro_settings, free_profile):
        with pytest.raises(NoActiveSubscriptionError):
            cancel_subscription(
                free_profile.user_id, reason="other", feedback_text=""
            )


# ---------- reactivate_subscription ----------


class TestReactivateSubscription:
    @pytest.mark.django_db
    @patch("core.billing.services.get_stripe")
    def test_clears_cancel_flag(self, mock_get_stripe, pro_settings, pro_profile):
        pro_profile.cancel_at_period_end = True
        pro_profile.save()

        mock_stripe = MagicMock()
        mock_get_stripe.return_value = mock_stripe

        reactivate_subscription(pro_profile.user_id)
        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_pro_active", cancel_at_period_end=False
        )
        pro_profile.refresh_from_db()
        assert pro_profile.cancel_at_period_end is False


# ---------- apply_retention_coupon ----------


class TestRetentionCoupon:
    @pytest.mark.django_db
    @patch("core.billing.services.get_stripe")
    def test_applies_coupon_and_marks_flag(
        self, mock_get_stripe, pro_settings, pro_profile
    ):
        mock_stripe = MagicMock()
        mock_get_stripe.return_value = mock_stripe

        result = apply_retention_coupon(
            pro_profile.user_id, reason="too_expensive", feedback_text=""
        )
        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_pro_active", discounts=[{"coupon": "ret_30"}]
        )
        assert result["coupon"] == "ret_30"
        pro_profile.refresh_from_db()
        assert pro_profile.had_retention_offer is True

    @pytest.mark.django_db
    @patch("core.billing.services.get_stripe")
    def test_second_attempt_rejected(
        self, mock_get_stripe, pro_settings, pro_profile
    ):
        mock_stripe = MagicMock()
        mock_get_stripe.return_value = mock_stripe
        pro_profile.had_retention_offer = True
        pro_profile.save()

        with pytest.raises(RetentionAlreadyUsedError):
            apply_retention_coupon(
                pro_profile.user_id, reason="too_expensive", feedback_text=""
            )
        mock_stripe.Subscription.modify.assert_not_called()


# ---------- downgrade_subscription ----------


class TestDowngradeSubscription:
    @pytest.mark.django_db
    @patch("core.billing.services.get_stripe")
    def test_switches_price_and_updates_profile(
        self, mock_get_stripe, pro_settings, user_id, db
    ):
        # Studio user wants to go down to Pro
        studio = AccountProfile.objects.create(
            user_id=user_id,
            plan="studio",
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_studio",
            stripe_price_id="price_studio_monthly",
        )

        mock_stripe = MagicMock()
        mock_stripe.Subscription.retrieve.return_value = {
            "items": {"data": [{"id": "si_1", "price": {"id": "price_studio_monthly"}}]}
        }
        mock_get_stripe.return_value = mock_stripe

        result = downgrade_subscription(
            studio.user_id, target_plan="pro", period="monthly"
        )

        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_studio",
            items=[{"id": "si_1", "price": "price_pro_monthly"}],
            proration_behavior="create_prorations",
        )
        assert result["to_plan"] == "pro"
        studio.refresh_from_db()
        assert studio.plan == "pro"
        assert studio.stripe_price_id == "price_pro_monthly"

"""Tests for the cross-source entitlement layer.

`apply_entitlement` is the only thing allowed to write which paid plan a user
has, so this file is where the rules that make a second payment channel safe
are pinned down. The scenarios that matter are the ones nobody notices until
money is involved:

- a stale event from one channel demoting a subscriber of another,
- two channels both claiming the same user (a real double charge),
- an out-of-order store redelivery shortening someone's access,
- a comp account losing its plan because a subscription behind it lapsed,
- a row with a blank source still being protected.

See `docs/integracion-pagos-web-y-movil.md`.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from core.assistant.models import AccountProfile, BillingSource, Plan
from core.billing.entitlements import (
    Entitlement,
    EntitlementStatus,
    apply_entitlement,
)


def _dt(days: int) -> dt.datetime:
    """A timestamp `days` from a fixed epoch — stable across runs."""
    return dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=days)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def web_pro(db, user_id) -> AccountProfile:
    """A Pro subscriber who bought through the web channel."""
    return AccountProfile.objects.create(
        user_id=user_id,
        plan=Plan.PRO.value,
        billing_source=BillingSource.WEB.value,
        billing_customer_id="cus_web",
        billing_transaction_id="rcb_web",
        billing_product_id="pro_monthly",
        plan_renews_at=_dt(30),
    )


@pytest.fixture
def apple_pro(db, user_id) -> AccountProfile:
    """A Pro subscriber who bought in the App Store."""
    return AccountProfile.objects.create(
        user_id=user_id,
        plan=Plan.PRO.value,
        billing_source=BillingSource.APPLE.value,
        billing_transaction_id="1000000123",
        billing_product_id="pro_monthly",
        plan_renews_at=_dt(30),
    )


def _store_event(
    user_id: uuid.UUID,
    *,
    status: EntitlementStatus = EntitlementStatus.ACTIVE,
    external_id: str = "1000000123",
    plan: str = Plan.PRO.value,
    period_end: dt.datetime | None = None,
    source: str = BillingSource.APPLE.value,
) -> Entitlement:
    return Entitlement(
        source=source,
        status=status,
        external_id=external_id,
        user_id=user_id,
        plan=plan,
        product_id="pro_monthly",
        period_end=period_end,
    )


class TestCrossSourceProtection:
    def test_stale_web_cancel_cannot_demote_an_app_store_subscriber(
        self, apple_pro
    ):
        """The scenario that motivated this layer.

        A user cancels their old web subscription after re-subscribing on
        iPhone. The web channel's terminal event arrives about a subscription we no
        longer track — acting on it would take away a plan the user is
        currently paying Apple for.
        """
        outcome = apply_entitlement(
            Entitlement(
                source=BillingSource.WEB.value,
                status=EntitlementStatus.TERMINAL,
                external_id="rcb_web_viejo",
                user_id=apple_pro.user_id,
            )
        )
        apple_pro.refresh_from_db()
        assert outcome.action == "ignored_stale"
        assert apple_pro.plan == Plan.PRO.value
        assert apple_pro.billing_source == BillingSource.APPLE.value

    def test_stale_web_renewal_cannot_repoint_an_app_store_subscriber(
        self, apple_pro
    ):
        """A late *active* event is the half the old code missed.

        The terminal branch always checked staleness; the active branch did
        not, so a delayed renewal could repoint the plan at the wrong
        subscription. Here the incoming one also ends sooner, so the store
        entitlement must win.
        """
        outcome = apply_entitlement(
            Entitlement(
                source=BillingSource.WEB.value,
                status=EntitlementStatus.ACTIVE,
                external_id="rcb_web_viejo",
                user_id=apple_pro.user_id,
                plan=Plan.STUDIO.value,
                product_id="studio_monthly",
                period_end=_dt(5),
            )
        )
        apple_pro.refresh_from_db()
        assert outcome.action == "conflict_kept_existing"
        assert apple_pro.plan == Plan.PRO.value
        assert apple_pro.billing_source == BillingSource.APPLE.value
        # The App Store subscription is left exactly as it was.
        assert apple_pro.billing_transaction_id == "1000000123"

    def test_longer_running_entitlement_takes_over(self, web_pro):
        """Conflicts resolve by which one runs longest, never by arrival order.

        An annual App Store purchase outlasting the monthly web subscription
        legitimately takes over — but the displaced one still needs a human
        to cancel and refund it, so the switch is deliberate rather than
        incidental.
        """
        outcome = apply_entitlement(
            _store_event(
                web_pro.user_id, plan=Plan.STUDIO.value, period_end=_dt(365)
            )
        )
        web_pro.refresh_from_db()
        assert outcome.action == "granted"
        assert web_pro.plan == Plan.STUDIO.value
        assert web_pro.billing_source == BillingSource.APPLE.value
        # One set of id columns, so taking over overwrites them outright —
        # there is no longer a losing channel's ids left behind to misread.
        assert web_pro.billing_transaction_id == "1000000123"
        assert web_pro.billing_product_id == "pro_monthly"

    def test_row_with_a_blank_source_is_still_protected(self, db, user_id):
        """A live subscription is protected even if the source column is blank.

        `_has_live_entitlement` keys on the transaction id rather than on
        `billing_source` precisely so that a half-written row fails safe: the
        worst outcome of a missing source is a conflict we log, whereas the
        worst outcome of "nothing tracked" is demoting someone who pays.
        """
        profile = AccountProfile.objects.create(
            user_id=user_id,
            plan=Plan.PRO.value,
            billing_customer_id="cus_legacy",
            billing_transaction_id="sub_legacy",
            billing_product_id="pro_monthly",
            plan_renews_at=_dt(30),
        )
        outcome = apply_entitlement(
            Entitlement(
                source=BillingSource.WEB.value,
                status=EntitlementStatus.TERMINAL,
                external_id="sub_otra",
                user_id=user_id,
            )
        )
        profile.refresh_from_db()
        assert outcome.action == "ignored_stale"
        assert profile.plan == Plan.PRO.value


class TestStoreOrdering:
    def test_out_of_order_renewal_does_not_shorten_access(self, apple_pro):
        """Store subscriptions only extend; an earlier end date is the past."""
        outcome = apply_entitlement(
            _store_event(apple_pro.user_id, period_end=_dt(2))
        )
        apple_pro.refresh_from_db()
        assert outcome.action == "ignored_stale"
        assert apple_pro.plan_renews_at == _dt(30)

    def test_renewal_extends_access(self, apple_pro):
        outcome = apply_entitlement(
            _store_event(apple_pro.user_id, period_end=_dt(60))
        )
        apple_pro.refresh_from_db()
        assert outcome.action == "granted"
        assert apple_pro.plan_renews_at == _dt(60)

    def test_expiration_revokes(self, apple_pro):
        outcome = apply_entitlement(
            _store_event(apple_pro.user_id, status=EntitlementStatus.TERMINAL)
        )
        apple_pro.refresh_from_db()
        assert outcome.action == "revoked"
        assert apple_pro.plan == Plan.FREE.value
        assert apple_pro.billing_source == ""
        assert apple_pro.billing_transaction_id == ""
        assert apple_pro.plan_renews_at is None


class TestExemption:
    def test_exempt_account_is_never_revoked(self, apple_pro):
        """Comp/beta accounts hold their plan by exemption, not by purchase."""
        apple_pro.is_billing_exempt = True
        apple_pro.save(update_fields=["is_billing_exempt"])

        outcome = apply_entitlement(
            _store_event(apple_pro.user_id, status=EntitlementStatus.TERMINAL)
        )
        apple_pro.refresh_from_db()
        assert outcome.action == "skipped_exempt"
        assert apple_pro.plan == Plan.PRO.value


class TestBasics:
    def test_first_purchase_grants(self, db, user_id):
        AccountProfile.objects.create(user_id=user_id, plan=Plan.FREE.value)
        outcome = apply_entitlement(
            _store_event(user_id, plan=Plan.STUDIO.value, period_end=_dt(30))
        )
        profile = AccountProfile.objects.get(user_id=user_id)
        assert outcome.action == "granted"
        assert profile.plan == Plan.STUDIO.value
        assert profile.billing_source == BillingSource.APPLE.value

    def test_ignore_status_is_a_no_op(self, web_pro):
        outcome = apply_entitlement(
            Entitlement(
                source=BillingSource.WEB.value,
                status=EntitlementStatus.IGNORE,
                external_id="sub_incompleta",
                user_id=web_pro.user_id,
            )
        )
        web_pro.refresh_from_db()
        assert outcome.action == "ignored_non_terminal"
        assert web_pro.plan == Plan.PRO.value

    def test_unknown_profile_is_reported_not_crashed(self, db):
        outcome = apply_entitlement(_store_event(uuid.uuid4(), period_end=_dt(30)))
        assert outcome.action == "no_profile"

    def test_store_purchase_found_by_transaction_id(self, apple_pro):
        """A store event whose app_user_id was lost still finds its owner."""
        outcome = apply_entitlement(
            Entitlement(
                source=BillingSource.APPLE.value,
                status=EntitlementStatus.ACTIVE,
                external_id="1000000123",
                user_id=None,
                plan=Plan.STUDIO.value,
                product_id="studio_monthly",
                period_end=_dt(60),
            )
        )
        apple_pro.refresh_from_db()
        assert outcome.action == "granted"
        assert apple_pro.plan == Plan.STUDIO.value

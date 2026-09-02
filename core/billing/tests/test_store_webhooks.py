"""Tests for the App Store / Google Play webhook endpoint.

Covers the three things that go wrong with store notifications in practice:
an unauthenticated caller, the same event delivered several times, and the
distinction between "cancelled" (auto-renew off, access continues) and
"expired" (access is over) — getting that one backwards cuts paying users
off mid-period.

See `docs/integracion-pagos-web-y-movil.md`.
"""

from __future__ import annotations

import json
import uuid

import pytest
from django.urls import reverse

from core.assistant.models import AccountProfile, BillingSource, Plan
from core.billing.models import StoreWebhookEvent


AUTH = "shared-secret-for-tests"


@pytest.fixture
def store_settings(settings):
    settings.REVENUECAT_WEBHOOK_AUTH = AUTH
    settings.STORE_PRODUCT_PRO_MONTHLY = "pro_monthly"
    settings.STORE_PRODUCT_PRO_ANNUAL = "pro_annual"
    settings.STORE_PRODUCT_STUDIO_MONTHLY = "studio_monthly"
    settings.STORE_PRODUCT_STUDIO_ANNUAL = "studio_annual"
    return settings


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def free_profile(db, user_id) -> AccountProfile:
    return AccountProfile.objects.create(user_id=user_id, plan=Plan.FREE.value)


def _payload(
    user_id: uuid.UUID,
    *,
    event_type: str = "INITIAL_PURCHASE",
    event_id: str = "evt_1",
    product_id: str = "pro_monthly",
    expiration_ms: int = 1_800_000_000_000,
    store: str = "APP_STORE",
    cancel_reason: str | None = None,
) -> dict:
    event = {
        "id": event_id,
        "type": event_type,
        "app_user_id": str(user_id),
        "product_id": product_id,
        "store": store,
        "original_transaction_id": "1000000999",
        "expiration_at_ms": expiration_ms,
    }
    if cancel_reason:
        event["cancel_reason"] = cancel_reason
    return {"api_version": "1.0", "event": event}


def _post(client, body: dict, *, auth: str | None = AUTH):
    headers = {"HTTP_AUTHORIZATION": auth} if auth is not None else {}
    return client.post(
        reverse("store-webhook"),
        data=json.dumps(body),
        content_type="application/json",
        **headers,
    )


@pytest.mark.django_db
class TestAuth:
    def test_missing_header_is_rejected(self, client, store_settings, free_profile):
        res = _post(client, _payload(free_profile.user_id), auth=None)
        assert res.status_code == 401
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.FREE.value

    def test_wrong_secret_is_rejected(self, client, store_settings, free_profile):
        res = _post(client, _payload(free_profile.user_id), auth="nope")
        assert res.status_code == 401

    def test_unconfigured_secret_rejects_everything(
        self, client, settings, free_profile
    ):
        """An open billing webhook is worse than a missing one."""
        settings.REVENUECAT_WEBHOOK_AUTH = ""
        res = _post(client, _payload(free_profile.user_id), auth="")
        assert res.status_code == 401


@pytest.mark.django_db
class TestLifecycle:
    def test_initial_purchase_grants_the_plan(
        self, client, store_settings, free_profile
    ):
        res = _post(client, _payload(free_profile.user_id))
        assert res.status_code == 200
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.PRO.value
        assert free_profile.billing_source == BillingSource.APPLE.value
        assert free_profile.billing_transaction_id == "1000000999"

    def test_play_store_purchase_maps_to_google(
        self, client, store_settings, free_profile
    ):
        res = _post(
            client,
            _payload(free_profile.user_id, store="PLAY_STORE", product_id="studio_annual"),
        )
        assert res.status_code == 200
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.STUDIO.value
        assert free_profile.billing_source == BillingSource.GOOGLE.value

    def test_web_billing_purchase_maps_to_web(
        self, client, store_settings, free_profile
    ):
        """The web channel arrives through the same webhook as the stores.

        That is the whole point of routing everything through RevenueCat:
        one endpoint, one event shape, and `billing_source` is the only thing
        that differs.
        """
        res = _post(client, _payload(free_profile.user_id, store="RC_BILLING"))
        assert res.status_code == 200
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.PRO.value
        assert free_profile.billing_source == BillingSource.WEB.value

    def test_cancellation_keeps_access_until_the_period_ends(
        self, client, store_settings, free_profile
    ):
        """"Cancelled" means auto-renew off, not "cut them off now"."""
        _post(client, _payload(free_profile.user_id))
        res = _post(
            client,
            _payload(free_profile.user_id, event_type="CANCELLATION", event_id="evt_2"),
        )
        assert res.status_code == 200
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.PRO.value
        assert free_profile.cancel_at_period_end is True

    def test_refund_revokes_immediately(self, client, store_settings, free_profile):
        _post(client, _payload(free_profile.user_id))
        res = _post(
            client,
            _payload(
                free_profile.user_id,
                event_type="CANCELLATION",
                event_id="evt_3",
                cancel_reason="CUSTOMER_SUPPORT",
            ),
        )
        assert res.status_code == 200
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.FREE.value

    def test_expiration_revokes(self, client, store_settings, free_profile):
        _post(client, _payload(free_profile.user_id))
        _post(
            client,
            _payload(free_profile.user_id, event_type="EXPIRATION", event_id="evt_4"),
        )
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.FREE.value
        assert free_profile.billing_source == ""

    def test_billing_issue_keeps_the_plan_during_grace(
        self, client, store_settings, free_profile
    ):
        """A card that just expired is a retry, not a churn."""
        _post(client, _payload(free_profile.user_id))
        _post(
            client,
            _payload(free_profile.user_id, event_type="BILLING_ISSUE", event_id="evt_5"),
        )
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.PRO.value


@pytest.mark.django_db
class TestIdempotencyAndSafety:
    def test_duplicate_delivery_is_processed_once(
        self, client, store_settings, free_profile
    ):
        body = _payload(free_profile.user_id)
        first = _post(client, body)
        second = _post(client, body)
        assert first.json()["status"] == "ok"
        assert second.json()["status"] == "duplicate"
        assert StoreWebhookEvent.objects.count() == 1

    def test_unknown_product_does_not_grant_a_plan(
        self, client, store_settings, free_profile
    ):
        """Refusing to guess: a stale product id must not hand out Studio."""
        res = _post(
            client, _payload(free_profile.user_id, product_id="mystery_tier")
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ignored"
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.FREE.value

    def test_event_is_recorded_with_its_outcome(
        self, client, store_settings, free_profile
    ):
        _post(client, _payload(free_profile.user_id))
        row = StoreWebhookEvent.objects.get(event_id="evt_1")
        assert row.outcome == "granted"
        assert row.event_type == "INITIAL_PURCHASE"
        assert row.source == BillingSource.APPLE.value
        assert row.payload["event"]["product_id"] == "pro_monthly"

    def test_anonymous_purchase_is_recorded_but_not_applied(
        self, client, store_settings, free_profile
    ):
        """Pre-login purchases can't be attributed until a TRANSFER arrives."""
        body = _payload(free_profile.user_id)
        body["event"]["app_user_id"] = "$RCAnonymousID:abc123"
        res = _post(client, body)
        assert res.status_code == 200
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.FREE.value
        assert StoreWebhookEvent.objects.filter(event_id="evt_1").exists()

    def test_test_event_is_a_no_op(self, client, store_settings, free_profile):
        res = _post(
            client, _payload(free_profile.user_id, event_type="TEST", event_id="evt_t")
        )
        assert res.status_code == 200
        free_profile.refresh_from_db()
        assert free_profile.plan == Plan.FREE.value

    def test_missing_event_id_is_rejected(self, client, store_settings):
        res = _post(client, {"event": {"type": "RENEWAL"}})
        assert res.status_code == 400

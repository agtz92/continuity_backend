"""Tests for the beta lifecycle admin GraphQL (list, pipeline, mutations)."""

from __future__ import annotations

import uuid

import pytest

from core.assistant.models import AccountProfile, BetaStatus
from core.services import app_config


@pytest.fixture
def admin_id():
    uid = uuid.uuid4()
    AccountProfile.objects.create(user_id=uid, is_admin=True)
    return uid


def _beta(**kw):
    defaults = dict(
        user_id=uuid.uuid4(),
        beta_cohort=True,
        beta_status=BetaStatus.ACTIVE,
        is_billing_exempt=True,
        billing_exempt_reason="beta",
    )
    defaults.update(kw)
    return AccountProfile.objects.create(**defaults)


@pytest.mark.django_db
def test_beta_users_lists_cohort_only(execute_query, admin_id):
    _beta()
    _beta()
    AccountProfile.objects.create(user_id=uuid.uuid4(), beta_cohort=False)  # not in cohort

    doc = "{ adminBetaUsers { userId betaStatus betaCohort isBillingExempt } }"
    res = execute_query(doc, user_id=admin_id)
    assert res.errors is None, res.errors
    rows = res.data["adminBetaUsers"]
    assert len(rows) == 2
    assert all(r["betaCohort"] for r in rows)


@pytest.mark.django_db
def test_beta_users_requires_admin(execute_query, user_a):
    AccountProfile.objects.create(user_id=user_a, is_admin=False)
    res = execute_query("{ adminBetaUsers { userId } }", user_id=user_a)
    assert res.errors is not None


@pytest.mark.django_db
def test_pipeline_counts_by_status(execute_query, admin_id):
    _beta()
    _beta(beta_status=BetaStatus.RECLAIMED, is_billing_exempt=False, billing_exempt_reason="")
    doc = """
    { adminBetaPipeline {
        statusCounts { label count }
        thresholdCounts { label count }
        recentReclaims { userId betaStatus }
    } }
    """
    res = execute_query(doc, user_id=admin_id)
    assert res.errors is None, res.errors
    data = res.data["adminBetaPipeline"]
    status = {c["label"]: c["count"] for c in data["statusCounts"]}
    assert status.get("active") == 1
    assert status.get("reclaimed") == 1
    assert len(data["recentReclaims"]) == 1


@pytest.mark.django_db
def test_set_beta_status_does_not_touch_billing(execute_query, admin_id):
    p = _beta()
    doc = """
    mutation($id: ID!) {
      adminSetBeta(userId: $id, betaStatus: "manually_paused") {
        betaStatus isBillingExempt
      }
    }
    """
    res = execute_query(doc, user_id=admin_id, variable_values={"id": str(p.user_id)})
    assert res.errors is None, res.errors
    assert res.data["adminSetBeta"]["betaStatus"] == "manually_paused"
    # Invariant: manual beta action leaves exemption untouched.
    assert res.data["adminSetBeta"]["isBillingExempt"] is True
    p.refresh_from_db()
    assert p.beta_status == "manually_paused"
    assert p.is_billing_exempt is True


@pytest.mark.django_db
def test_set_billing_exempt_with_reason(execute_query, admin_id):
    p = AccountProfile.objects.create(user_id=uuid.uuid4())
    doc = """
    mutation($id: ID!) {
      adminSetBillingExempt(userId: $id, isBillingExempt: true, reason: "investor") {
        isBillingExempt billingExemptReason
      }
    }
    """
    res = execute_query(doc, user_id=admin_id, variable_values={"id": str(p.user_id)})
    assert res.errors is None, res.errors
    assert res.data["adminSetBillingExempt"]["billingExemptReason"] == "investor"
    p.refresh_from_db()
    assert p.is_billing_exempt is True
    assert p.billing_exempt_reason == "investor"


@pytest.mark.django_db
def test_set_app_config(execute_query, admin_id):
    doc = """
    mutation {
      adminSetAppConfig(key: "beta_enrollment_open", valueJson: "true") { key valueJson }
    }
    """
    res = execute_query(doc, user_id=admin_id)
    assert res.errors is None, res.errors
    assert app_config.get_bool("beta_enrollment_open") is True


@pytest.mark.django_db
def test_set_app_config_rejects_unknown_key(execute_query, admin_id):
    doc = 'mutation { adminSetAppConfig(key: "nope", valueJson: "1") { key } }'
    res = execute_query(doc, user_id=admin_id)
    assert res.errors is not None


@pytest.mark.django_db
def test_send_test_email_to_self(execute_query, admin_id, monkeypatch):
    from core.notifications.providers.base import DeliveryResult

    monkeypatch.setattr(
        "core.admin_api.beta_schema.get_user",
        lambda uid: type("U", (), {"email": "me@x.com"})(),
    )
    sent = {}

    class _P:
        def send(self, to, subject, html, text="", **kw):
            sent["to"] = to
            sent["subject"] = subject
            return DeliveryResult(success=True, external_message_id="m1")

    monkeypatch.setattr(
        "core.notifications.providers.resend.ResendEmailProvider", _P
    )
    doc = 'mutation { adminSendTestEmail(emailId: "welcome_beta", locale: "es") }'
    res = execute_query(doc, user_id=admin_id)
    assert res.errors is None, res.errors
    assert "me@x.com" in res.data["adminSendTestEmail"]
    assert sent["subject"].startswith("[TEST]")

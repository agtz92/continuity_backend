"""Courtesy plans with an end date: set it from the admin, expire it hourly."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.utils import timezone

from core.admin_api.models import AdminAuditLog
from core.assistant.models import AccountProfile
from core.services import billing_exemptions

SET_UNTIL = """
mutation($id: ID!, $until: DateTime) {
  adminSetUserBillingExemptUntil(userId: $id, until: $until)
}
"""


@pytest.fixture
def admin_id():
    uid = uuid.uuid4()
    AccountProfile.objects.create(user_id=uid, is_admin=True)
    return uid


def _exempt(**kw):
    defaults = dict(
        user_id=uuid.uuid4(), plan="studio", is_billing_exempt=True, billing_exempt_reason="friend"
    )
    defaults.update(kw)
    return AccountProfile.objects.create(**defaults)


@pytest.mark.django_db
def test_admin_sets_and_clears_end_date(execute_query, admin_id):
    p = _exempt()
    until = (timezone.now() + dt.timedelta(days=90)).isoformat()
    res = execute_query(SET_UNTIL, user_id=admin_id, variable_values={"id": str(p.user_id), "until": until})
    assert res.errors is None, res.errors
    p.refresh_from_db()
    assert p.billing_exempt_until is not None

    res = execute_query(SET_UNTIL, user_id=admin_id, variable_values={"id": str(p.user_id), "until": None})
    assert res.errors is None, res.errors
    p.refresh_from_db()
    assert p.billing_exempt_until is None
    assert AdminAuditLog.objects.filter(action="user.set_billing_exempt_until").count() == 2


@pytest.mark.django_db
def test_rejects_past_date_and_non_exempt_user(execute_query, admin_id):
    p = _exempt()
    past = (timezone.now() - dt.timedelta(days=1)).isoformat()
    res = execute_query(SET_UNTIL, user_id=admin_id, variable_values={"id": str(p.user_id), "until": past})
    assert res.errors[0].extensions["code"] == "BAD_INPUT"

    q = AccountProfile.objects.create(user_id=uuid.uuid4())
    future = (timezone.now() + dt.timedelta(days=1)).isoformat()
    res = execute_query(SET_UNTIL, user_id=admin_id, variable_values={"id": str(q.user_id), "until": future})
    assert res.errors[0].extensions["code"] == "NOT_EXEMPT"


@pytest.mark.django_db
def test_turning_exemption_off_clears_end_date(execute_query, admin_id):
    p = _exempt(billing_exempt_until=timezone.now() + dt.timedelta(days=5))
    doc = 'mutation($id: ID!) { adminSetUserIsBillingExempt(userId: $id, isBillingExempt: false) { isBillingExempt } }'
    res = execute_query(doc, user_id=admin_id, variable_values={"id": str(p.user_id)})
    assert res.errors is None, res.errors
    p.refresh_from_db()
    assert p.billing_exempt_until is None and p.billing_exempt_reason == ""


@pytest.mark.django_db
def test_expiry_drops_unpaid_plan_to_free():
    now = timezone.now()
    due = _exempt(billing_exempt_until=now - dt.timedelta(minutes=1))
    later = _exempt(billing_exempt_until=now + dt.timedelta(days=1))
    forever = _exempt(billing_exempt_until=None)

    assert billing_exemptions.expire_due(now) == 1

    due.refresh_from_db()
    assert not due.is_billing_exempt and due.plan == "free"
    assert due.billing_exempt_until is None and due.billing_exempt_reason == ""
    later.refresh_from_db()
    forever.refresh_from_db()
    assert later.is_billing_exempt and forever.is_billing_exempt
    log = AdminAuditLog.objects.get(action="billing.exempt_expired")
    assert log.target_id == str(due.user_id) and log.payload["before"]["plan"] == "studio"


@pytest.mark.django_db
def test_expiry_keeps_a_plan_someone_pays_for_and_staff():
    now = timezone.now()
    paying = _exempt(billing_exempt_until=now - dt.timedelta(minutes=1), billing_source="web")
    staff = _exempt(billing_exempt_until=now - dt.timedelta(minutes=1), plan="admin")

    assert billing_exemptions.expire_due(now) == 2
    paying.refresh_from_db()
    staff.refresh_from_db()
    assert paying.plan == "studio" and not paying.is_billing_exempt
    assert staff.plan == "admin"

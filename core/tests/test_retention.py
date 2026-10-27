"""Retention purge: old rows lose their personal data, recent ones are untouched,
and dedupe records survive so nothing is re-sent."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.billing.models import StoreWebhookEvent
from core.feedback.models import BugReport
from core.models import OAuthConnectionEvent
from core.notifications.models import EmailSend, Notification
from core.services import retention

NOW = timezone.now()


def _age(model, pk, field, days):
    model.objects.filter(pk=pk).update(**{field: NOW - dt.timedelta(days=days)})


@pytest.mark.django_db
def test_purge_clears_or_deletes_only_expired_rows():
    uid = uuid.uuid4()
    old_n = Notification.objects.create(
        user_id=uid, channel="expo", kind="daily_digest", dedupe_key="daily:old", body="Llamar al banco"
    )
    new_n = Notification.objects.create(
        user_id=uid, channel="expo", kind="daily_digest", dedupe_key="daily:new", body="Reciente"
    )
    _age(Notification, old_n.pk, "created", retention.NOTIFICATION_BODY_DAYS + 1)

    old_e = EmailSend.objects.create(
        user_id=uid, email_id="inactivity_1", status="failed", dry_run=False,
        error="resend 422: user@example.com", resend_message_id="m1",
    )
    _age(EmailSend, old_e.pk, "created", retention.EMAIL_SEND_DETAIL_DAYS + 1)

    old_w = StoreWebhookEvent.objects.create(
        event_id="evt-old", event_type="RENEWAL", product_id="pro_monthly",
        payload={"subscriber_attributes": {"$email": "user@example.com"}},
    )
    new_w = StoreWebhookEvent.objects.create(event_id="evt-new", event_type="RENEWAL", payload={"a": 1})
    _age(StoreWebhookEvent, old_w.pk, "received_at", retention.STORE_WEBHOOK_PAYLOAD_DAYS + 1)

    archived = BugReport.objects.create(user_id=uid, topic="t", message="m", status="archived")
    open_old = BugReport.objects.create(user_id=uid, topic="t", message="m", status="new")
    for b in (archived, open_old):
        _age(BugReport, b.pk, "updated_at", retention.ARCHIVED_BUG_REPORT_DAYS + 1)

    old_ev = OAuthConnectionEvent.objects.create(user_id=uid, client_id="c", event="authorized")
    new_ev = OAuthConnectionEvent.objects.create(user_id=uid, client_id="c", event="revoked")
    _age(OAuthConnectionEvent, old_ev.pk, "created", retention.OAUTH_CONNECTION_EVENT_DAYS + 1)

    counts = retention.purge(NOW)

    assert counts == {
        "notification_bodies": 1,
        "email_send_details": 1,
        "store_webhook_payloads": 1,
        "archived_bug_reports": 1,
        "oauth_connection_events": 1,
    }
    old_n.refresh_from_db()
    assert old_n.body == "" and old_n.dedupe_key == "daily:old"  # still dedupes
    assert Notification.objects.get(pk=new_n.pk).body == "Reciente"
    old_e.refresh_from_db()
    assert (old_e.error, old_e.resend_message_id, old_e.status) == ("", "", "failed")
    old_w.refresh_from_db()
    assert old_w.payload == {} and old_w.product_id == "pro_monthly"
    assert StoreWebhookEvent.objects.get(pk=new_w.pk).payload == {"a": 1}
    assert list(BugReport.objects.values_list("pk", flat=True)) == [open_old.pk]
    assert list(OAuthConnectionEvent.objects.values_list("pk", flat=True)) == [new_ev.pk]


@pytest.mark.django_db
def test_purge_is_idempotent_via_command(capsys):
    call_command("purge_expired_data")
    call_command("purge_expired_data")
    assert "notification_bodies=0" in capsys.readouterr().out

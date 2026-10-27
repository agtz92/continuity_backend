"""Retention: how long operational records keep personal data.

The privacy policy ("Data retention") promises these periods; change both
together. Run by `purge_expired_data` in the hourly cron (cheap and idempotent).

Records whose *existence* is what prevents a duplicate (notification outbox,
email ledger) are never deleted — deleting them would re-send the push or the
email. Only their free-text columns are cleared.
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

#: Push outbox: `body` is the text the phone showed (task and project names).
NOTIFICATION_BODY_DAYS = 90
#: Email ledger: the provider's error text and message id.
EMAIL_SEND_DETAIL_DAYS = 180
#: Bug reports the admin archived (counted from when they were archived).
ARCHIVED_BUG_REPORT_DAYS = 365
#: MCP connector audit trail.
OAUTH_CONNECTION_EVENT_DAYS = 365
#: Store webhooks: the raw payload goes; the billing columns (event, product,
#: outcome, date) stay as the payment record.
STORE_WEBHOOK_PAYLOAD_DAYS = 400


def purge(now: dt.datetime | None = None) -> dict[str, int]:
    from core.billing.models import StoreWebhookEvent
    from core.feedback.models import BugReport
    from core.models import OAuthConnectionEvent
    from core.notifications.models import EmailSend, Notification

    now = now or timezone.now()

    def before(days: int) -> dt.datetime:
        return now - dt.timedelta(days=days)

    counts = {
        "notification_bodies": Notification.objects.filter(
            created__lt=before(NOTIFICATION_BODY_DAYS)
        )
        .exclude(body="", error="")
        .update(body="", error=""),
        "email_send_details": EmailSend.objects.filter(
            created__lt=before(EMAIL_SEND_DETAIL_DAYS)
        )
        .exclude(error="", resend_message_id="")
        .update(error="", resend_message_id=""),
        "store_webhook_payloads": StoreWebhookEvent.objects.filter(
            received_at__lt=before(STORE_WEBHOOK_PAYLOAD_DAYS)
        )
        .exclude(payload={})
        .update(payload={}),
    }
    counts["archived_bug_reports"], _ = BugReport.objects.filter(
        status="archived", updated_at__lt=before(ARCHIVED_BUG_REPORT_DAYS)
    ).delete()
    counts["oauth_connection_events"], _ = OAuthConnectionEvent.objects.filter(
        created__lt=before(OAUTH_CONNECTION_EVENT_DAYS)
    ).delete()
    return counts

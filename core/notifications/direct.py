"""One-off emails an admin writes by hand to a single user.

Unlike `lifecycle.deliver()`, the copy is not a template: the admin types the
subject and body in the panel. What it shares with lifecycle emails is the
transport (Resend), the `EmailSend` ledger, the `{{greeting}}`/`{{first_name}}`
tokens, and the unsubscribe footer — a user who unsubscribed from product
emails gets nothing from here either.

Replies go to `settings.EMAIL_REPLY_TO` (hello@continuu.it), with the user's
name in the Reply-To label ("continuu · Gangeswari"): the reply then arrives
addressed to that label, so the shared inbox shows who it is at a glance even
when the user writes from an address or display name we don't recognise.

Every send is its own ledger row: `email_id=DIRECT_EMAIL_ID` with a random
`episode_key`, so the idempotency constraint never blocks a second message.
`app_config.dry_run` does NOT apply: it gates the automatic cron, and this is
an explicit, confirmed admin action.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from . import lifecycle, unsubscribe
from .email_templates import render_freeform
from .models import EmailSend
from .providers.base import DeliveryResult, ProviderError
from .providers.resend import ResendEmailProvider

DIRECT_EMAIL_ID = "admin_direct"

MAX_SUBJECT_LEN = 200
MAX_BODY_LEN = 10_000


class DirectEmailError(Exception):
    """Refused before anything was sent. `code` maps to the GraphQL error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def reply_to_for(first_name: str, email: str) -> str:
    """`continuu · <name> <hello@…>`; the name falls back to the email's local
    part. Characters with meaning in an address header are dropped."""
    address = getattr(settings, "EMAIL_REPLY_TO", "")
    if not address:
        return ""
    who = re.sub(r'[<>"(),;:@\\[\]\r\n]', "", first_name or email.split("@")[0]).strip()
    return f'"continuu · {who}" <{address}>' if who else address


@dataclass
class DirectEmailOutcome:
    send: EmailSend
    to: str
    locale: str
    subject: str


def send_direct_email(user_id: uuid.UUID, subject: str, body: str) -> DirectEmailOutcome:
    """Render and send one hand-written email to `user_id`.

    Raises DirectEmailError for bad input, opted-out users and missing
    recipients (nothing sent, no ledger row). A provider failure DOES leave a
    `failed` ledger row and is reported through the returned `send.status`.
    """
    # One line only: it ends up as a mail header.
    subject = " ".join((subject or "").split())
    body = (body or "").strip()
    if not subject or not body:
        raise DirectEmailError("BAD_INPUT", "Subject and body are required")
    if len(subject) > MAX_SUBJECT_LEN or len(body) > MAX_BODY_LEN:
        raise DirectEmailError("BAD_INPUT", "Subject or body is too long")
    if unsubscribe.is_opted_out(user_id):
        raise DirectEmailError(
            "OPTED_OUT", "The user unsubscribed from product emails"
        )

    to = lifecycle._recipient_email(user_id)
    if not to:
        raise DirectEmailError("NO_EMAIL", "Could not resolve the user's email")

    locale = lifecycle._user_locale(user_id)
    ctx = lifecycle._build_context(user_id, None, locale)
    subject_r, html, text = render_freeform(subject, body, ctx)
    footer_html, footer_text, headers = unsubscribe.footer(user_id, locale)
    html = f"{html}\n{footer_html}"
    text = f"{text}\n\n--\n{footer_text}"

    row = EmailSend.objects.create(
        user_id=user_id,
        email_id=DIRECT_EMAIL_ID,
        episode_key=uuid.uuid4().hex,
        status=EmailSend.Status.FAILED,
        dry_run=False,
    )
    try:
        result = ResendEmailProvider().send(
            to,
            subject_r,
            html,
            text,
            reply_to=reply_to_for(ctx.get("first_name", ""), to),
            headers=headers,
        )
    except ProviderError as e:
        result = DeliveryResult(success=False, error=str(e))

    if result.success:
        row.status = EmailSend.Status.SENT
        row.resend_message_id = result.external_message_id
        row.sent_at = timezone.now()
        row.save(update_fields=["status", "resend_message_id", "sent_at"])
    else:
        row.error = result.error
        row.attempts = 1
        row.save(update_fields=["error", "attempts"])
    return DirectEmailOutcome(send=row, to=to, locale=locale, subject=subject_r)

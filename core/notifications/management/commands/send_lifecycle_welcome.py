"""Hourly: send the welcome email to newly-provisioned accounts.

A profile exists only after the user's first authenticated request, which
happens post-verification — so every AccountProfile without a real welcome send
is a candidate. beta_cohort picks the template. Idempotency, dry_run and the
ledger are handled by `lifecycle.deliver`.

Candidates exclude users with a status=SENT (real) or SUPPRESSED welcome — NOT
dry_run previews — so when dry_run is flipped off, previewed users still get the
real email, but launch-time existing users (marked SUPPRESSED) never do.

Only accounts younger than `MAX_AGE` get the email. Older ones without a welcome
are marked SUPPRESSED instead: "welcome, you're in" weeks late reads as a bug,
and for a beta member whose spot was already reclaimed it is plainly wrong.
(Found 2026-10-28: this command had never run in production since launch, so
every signup since 2026-06-26 was still a candidate.)

One user's failure is logged and counted, never allowed to abort the batch.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.notifications import lifecycle
from core.notifications.models import EmailSend

logger = logging.getLogger(__name__)

MAX_AGE = dt.timedelta(days=3)
TOO_OLD = "too_old"
ERROR = "error"


class Command(BaseCommand):
    help = "Send welcome_beta / welcome_regular to accounts that lack a welcome."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        from core.assistant.models import AccountProfile

        welcomed = EmailSend.objects.filter(
            email_id__in=["welcome_beta", "welcome_regular"],
            status__in=[EmailSend.Status.SENT, EmailSend.Status.SUPPRESSED],
        ).values_list("user_id", flat=True)

        candidates = (
            AccountProfile.objects.exclude(user_id__in=welcomed)
            .values_list("user_id", "beta_cohort", "created")[: options["limit"]]
        )

        cutoff = timezone.now() - MAX_AGE
        counts: dict[str, int] = {}
        for user_id, beta_cohort, created in candidates:
            email_id = "welcome_beta" if beta_cohort else "welcome_regular"
            try:
                if created < cutoff:
                    EmailSend.objects.update_or_create(
                        user_id=user_id,
                        email_id=email_id,
                        episode_key="",
                        dry_run=False,
                        defaults={
                            "status": EmailSend.Status.SUPPRESSED,
                            "error": f"account older than {MAX_AGE.days}d",
                        },
                    )
                    result = TOO_OLD
                else:
                    result = lifecycle.deliver(user_id, email_id)
            except Exception:
                logger.exception("welcome failed for %s", user_id)
                result = ERROR
            counts[result] = counts.get(result, 0) + 1

        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
        self.stdout.write(f"Lifecycle welcome: {summary}")

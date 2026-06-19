"""Hourly: send the welcome email to newly-provisioned accounts.

A profile exists only after the user's first authenticated request, which
happens post-verification — so every AccountProfile without a real welcome send
is a candidate. beta_cohort picks the template. Idempotency, dry_run and the
ledger are handled by `lifecycle.deliver`.

Candidates exclude only users with a status=SENT welcome (real), NOT dry_run
previews — so when dry_run is flipped off, previewed users still get the real
email.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.notifications import lifecycle
from core.notifications.models import EmailSend


class Command(BaseCommand):
    help = "Send welcome_beta / welcome_regular to accounts that lack a welcome."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        from core.assistant.models import AccountProfile

        welcomed = EmailSend.objects.filter(
            email_id__in=["welcome_beta", "welcome_regular"],
            status=EmailSend.Status.SENT,
        ).values_list("user_id", flat=True)

        candidates = (
            AccountProfile.objects.exclude(user_id__in=welcomed)
            .values_list("user_id", "beta_cohort")[: options["limit"]]
        )

        counts: dict[str, int] = {}
        for user_id, beta_cohort in candidates:
            email_id = "welcome_beta" if beta_cohort else "welcome_regular"
            result = lifecycle.deliver(user_id, email_id)
            counts[result] = counts.get(result, 0) + 1

        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
        self.stdout.write(f"Lifecycle welcome: {summary}")

"""Move existing beta-cohort members from `pro` to `studio`.

Why this is a command and not a data migration: it changes what real
people are entitled to, and a migration would do it silently on the next
deploy. Run it deliberately, read the dry run first.

The cohort was enrolled on the promise of the full assistant. Once Loop's
chat moved to the `studio` tier (core/assistant/tiers.py), anyone left on
`pro` would have lost it — so this brings them along. New enrolments
already land on `studio` (see `quotas._apply_enrollment_decision`).

Only touches profiles that are ALL of: in the beta cohort, status active,
and currently on `pro`. A member who is billing-exempt for another reason,
or who already pays for studio, is left alone.

    python manage.py migrate_beta_to_studio --dry-run
    python manage.py migrate_beta_to_studio
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.assistant.models import AccountProfile, BetaStatus, Plan


class Command(BaseCommand):
    help = "Move active beta-cohort members from the pro plan to studio."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List who would move without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]

        qs = AccountProfile.objects.filter(
            beta_cohort=True,
            beta_status=BetaStatus.ACTIVE,
            plan=Plan.PRO.value,
        ).order_by("created" if _has_field("created") else "user_id")

        rows = list(qs)
        if not rows:
            self.stdout.write("No active beta members on the pro plan. Nothing to do.")
            return

        self.stdout.write(f"{len(rows)} beta member(s) on pro:")
        for p in rows:
            self.stdout.write(f"  {p.user_id}  enrolled={p.beta_enrolled_at}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing written."))
            return

        with transaction.atomic():
            moved = AccountProfile.objects.filter(
                pk__in=[p.pk for p in rows]
            ).update(plan=Plan.STUDIO.value)

        self.stdout.write(self.style.SUCCESS(f"Moved {moved} profile(s) to studio."))


def _has_field(name: str) -> bool:
    return any(f.name == name for f in AccountProfile._meta.get_fields())

"""Daily (Render cron, 15:00 UTC): drive the beta inactivity lifecycle.

Classifies every active beta member (ghost / brief / established), sends at
most one nudge/warn/reclaim email per user, and reclaims spots after the
warn + grace window. Respects app_config.dry_run (default True): in dry_run
nothing is sent and no state changes — only preview rows in email_sends.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.services import beta_lifecycle


class Command(BaseCommand):
    help = "Run the daily beta inactivity nudge/reclaim lifecycle."

    def handle(self, *args, **options):
        from core.services import app_config

        counts = beta_lifecycle.run()
        mode = "DRY_RUN" if app_config.get_bool("dry_run") else "LIVE"
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
        self.stdout.write(f"Beta lifecycle [{mode}]: {summary}")

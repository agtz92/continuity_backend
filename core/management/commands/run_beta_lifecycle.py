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
        from django.utils import timezone

        from core.services import app_config

        counts = beta_lifecycle.run()
        mode = "DRY_RUN" if app_config.get_bool("dry_run") else "LIVE"
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"

        # Heartbeat: record that (and when) the cron actually ran, so the admin
        # can tell from /admin/beta whether the Render cron is alive without
        # digging through logs. A missing/stale value = the cron isn't firing.
        app_config.set(
            "beta_lifecycle_last_run",
            {"at": timezone.now().isoformat(), "mode": mode, "summary": summary},
        )

        self.stdout.write(f"Beta lifecycle [{mode}]: {summary}")

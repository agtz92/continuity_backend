"""Drive the beta inactivity lifecycle (meant to run once a day).

Classifies every active beta member (ghost / brief / established), sends at
most one nudge/warn/reclaim email per user, and reclaims spots after the
warn + grace window. Respects app_config.dry_run (default True): in dry_run
nothing is sent and no state changes — only preview rows in email_sends.

Piggybacks on the hourly notifications cron instead of a dedicated daily
service: it's invoked every hour but does real work only during the run hour
(app_config `lifecycle_run_hour_utc`, default 15; overridable with --hour) or
under --force. The hour lives in config so it's changed from /admin/beta, never
in the cron command. The furthest-due step per user plus EmailSend idempotency
make an accidental extra run a no-op, but the hour gate keeps emails to a sane
local time and avoids 24 redundant passes a day.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.services import beta_lifecycle


class Command(BaseCommand):
    help = "Run the daily beta inactivity nudge/reclaim lifecycle."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run now regardless of the hour gate (manual/testing).",
        )
        parser.add_argument(
            "--hour",
            type=int,
            default=None,
            help="Override the UTC run hour (default: app_config lifecycle_run_hour_utc, or 15).",
        )

    def handle(self, *args, **options):
        from django.utils import timezone

        from core.services import app_config

        now = timezone.now()
        target_hour = options["hour"]
        if target_hour is None:
            target_hour = app_config.get_int("lifecycle_run_hour_utc")
        if not options["force"] and now.hour != target_hour:
            # Not the daily slot — the hourly cron invoked us; do nothing.
            self.stdout.write(
                f"Beta lifecycle: skipped (UTC hour {now.hour} != {target_hour})"
            )
            return

        counts = beta_lifecycle.run(now=now)
        mode = "DRY_RUN" if app_config.get_bool("dry_run") else "LIVE"
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"

        # Heartbeat: record that (and when) the lifecycle actually ran, so the
        # admin can tell from /admin/beta whether it's alive without digging
        # through logs. A missing/stale value = the daily pass isn't firing.
        app_config.set(
            "beta_lifecycle_last_run",
            {"at": now.isoformat(), "mode": mode, "summary": summary},
        )

        self.stdout.write(f"Beta lifecycle [{mode}]: {summary}")

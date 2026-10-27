"""Send the daily pending-tasks digest.

Designed to run hourly via Render Cron Job; respects each user's tz/hour.

Flags:
  --force                 Skip the hour gate (useful for testing).
  --user-id <uuid>        Restrict to a single user.
"""

from __future__ import annotations

import uuid
import zoneinfo

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.notifications import builders
from core.notifications.dispatcher import enqueue, push_recipients
from core.notifications.models import NotificationSettings


class Command(BaseCommand):
    help = "Send daily pending-tasks digests at each user's local hour."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--user-id")

    def handle(self, *args, **opts):
        qs = NotificationSettings.objects.filter(daily_digest_enabled=True)

        if opts.get("user_id"):
            try:
                qs = qs.filter(user_id=uuid.UUID(opts["user_id"]))
            except ValueError as e:
                raise CommandError(f"invalid --user-id: {e}")
        else:
            # Only users who can receive it: no device, no digest to build.
            qs = qs.filter(user_id__in=push_recipients())

        now_utc = timezone.now()
        sent = skipped = 0

        for setting in qs:
            try:
                tz = zoneinfo.ZoneInfo(setting.timezone)
            except zoneinfo.ZoneInfoNotFoundError:
                tz = zoneinfo.ZoneInfo("UTC")
            now_local = now_utc.astimezone(tz)

            if not opts["force"]:
                if now_local.hour != setting.daily_digest_hour:
                    skipped += 1
                    continue

            local_date = now_local.date()
            if opts["force"]:
                dedupe_key = f"daily:test:{int(now_utc.timestamp())}"
            else:
                dedupe_key = f"daily:{local_date.isoformat()}"

            msg = builders.build_daily_digest(setting.user_id, today=local_date)
            result = enqueue(
                user_id=setting.user_id,
                kind="daily_digest",
                dedupe_key=dedupe_key,
                push=msg,
            )
            sent += result.sent
            self.stdout.write(f"user={setting.user_id} -> {result}")

        self.stdout.write(
            self.style.SUCCESS(
                f"done. sent={sent} skipped_by_schedule={skipped}"
            )
        )

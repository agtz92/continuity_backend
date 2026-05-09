"""Send the weekly analytics digest.

Designed to run hourly via Render Cron Job; respects each user's tz/day/hour.

Flags:
  --force                 Skip the day/hour gate (useful for testing).
  --user-id <uuid>        Restrict to a single user.
  --all-verified          Pick every user that has at least one verified link
                          (still requires --force to bypass the schedule).
"""

from __future__ import annotations

import datetime as dt
import uuid
import zoneinfo

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.notifications import builders
from core.notifications.dispatcher import enqueue
from core.notifications.models import NotificationLink, NotificationSettings


class Command(BaseCommand):
    help = "Send weekly digests to users whose local clock matches their schedule."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--user-id")
        parser.add_argument("--all-verified", action="store_true")

    def handle(self, *args, **opts):
        qs = NotificationSettings.objects.filter(digest_enabled=True)

        if opts.get("user_id"):
            try:
                qs = qs.filter(user_id=uuid.UUID(opts["user_id"]))
            except ValueError as e:
                raise CommandError(f"invalid --user-id: {e}")
        elif opts.get("all_verified"):
            verified_users = NotificationLink.objects.filter(
                verified_at__isnull=False
            ).values_list("user_id", flat=True).distinct()
            qs = qs.filter(user_id__in=list(verified_users))

        now_utc = timezone.now()
        sent = skipped = 0

        for setting in qs:
            try:
                tz = zoneinfo.ZoneInfo(setting.timezone)
            except zoneinfo.ZoneInfoNotFoundError:
                tz = zoneinfo.ZoneInfo("UTC")
            now_local = now_utc.astimezone(tz)

            if not opts["force"]:
                if (
                    now_local.weekday() != setting.digest_day_of_week
                    or now_local.hour != setting.digest_hour
                ):
                    skipped += 1
                    continue

            iso_year, iso_week, _ = now_local.isocalendar()
            if opts["force"]:
                # Use a unique key per --force run so we always re-send
                dedupe_key = f"weekly:test:{int(now_utc.timestamp())}"
            else:
                dedupe_key = f"weekly:{iso_year}-W{iso_week:02d}"

            body = builders.build_weekly_digest(setting.user_id)
            result = enqueue(
                user_id=setting.user_id,
                kind="weekly_digest",
                dedupe_key=dedupe_key,
                body=body,
            )
            sent += result.sent
            self.stdout.write(
                f"user={setting.user_id} -> {result}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"done. sent={sent} skipped_by_schedule={skipped}"
            )
        )

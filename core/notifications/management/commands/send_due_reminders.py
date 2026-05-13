"""End-of-day warning: if items are still pending at the user's local hour,
ping them. Designed to run hourly via Render Cron Job.

Skips the send entirely (no notification, no outbox row) when the user has
nothing pending — the builder returns `None` in that case.

Flags:
  --force                 Skip the hour gate.
  --user-id <uuid>        Restrict to a single user.
  --all-verified          Pick every user that has at least one verified link.
"""

from __future__ import annotations

import uuid
import zoneinfo

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.notifications import builders, i18n as i18n_strings
from core.notifications.dispatcher import enqueue
from core.notifications.models import NotificationLink, NotificationSettings


class Command(BaseCommand):
    help = "Send a heads-up when items are still pending at the user's chosen hour."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--user-id")
        parser.add_argument("--all-verified", action="store_true")

    def handle(self, *args, **opts):
        qs = NotificationSettings.objects.filter(due_reminders_enabled=True)

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
        sent = skipped_schedule = skipped_empty = 0

        for setting in qs:
            try:
                tz = zoneinfo.ZoneInfo(setting.timezone)
            except zoneinfo.ZoneInfoNotFoundError:
                tz = zoneinfo.ZoneInfo("UTC")
            now_local = now_utc.astimezone(tz)

            if not opts["force"]:
                if now_local.hour != setting.due_reminder_hour:
                    skipped_schedule += 1
                    continue

            local_date = now_local.date()
            body = builders.build_due_warning(setting.user_id, today=local_date)
            if body is None:
                skipped_empty += 1
                self.stdout.write(f"user={setting.user_id} -> nothing pending")
                continue

            if opts["force"]:
                dedupe_key = f"due_warning:test:{int(now_utc.timestamp())}"
            else:
                dedupe_key = f"due_warning:{local_date.isoformat()}"

            s = i18n_strings.get(setting.locale or "en")
            buttons = [{"text": s["daily.openDashboard"], "url": builders.DASHBOARD_URL}]
            result = enqueue(
                user_id=setting.user_id,
                kind="due_reminder",
                dedupe_key=dedupe_key,
                body=body,
                buttons=buttons,
            )
            sent += result.sent
            self.stdout.write(f"user={setting.user_id} -> {result}")

        self.stdout.write(
            self.style.SUCCESS(
                f"done. sent={sent} "
                f"skipped_by_schedule={skipped_schedule} skipped_empty={skipped_empty}"
            )
        )

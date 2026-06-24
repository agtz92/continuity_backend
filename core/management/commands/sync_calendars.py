"""Push tasks/routines to Google Calendar for every user who enabled sync.

Runs from the hourly Render cron. The ICS subscription feed needs no cron (it's
pulled by the client); this command only drives the direct Google Calendar API
push. Failures for one user never abort the others.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from core.notifications.models import NotificationSettings
from core.services import google_calendar as gcal

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Push tasks/routines to Google Calendar for users with sync enabled."

    def handle(self, *args, **options):
        qs = NotificationSettings.objects.filter(calendar_sync_enabled=True)
        total = ok = failed = 0
        for s in qs.iterator():
            if gcal.get_connection_status(s.user_id) is None:
                continue
            total += 1
            try:
                res = gcal.sync_user(s.user_id)
                ok += 1
                logger.info("calendar sync %s: %s", s.user_id, res)
            except Exception:
                failed += 1
                logger.exception("calendar sync failed for %s", s.user_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"sync_calendars done — users={total} ok={ok} failed={failed}"
            )
        )

"""Push active admin announcements to mobile devices.

Runs hourly via Render Cron. For each user with a registered Expo token, finds
their active announcements (same audience + time-window logic as the in-app
banners) and sends a push — once per (user, announcement) via the outbox dedupe
key, so re-running is a no-op. The dispatcher gates on the user's push toggle.
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from core.announcements.services import _active_announcements
from core.assistant.models import AccountProfile, Plan
from core.notifications.dispatcher import enqueue
from core.notifications.models import ExpoPushToken


class Command(BaseCommand):
    help = "Send push notifications for active admin announcements."

    def add_arguments(self, parser):
        parser.add_argument("--user-id")

    def handle(self, *args, **opts):
        if opts.get("user_id"):
            try:
                user_ids = [uuid.UUID(opts["user_id"])]
            except ValueError as e:
                raise CommandError(f"invalid --user-id: {e}")
        else:
            user_ids = list(
                ExpoPushToken.objects.values_list("user_id", flat=True).distinct()
            )

        sent = skipped = 0
        for uid in user_ids:
            profile = AccountProfile.objects.filter(user_id=uid).first()
            plan = profile.plan if profile else Plan.FREE.value
            for ann in _active_announcements(uid, plan):
                body = f"{ann.title}\n{ann.body}" if ann.body else ann.title
                result = enqueue(
                    user_id=uid,
                    kind="manual",
                    dedupe_key=f"announcement:{ann.id}",
                    body=body,
                    channels=("expo",),
                )
                sent += result.sent
                skipped += result.skipped

        self.stdout.write(
            self.style.SUCCESS(
                f"announcement push done. users={len(user_ids)} sent={sent} skipped={skipped}"
            )
        )

"""Send a one-off test message through the dispatcher to a specific user.

    python manage.py test_notification --user-id <uuid> --body "hola"
"""

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.notifications.dispatcher import enqueue


class Command(BaseCommand):
    help = "Dispatch a manual notification to a user across their verified channels."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", required=True)
        parser.add_argument("--body", default="Hello from Continuity \\(test\\)\\.")
        parser.add_argument("--channel", help="Restrict to one channel (telegram|whatsapp).")

    def handle(self, *args, **opts):
        try:
            uid = uuid.UUID(opts["user_id"])
        except ValueError as e:
            raise CommandError(f"invalid --user-id: {e}")

        channels = (opts["channel"],) if opts.get("channel") else ()
        result = enqueue(
            user_id=uid,
            kind="manual",
            dedupe_key=f"manual:{timezone.now().isoformat()}",
            body=opts["body"],
            channels=channels,
        )
        self.stdout.write(self.style.SUCCESS(str(result)))

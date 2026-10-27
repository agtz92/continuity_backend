"""Send a one-off test push through the dispatcher to a specific user.

    python manage.py test_notification --user-id <uuid> --body "hola"
"""

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.notifications.dispatcher import enqueue
from core.notifications.providers.base import PushContent


class Command(BaseCommand):
    help = "Push a manual notification to every device of a user."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", required=True)
        parser.add_argument("--title", default="Continuity")
        parser.add_argument("--body", default="Hello from Continuity (test).")

    def handle(self, *args, **opts):
        try:
            uid = uuid.UUID(opts["user_id"])
        except ValueError as e:
            raise CommandError(f"invalid --user-id: {e}")

        result = enqueue(
            user_id=uid,
            kind="manual",
            dedupe_key=f"manual:{timezone.now().isoformat()}",
            push=PushContent(title=opts["title"], body=opts["body"]),
        )
        self.stdout.write(self.style.SUCCESS(str(result)))

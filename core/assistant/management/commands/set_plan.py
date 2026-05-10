"""Set a user's assistant plan tier.

Usage:
    python manage.py set_plan <user_id> <free|pro|admin>
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from core.assistant.models import AccountProfile, Plan


class Command(BaseCommand):
    help = "Set the AccountProfile.plan for a given user."

    def add_arguments(self, parser):
        parser.add_argument("user_id", help="Supabase user UUID")
        parser.add_argument(
            "plan",
            choices=[p.value for p in Plan],
            help="Plan tier to set",
        )

    def handle(self, *args, **options):
        try:
            user_id = uuid.UUID(options["user_id"])
        except ValueError as e:
            raise CommandError(f"Invalid user_id: {e}")

        plan = options["plan"]
        profile, created = AccountProfile.objects.update_or_create(
            user_id=user_id, defaults={"plan": plan}
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} AccountProfile for {user_id}: plan={profile.plan}")
        )

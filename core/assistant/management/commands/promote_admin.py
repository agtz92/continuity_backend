"""Promote (or demote) a Supabase user to platform admin.

Usage:
    python manage.py promote_admin <email> [--demote]

Looks up the user in Supabase by email using the service role key,
then sets AccountProfile.is_admin accordingly (lazy-creates the profile
if it doesn't exist yet).
"""

from __future__ import annotations

import uuid

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.assistant.models import AccountProfile


def _lookup_supabase_user_id(email: str) -> uuid.UUID:
    if not settings.SUPABASE_URL:
        raise CommandError("SUPABASE_URL is not configured")
    if not getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", ""):
        raise CommandError("SUPABASE_SERVICE_ROLE_KEY is not configured")

    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
    }
    resp = requests.get(url, headers=headers, params={"email": email}, timeout=10)
    if resp.status_code != 200:
        raise CommandError(
            f"Supabase admin API returned {resp.status_code}: {resp.text}"
        )
    data = resp.json()
    users = data.get("users", []) if isinstance(data, dict) else []
    match = next(
        (u for u in users if u.get("email", "").lower() == email.lower()), None
    )
    if not match:
        raise CommandError(f"No Supabase user found with email '{email}'")
    return uuid.UUID(match["id"])


class Command(BaseCommand):
    help = "Set or unset AccountProfile.is_admin for a user by email."

    def add_arguments(self, parser):
        parser.add_argument("email", help="User email (case-insensitive)")
        parser.add_argument(
            "--demote",
            action="store_true",
            help="Set is_admin=False instead of True.",
        )

    def handle(self, *args, **options):
        email = options["email"].strip()
        is_admin = not options["demote"]

        user_id = _lookup_supabase_user_id(email)
        profile, created = AccountProfile.objects.update_or_create(
            user_id=user_id, defaults={"is_admin": is_admin}
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} AccountProfile for {email} ({user_id}): "
                f"is_admin={profile.is_admin}"
            )
        )

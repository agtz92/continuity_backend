"""Delete stale MCP OAuth artifacts. Safe to run hourly alongside the digests.

- Authorization codes: expired or consumed (one-time use → never needed again).
- Refresh tokens: expired, or revoked more than a day ago (kept briefly for
  audit/debugging, then purged).
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import OAuthAuthorizationCode, OAuthRefreshToken


class Command(BaseCommand):
    help = "Purge expired/used OAuth codes and expired/revoked refresh tokens."

    def handle(self, *args, **options):
        now = timezone.now()
        grace = now - timedelta(days=1)

        codes, _ = OAuthAuthorizationCode.objects.filter(
            expires_at__lt=now
        ).delete()
        consumed, _ = OAuthAuthorizationCode.objects.filter(
            consumed_at__isnull=False
        ).delete()
        expired_rt, _ = OAuthRefreshToken.objects.filter(expires_at__lt=now).delete()
        revoked_rt, _ = OAuthRefreshToken.objects.filter(
            revoked_at__lt=grace
        ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"cleanup_oauth_tokens: codes_expired={codes} codes_consumed={consumed} "
                f"refresh_expired={expired_rt} refresh_revoked={revoked_rt}"
            )
        )

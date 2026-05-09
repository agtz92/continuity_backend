"""Register or remove the Telegram webhook URL.

Usage:
    python manage.py setup_telegram_webhook --base-url https://api.example.com
    python manage.py setup_telegram_webhook --delete
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.notifications.providers.telegram import TelegramProvider


class Command(BaseCommand):
    help = "Register the Telegram bot webhook with the configured TELEGRAM_WEBHOOK_SECRET"

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            help="Public base URL of the backend (no trailing slash). Required unless --delete.",
        )
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Remove the webhook instead of setting it.",
        )

    def handle(self, *args, **opts):
        provider = TelegramProvider()

        if opts["delete"]:
            res = provider.delete_webhook()
            self.stdout.write(self.style.SUCCESS(f"deleteWebhook → {res}"))
            return

        base_url = opts.get("base_url")
        if not base_url:
            raise CommandError("--base-url is required (e.g. https://continuity-backend.onrender.com)")

        secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
        if not secret:
            raise CommandError("TELEGRAM_WEBHOOK_SECRET is not configured")

        url = f"{base_url.rstrip('/')}/api/telegram/webhook/{secret}/"
        res = provider.set_webhook(url=url, secret_token=secret)
        self.stdout.write(self.style.SUCCESS(f"setWebhook → {url}"))
        self.stdout.write(str(res))

"""Apply the data-retention periods (`core/services/retention.py`). Safe to run
hourly alongside the digests: each run only touches rows that just expired."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.services import retention


class Command(BaseCommand):
    help = "Clear or delete operational records past their retention period."

    def handle(self, *args, **options):
        counts = retention.purge()
        summary = " ".join(f"{k}={v}" for k, v in counts.items())
        self.stdout.write(self.style.SUCCESS(f"purge_expired_data: {summary}"))

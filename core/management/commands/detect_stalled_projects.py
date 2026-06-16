"""Hourly cron: mark active projects idle 14+ days as stalled (D4)."""

from django.core.management.base import BaseCommand

from core.services.stalled import detect_and_mark_stalled


class Command(BaseCommand):
    help = "Mark active projects idle for 14+ days as stalled (auto-detection)."

    def handle(self, *args, **options):
        changed = detect_and_mark_stalled()
        self.stdout.write(
            f"Stalled detection: {len(changed)} project(s) marked stalled"
        )

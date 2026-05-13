import uuid
from django.db import models


class Channel(models.TextChoices):
    TELEGRAM = "telegram", "Telegram"
    WHATSAPP = "whatsapp", "WhatsApp"


class NotificationKind(models.TextChoices):
    WEEKLY_DIGEST = "weekly_digest", "Weekly digest"
    DAILY_DIGEST = "daily_digest", "Daily pending tasks"
    SLEEPING_ALERT = "sleeping_alert", "Sleeping project alert"
    DUE_REMINDER = "due_reminder", "Due-date reminder"
    MANUAL = "manual", "Manual / admin"


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class NotificationSettings(models.Model):
    """One row per user. Created lazily on first read of /settings/notifications.

    Despite the name, this also holds general user preferences (locale,
    timezone, admin flag). Will likely be renamed `UserPreferences` if more
    fields land that aren't notification-specific.
    """

    user_id = models.UUIDField(primary_key=True)
    locale = models.CharField(max_length=8, default="en")
    theme = models.CharField(max_length=10, default="system")
    palette = models.CharField(max_length=20, default="default")
    timezone = models.CharField(max_length=64, default="America/Mexico_City")

    digest_enabled = models.BooleanField(default=True)
    digest_day_of_week = models.PositiveSmallIntegerField(default=0)  # 0=Mon
    digest_hour = models.PositiveSmallIntegerField(default=8)  # 0-23 local

    daily_digest_enabled = models.BooleanField(default=False)
    daily_digest_hour = models.PositiveSmallIntegerField(default=8)  # 0-23 local

    sleeping_alerts_enabled = models.BooleanField(default=True)
    due_reminders_enabled = models.BooleanField(default=True)
    due_reminder_lead_hours = models.PositiveSmallIntegerField(default=24)

    manual_enabled = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)


class NotificationLink(models.Model):
    """A user's connection to a specific channel (Telegram chat_id, WhatsApp number).

    Pre-verification, only `link_token` is set; once the user completes the
    `/start <token>` flow on Telegram (or sandbox JOIN on WhatsApp), `external_id`
    and `verified_at` get populated.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(db_index=True)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    external_id = models.CharField(max_length=255, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    link_token = models.CharField(max_length=64, blank=True, default="", db_index=True)
    link_token_expires = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "channel"], name="unique_link_per_user_channel"
            )
        ]


class Notification(models.Model):
    """Outbox row. Append-only audit log + idempotency guard.

    `dedupe_key` makes re-running a cron a no-op for the same logical event
    (e.g. "weekly:2026-W19"). Status transitions: PENDING -> SENT/FAILED/SKIPPED.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(db_index=True)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    kind = models.CharField(max_length=32, choices=NotificationKind.choices)
    dedupe_key = models.CharField(max_length=128)
    body = models.TextField()
    scheduled_for = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
    )
    external_message_id = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "channel", "kind", "dedupe_key"],
                name="unique_notification_event",
            )
        ]
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
        ]

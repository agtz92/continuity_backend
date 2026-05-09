import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="NotificationSettings",
            fields=[
                ("user_id", models.UUIDField(primary_key=True, serialize=False)),
                ("timezone", models.CharField(default="America/Mexico_City", max_length=64)),
                ("digest_enabled", models.BooleanField(default=True)),
                ("digest_day_of_week", models.PositiveSmallIntegerField(default=0)),
                ("digest_hour", models.PositiveSmallIntegerField(default=8)),
                ("sleeping_alerts_enabled", models.BooleanField(default=True)),
                ("due_reminders_enabled", models.BooleanField(default=True)),
                ("due_reminder_lead_hours", models.PositiveSmallIntegerField(default=24)),
                ("manual_enabled", models.BooleanField(default=True)),
                ("is_admin", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="NotificationLink",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField(db_index=True)),
                (
                    "channel",
                    models.CharField(
                        choices=[("telegram", "Telegram"), ("whatsapp", "WhatsApp")],
                        max_length=20,
                    ),
                ),
                ("external_id", models.CharField(blank=True, default="", max_length=255)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("link_token", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("link_token_expires", models.DateTimeField(blank=True, null=True)),
                ("created", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="notificationlink",
            constraint=models.UniqueConstraint(
                fields=("user_id", "channel"), name="unique_link_per_user_channel"
            ),
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField(db_index=True)),
                (
                    "channel",
                    models.CharField(
                        choices=[("telegram", "Telegram"), ("whatsapp", "WhatsApp")],
                        max_length=20,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("weekly_digest", "Weekly digest"),
                            ("sleeping_alert", "Sleeping project alert"),
                            ("due_reminder", "Due-date reminder"),
                            ("manual", "Manual / admin"),
                        ],
                        max_length=32,
                    ),
                ),
                ("dedupe_key", models.CharField(max_length=128)),
                ("body", models.TextField()),
                ("scheduled_for", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("external_message_id", models.CharField(blank=True, default="", max_length=255)),
                ("error", models.TextField(blank=True, default="")),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-created"]},
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                fields=("user_id", "channel", "kind", "dedupe_key"),
                name="unique_notification_event",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["status", "scheduled_for"], name="notif_status_sched_idx"),
        ),
    ]

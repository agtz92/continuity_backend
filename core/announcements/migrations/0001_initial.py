import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Announcement",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("title", models.CharField(max_length=200)),
                ("body", models.TextField(blank=True, default="")),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("info", "Info"),
                            ("warn", "Warning"),
                            ("error", "Error"),
                        ],
                        default="info",
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("published", "Published"),
                            ("archived", "Archived"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=10,
                    ),
                ),
                ("audience_plans", models.JSONField(blank=True, default=list)),
                ("audience_user_ids", models.JSONField(blank=True, default=list)),
                ("starts_at", models.DateTimeField(blank=True, null=True)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("dismissible", models.BooleanField(default=True)),
                ("cta_label", models.CharField(blank=True, default="", max_length=64)),
                ("cta_url", models.CharField(blank=True, default="", max_length=500)),
                ("created_by", models.UUIDField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["status", "starts_at", "ends_at"],
                        name="announcemen_status_8b5e62_idx",
                    )
                ],
            },
        ),
    ]

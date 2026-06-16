from django.db import migrations, models

from . import _pg


ENABLE_RLS_SQL = (
    "ALTER TABLE core_onboardingprogress ENABLE ROW LEVEL SECURITY;"
)
DISABLE_RLS_SQL = (
    "ALTER TABLE core_onboardingprogress DISABLE ROW LEVEL SECURITY;"
)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_task_blocker"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="first_name",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.CreateModel(
            name="OnboardingProgress",
            fields=[
                (
                    "user_id",
                    models.UUIDField(primary_key=True, serialize=False),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("in_progress", "In progress"),
                            ("completed", "Completed"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "current_step",
                    models.PositiveSmallIntegerField(default=1),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "completed_via",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("finished", "Finished"),
                            ("skipped", "Skipped"),
                        ],
                        default="",
                        max_length=8,
                    ),
                ),
                (
                    "tour_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("seen", "Seen"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "tour_completed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        _pg.postgres_only(ENABLE_RLS_SQL, DISABLE_RLS_SQL),
    ]

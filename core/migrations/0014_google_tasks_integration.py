"""Google Tasks plugin: store per-user OAuth credentials and tag imported tasks
with their external id so re-imports don't duplicate."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_routine_effort_hours"),
    ]

    operations = [
        migrations.CreateModel(
            name="GoogleOAuthCredential",
            fields=[
                (
                    "user_id",
                    models.UUIDField(primary_key=True, serialize=False),
                ),
                ("refresh_token", models.TextField()),
                ("access_token", models.TextField(blank=True, default="")),
                ("token_expiry", models.DateTimeField(blank=True, null=True)),
                ("scopes", models.TextField(blank=True, default="")),
                ("email", models.CharField(blank=True, default="", max_length=320)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name="task",
            name="google_task_id",
            field=models.CharField(
                blank=True, db_index=True, max_length=128, null=True
            ),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.UniqueConstraint(
                condition=models.Q(("google_task_id__isnull", False)),
                fields=("user_id", "google_task_id"),
                name="uniq_user_google_task",
            ),
        ),
    ]

import uuid
from django.db import migrations, models
import django.db.models.deletion

from . import _pg

ENABLE_RLS = "ALTER TABLE IF EXISTS public.core_taskblocker ENABLE ROW LEVEL SECURITY;"
DISABLE_RLS = "ALTER TABLE IF EXISTS public.core_taskblocker DISABLE ROW LEVEL SECURITY;"


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_routine_project_fk"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskBlocker",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField(db_index=True)),
                ("created", models.DateTimeField(auto_now_add=True)),
                (
                    "blocked_task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blockers",
                        to="core.task",
                    ),
                ),
                (
                    "blocking_task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocking",
                        to="core.task",
                    ),
                ),
                ("external_description", models.CharField(blank=True, default="", max_length=500)),
            ],
            options={"ordering": ["created"]},
        ),
        _pg.postgres_only(ENABLE_RLS, DISABLE_RLS),
    ]

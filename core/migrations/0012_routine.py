"""Add Routine + RoutineOccurrence for project-independent activities
with optional recurrence (once / weekly days / every N / monthly day)."""

import uuid

import django.db.models.deletion
from django.db import migrations, models

from . import _pg


ENABLE_RLS_SQL = """
ALTER TABLE IF EXISTS public.core_routine ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.core_routineoccurrence ENABLE ROW LEVEL SECURITY;
"""

DISABLE_RLS_SQL = """
ALTER TABLE IF EXISTS public.core_routine DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.core_routineoccurrence DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_enable_rls"),
    ]

    operations = [
        migrations.AlterField(
            model_name="activity",
            name="kind",
            field=models.CharField(
                choices=[
                    ("note", "Note"),
                    ("project_created", "Project created"),
                    ("project_deleted", "Project deleted"),
                    ("project_status_changed", "Project status changed"),
                    ("project_due_date_changed", "Project due date changed"),
                    ("task_created", "Task created"),
                    ("task_completed", "Task completed"),
                    ("task_deleted", "Task deleted"),
                    ("task_due_date_changed", "Task due date changed"),
                    ("idea_created", "Idea created"),
                    ("idea_deleted", "Idea deleted"),
                    ("idea_promoted", "Idea promoted"),
                    ("routine_created", "Routine created"),
                    ("routine_completed", "Routine completed"),
                    ("routine_deleted", "Routine deleted"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="Routine",
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
                ("user_id", models.UUIDField(db_index=True)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "recurrence_type",
                    models.CharField(
                        choices=[
                            ("once", "Once"),
                            ("weekly_days", "Weekly days"),
                            ("every_n", "Every N"),
                            ("monthly_day", "Monthly day"),
                        ],
                        max_length=20,
                    ),
                ),
                ("start_date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                ("weekdays", models.JSONField(blank=True, default=list)),
                ("interval_n", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "interval_unit",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("days", "Days"),
                            ("weeks", "Weeks"),
                            ("months", "Months"),
                        ],
                        default="",
                        max_length=10,
                    ),
                ),
                ("monthly_day", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("archived", models.BooleanField(default=False)),
            ],
            options={
                "ordering": ["archived", "-created"],
            },
        ),
        migrations.AddIndex(
            model_name="routine",
            index=models.Index(
                fields=["user_id", "archived"],
                name="core_routin_user_id_0fd9ef_idx",
            ),
        ),
        migrations.CreateModel(
            name="RoutineOccurrence",
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
                ("user_id", models.UUIDField(db_index=True)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("scheduled_date", models.DateField()),
                ("completed_at", models.DateTimeField()),
                ("note", models.TextField(blank=True, default="")),
                (
                    "routine",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="occurrences",
                        to="core.routine",
                    ),
                ),
            ],
            options={
                "ordering": ["-scheduled_date"],
            },
        ),
        migrations.AddConstraint(
            model_name="routineoccurrence",
            constraint=models.UniqueConstraint(
                fields=("routine", "scheduled_date"),
                name="unique_routine_occurrence_per_day",
            ),
        ),
        migrations.AddIndex(
            model_name="routineoccurrence",
            index=models.Index(
                fields=["user_id", "-scheduled_date"],
                name="core_routin_user_id_2db5b9_idx",
            ),
        ),
        _pg.postgres_only(ENABLE_RLS_SQL, DISABLE_RLS_SQL),
    ]

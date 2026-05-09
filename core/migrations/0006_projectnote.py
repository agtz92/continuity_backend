"""Add ProjectNote (one-to-many on Project) and migrate any existing
Project.notes content into a single ProjectNote per project before dropping
the field."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


def move_notes_to_rows(apps, schema_editor):
    Project = apps.get_model("core", "Project")
    ProjectNote = apps.get_model("core", "ProjectNote")
    for p in Project.objects.exclude(notes="").exclude(notes=None):
        body = (p.notes or "").strip()
        if not body:
            continue
        ProjectNote.objects.create(
            user_id=p.user_id,
            project=p,
            title="",
            body=body,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_project_notes"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectNote",
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
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("body", models.TextField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="note_items",
                        to="core.project",
                    ),
                ),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.RunPython(move_notes_to_rows, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="project",
            name="notes",
        ),
    ]

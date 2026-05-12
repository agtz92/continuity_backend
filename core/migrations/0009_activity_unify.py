"""Unify Update + ActivityLog into a single Activity table.

Slice 1 introduced `core_activitylog` (empty in production). Slice 2
collapses it together with `core_update` (user-authored notes + the
auto-`"Completed: X"` Updates from task toggles) into one `core_activity`
table keyed by `kind`.

This migration:
1. Creates `core_activity`.
2. Backfills from `core_update`: rows whose note starts with
   "Completed: " become kind=task_completed (with entity_id resolved by
   title-within-project when possible); the rest become kind=note. The
   original `created` timestamp is preserved.
3. Drops `core_update` and `core_activitylog`.

Reverse: best-effort — re-creates the two old tables empty. Notes can be
backfilled from Activity (kind=note); task_completed events would not
round-trip perfectly. Acceptable for dev rollback.
"""

from __future__ import annotations

import uuid

from django.db import migrations, models


COMPLETED_PREFIX = "Completed: "


def backfill_activity(apps, schema_editor):
    Update = apps.get_model("core", "Update")
    Task = apps.get_model("core", "Task")
    Activity = apps.get_model("core", "Activity")

    for u in Update.objects.all().iterator():
        note_text = u.note or ""
        if note_text.startswith(COMPLETED_PREFIX):
            task_title = note_text[len(COMPLETED_PREFIX):]
            task = Task.objects.filter(
                user_id=u.user_id,
                project_id=u.project_id,
                title=task_title,
            ).first()
            row = Activity.objects.create(
                user_id=u.user_id,
                kind="task_completed",
                entity_id=task.id if task else None,
                entity_title=task_title,
                project_id=u.project_id,
            )
        else:
            row = Activity.objects.create(
                user_id=u.user_id,
                kind="note",
                note=note_text,
                project_id=u.project_id,
            )
        # `auto_now_add` clobbers `created`; override post-create.
        Activity.objects.filter(pk=row.pk).update(created=u.created)


def reverse_noop(apps, schema_editor):
    # No-op reverse: dev rollback only re-creates empty tables (via the
    # schema operations below). Reconstructing the original Update rows
    # from Activity is doable but not needed for development workflows.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_project_due_date_activitylog"),
    ]

    operations = [
        migrations.CreateModel(
            name="Activity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField(db_index=True)),
                ("created", models.DateTimeField(auto_now_add=True)),
                (
                    "kind",
                    models.CharField(
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
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("entity_id", models.UUIDField(blank=True, null=True)),
                ("entity_title", models.CharField(blank=True, default="", max_length=500)),
                ("project_id", models.UUIDField(blank=True, null=True)),
                ("target_project_id", models.UUIDField(blank=True, null=True)),
                ("note", models.TextField(blank=True, default="")),
                ("previous_value", models.TextField(blank=True, default="")),
                ("new_value", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ["-created"],
                "indexes": [
                    models.Index(fields=["user_id", "-created"], name="core_activity_user_created_idx"),
                    models.Index(fields=["user_id", "kind"], name="core_activity_user_kind_idx"),
                    models.Index(fields=["user_id", "project_id"], name="core_activity_user_project_idx"),
                ],
            },
        ),
        migrations.RunPython(backfill_activity, reverse_code=reverse_noop),
        migrations.DeleteModel(name="Update"),
        migrations.DeleteModel(name="ActivityLog"),
    ]

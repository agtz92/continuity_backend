"""Add `Task.position` (manual order inside a project) and backfill it.

The backfill numbers each project's tasks 0..N following the order the
project detail showed until now (pending first, then by due date, newest
first), so nobody sees their list jump after deploying. Standalone tasks keep
0: the position only means something inside a project.

`db_default=0` keeps a DEFAULT in the column, so a backend still running
without this field (old deploy sharing the database) can keep inserting tasks.
"""

from django.db import migrations, models


def backfill(apps, schema_editor):
    Task = apps.get_model("core", "Task")
    qs = (
        Task.objects.filter(project__isnull=False)
        .order_by("project_id", "done", "due_date", "-created", "id")
        .only("id", "project_id")
    )
    current_project = None
    idx = 0
    batch = []
    for task in qs.iterator():
        if task.project_id != current_project:
            current_project = task.project_id
            idx = 0
        task.position = idx
        idx += 1
        batch.append(task)
        if len(batch) >= 500:
            Task.objects.bulk_update(batch, ["position"])
            batch = []
    if batch:
        Task.objects.bulk_update(batch, ["position"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_seed_assistant_deep_flag"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="position",
            field=models.PositiveIntegerField(default=0, db_default=0),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]

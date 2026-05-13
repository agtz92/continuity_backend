"""Add optional effort_hours estimate to Routine, mirroring Task.effort_hours."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_routine"),
    ]

    operations = [
        migrations.AddField(
            model_name="routine",
            name="effort_hours",
            field=models.FloatField(blank=True, null=True),
        ),
    ]

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_google_tasks_integration"),
    ]

    operations = [
        migrations.AddField(
            model_name="routine",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="routines",
                to="core.project",
            ),
        ),
    ]

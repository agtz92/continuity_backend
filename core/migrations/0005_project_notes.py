from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_project_promoted_from_idea_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
    ]

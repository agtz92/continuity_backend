from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_project_priority_category_project_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='effort_hours',
            field=models.FloatField(blank=True, null=True),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_icloudcalendarcredential"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="parked_due_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="parked_due_time",
            field=models.TimeField(blank=True, null=True),
        ),
    ]

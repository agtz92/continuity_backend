from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_rename_notif_status_sched_idx_notificatio_status_d8d933_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationsettings",
            name="theme",
            field=models.CharField(default="system", max_length=10),
        ),
    ]

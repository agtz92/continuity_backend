from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_notificationsettings_theme"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationsettings",
            name="palette",
            field=models.CharField(default="default", max_length=20),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationsettings",
            name="locale",
            field=models.CharField(default="en", max_length=8),
        ),
    ]

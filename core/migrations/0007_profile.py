from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_projectnote"),
    ]

    operations = [
        migrations.CreateModel(
            name="Profile",
            fields=[
                (
                    "user_id",
                    models.UUIDField(primary_key=True, serialize=False),
                ),
                ("avatar", models.CharField(blank=True, default="", max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]

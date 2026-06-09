from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_user_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingprogress",
            name="example_seeded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

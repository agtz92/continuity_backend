from django.db import migrations, models


ENABLE_RLS_SQL = (
    "ALTER TABLE core_userpreferences ENABLE ROW LEVEL SECURITY;"
)
DISABLE_RLS_SQL = (
    "ALTER TABLE core_userpreferences DISABLE ROW LEVEL SECURITY;"
)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_onboarding"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserPreferences",
            fields=[
                (
                    "user_id",
                    models.UUIDField(primary_key=True, serialize=False),
                ),
                (
                    "today_layout",
                    models.JSONField(blank=True, default=dict),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.RunSQL(ENABLE_RLS_SQL, DISABLE_RLS_SQL),
    ]

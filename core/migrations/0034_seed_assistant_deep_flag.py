"""Seed the `assistant_deep_enabled` switch so it shows up in /admin/beta.

The admin UI lists whatever `app_config.DEFAULTS` contains merged over the
AppConfig rows, and `adminSetAppConfig` refuses keys outside DEFAULTS — so
adding the key to DEFAULTS is what makes the switch appear and be settable.
This migration just materialises the row.

Idempotent and non-destructive: `get_or_create` never clobbers a value an
admin already set, and the reverse only deletes this one key.
"""

from django.db import migrations

KEY = "assistant_deep_enabled"


def seed(apps, schema_editor):
    AppConfig = apps.get_model("core", "AppConfig")
    AppConfig.objects.get_or_create(key=KEY, defaults={"value": False})


def unseed(apps, schema_editor):
    AppConfig = apps.get_model("core", "AppConfig")
    AppConfig.objects.filter(key=KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0033_task_client_token"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

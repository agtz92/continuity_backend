"""Seed the AppConfig table with the beta-lifecycle defaults.

Idempotent: only inserts keys that are missing, so it never clobbers values an
admin has already tuned. Pulls from `core.services.app_config.DEFAULTS` so the
seed and the runtime fallbacks can never drift.
"""

from django.db import migrations


def seed(apps, schema_editor):
    AppConfig = apps.get_model("core", "AppConfig")
    from core.services.app_config import DEFAULTS

    for key, value in DEFAULTS.items():
        AppConfig.objects.get_or_create(key=key, defaults={"value": value})


def unseed(apps, schema_editor):
    AppConfig = apps.get_model("core", "AppConfig")
    from core.services.app_config import DEFAULTS

    AppConfig.objects.filter(key__in=list(DEFAULTS.keys())).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_appconfig"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

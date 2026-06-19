"""Open beta enrollment on deploy (owner decision 2026-06-15).

The seeded default for `beta_enrollment_open` is False (safe code default), but
the owner wants new signups to keep entering the beta after launch (11 users,
50 spots). This sets the deployed value to True. The owner will flip it back to
False (via /admin/beta) when they want to stop accepting new beta members.

`dry_run` stays True and `beta_spot_cap` stays 50 (both from the seed).
"""

from django.db import migrations


def open_enrollment(apps, schema_editor):
    AppConfig = apps.get_model("core", "AppConfig")
    AppConfig.objects.update_or_create(
        key="beta_enrollment_open", defaults={"value": True}
    )


def close_enrollment(apps, schema_editor):
    AppConfig = apps.get_model("core", "AppConfig")
    AppConfig.objects.update_or_create(
        key="beta_enrollment_open", defaults={"value": False}
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_seed_app_config"),
    ]

    operations = [
        migrations.RunPython(open_enrollment, close_enrollment),
    ]

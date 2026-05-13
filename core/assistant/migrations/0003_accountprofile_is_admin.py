"""Add is_admin flag to AccountProfile and backfill Plan.ADMIN rows.

Decouples authorization from billing tier: a user can be admin
regardless of plan, and the existing Plan.ADMIN value stays as a
billing tier without granting access on its own.
"""

from django.db import migrations, models


def backfill_is_admin_from_plan(apps, schema_editor):
    AccountProfile = apps.get_model("assistant", "AccountProfile")
    AccountProfile.objects.filter(plan="admin").update(is_admin=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0002_rename_assistant_c_user_id_idx_assistant_c_user_id_6ae267_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="is_admin",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.RunPython(backfill_is_admin_from_plan, noop_reverse),
    ]

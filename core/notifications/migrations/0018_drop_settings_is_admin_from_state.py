"""Phase 1 of removing NotificationSettings.is_admin.

The real admin role is AccountProfile.is_admin. This duplicate was never used
for authorization, but a second flag with the same name invites someone to
check the wrong one.

Phase 1 (this migration): the column gets a database default and leaves the
Django model. During a Render deploy the old instance keeps serving while the
new one starts. The old code still SELECTs the column, so it must exist; the
new code INSERTs without it, so it needs a database default.

Phase 2 (a later migration, after this one is live everywhere):
    ALTER TABLE notifications_notificationsettings DROP COLUMN is_admin;
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0017_lifecycle_email_opt_out"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationsettings",
            name="is_admin",
            field=models.BooleanField(default=False, db_default=False),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="notificationsettings", name="is_admin"),
            ],
            database_operations=[],
        ),
    ]

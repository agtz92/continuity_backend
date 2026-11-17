"""Phase 2 of removing NotificationSettings.is_admin: drop the column.

Phase 1 (0018) took the field out of the Django model and gave the column a
database default. 0018 is live, so no running code reads or writes the
column any more and it can go. The model state already lacks the field, so
this only touches the database.
"""

from django.db import migrations

TABLE = "notifications_notificationsettings"


def drop_column(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        columns = {
            c.name
            for c in schema_editor.connection.introspection.get_table_description(
                cursor, TABLE
            )
        }
    if "is_admin" in columns:
        schema_editor.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "is_admin"')


def add_column_back(apps, schema_editor):
    schema_editor.execute(
        f'ALTER TABLE "{TABLE}" ADD COLUMN "is_admin" boolean NOT NULL DEFAULT false'
    )


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0018_drop_settings_is_admin_from_state"),
    ]

    operations = [
        migrations.RunPython(drop_column, add_column_back),
    ]

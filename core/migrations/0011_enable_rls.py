from django.db import migrations

from . import _pg


ENABLE_SQL = """
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND rowsecurity = false
    LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
                       r.schemaname, r.tablename);
    END LOOP;
END $$;
"""

DISABLE_SQL = """
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND rowsecurity = true
    LOOP
        EXECUTE format('ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY',
                       r.schemaname, r.tablename);
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_rename_core_activity_user_created_idx_core_activi_user_id_39b9e2_idx_and_more"),
    ]

    operations = [
        _pg.postgres_only(ENABLE_SQL, DISABLE_SQL),
    ]

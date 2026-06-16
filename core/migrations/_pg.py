"""Helpers for migrations that carry Postgres-only raw SQL (e.g. Supabase RLS).

On non-Postgres backends (local SQLite for dev/test) these become no-ops so the
schema still builds and the app runs. RLS is a Supabase/Postgres feature; tenant
isolation in the app is enforced by user_id filtering in the service layer
regardless of the database backend.

Files starting with "_" are ignored by Django's migration loader, so this module
is safe to live inside the migrations package.
"""

from django.db import migrations


def postgres_only(sql, reverse_sql=""):
    """A RunPython op that runs `sql` only on PostgreSQL; no-op elsewhere."""

    def _forward(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(sql)

    def _reverse(apps, schema_editor):
        if reverse_sql and schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(reverse_sql)

    return migrations.RunPython(_forward, _reverse)

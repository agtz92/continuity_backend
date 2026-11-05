"""Lock every public table against Supabase client roles (anon/authenticated).

See core/rls.py for why this is deny-all and not per-owner policies.
"""

from django.db import migrations

from core.rls import APPLY_SQL, REVERSE_SQL

from . import _pg


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0039_avatars_vector_only"),
    ]

    operations = [
        _pg.postgres_only(APPLY_SQL, REVERSE_SQL),
    ]

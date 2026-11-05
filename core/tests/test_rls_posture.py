"""Database-level isolation: Supabase client roles can't read any table.

These run only against a Supabase Postgres (they need the ``anon`` and
``authenticated`` roles). On the default in-memory SQLite suite they skip.
To run them, point the suite at a Supabase *branch* or local ``supabase start``
database, never production:

    DATABASE_URL=postgres://... pytest core/tests/test_rls_posture.py

Production is verified read-only with ``python manage.py check_rls``.
See core/rls.py for the design.
"""

import uuid

import pytest
from django.db import connection, transaction
from django.db.utils import ProgrammingError

from core.models import Project
from core.rls import is_supabase, rls_violations

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _require_supabase():
    if not is_supabase(connection):
        pytest.skip("needs a Supabase Postgres (anon/authenticated roles)")


def test_every_public_table_is_locked():
    assert rls_violations(connection) == []


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_role_cannot_read_even_its_own_rows(role):
    owner = uuid.uuid4()
    Project.objects.create(user_id=owner, name="private")
    with pytest.raises(ProgrammingError, match="permission denied"):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                "select set_config('request.jwt.claims', %s, true)",
                [f'{{"sub": "{owner}", "role": "{role}"}}'],
            )
            cur.execute(f"set local role {role}")
            cur.execute("select count(*) from core_project")


def test_rls_blocks_rows_even_if_grants_come_back():
    """Layer 2 alone: re-grant SELECT and RLS still returns zero rows."""
    owner = uuid.uuid4()
    Project.objects.create(user_id=owner, name="private")
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("grant select on core_project to authenticated")
            cur.execute(
                "select set_config('request.jwt.claims', %s, true)",
                [f'{{"sub": "{owner}", "role": "authenticated"}}'],
            )
            cur.execute("set local role authenticated")
            cur.execute("select count(*) from core_project")
            assert cur.fetchone()[0] == 0
            cur.execute("reset role")
            cur.execute("revoke select on core_project from authenticated")

"""Los modelos y las migraciones no se desfasan.

Corre en SQLite (como el resto de la suite), así que nunca toca la base de
producción a la que apunta el ``.env`` local.
"""

import io

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_missing_migrations():
    out = io.StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out)
    except SystemExit as e:  # --check sale con 1 si hay cambios sin migrar
        pytest.fail(f"Faltan migraciones:\n{out.getvalue()}")
        raise e

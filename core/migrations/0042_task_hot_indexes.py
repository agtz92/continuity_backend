"""Índices de Task para las lecturas calientes del dashboard.

Hasta aquí Task solo tenía ``user_id``, el FK de ``project`` y dos únicos
parciales, pero el dashboard, el delta, ``completedTasks``, ``older_done`` y las
cuotas filtran por ``(user_id, done, completed_at)`` o ``(user_id, project, done)``.
Ver ``ANALISIS_CARGA_DATOS.md`` (A1).

En Postgres se crean ``CONCURRENTLY`` para no bloquear escrituras: por eso la
migración no es atómica y el SQL va aparte del estado (``SeparateDatabaseAndState``).
En SQLite (tests, dev local) el SQL es no-op; el estado igual registra los
índices para que ``makemigrations`` no los vuelva a proponer.
"""

from django.db import migrations, models
from django.db.models import Q

from . import _pg

CREATE_SQL = """
create index concurrently if not exists core_task_user_open_idx
  on core_task (user_id, due_date, created desc)
  where done = false;
create index concurrently if not exists core_task_user_donecomp_idx
  on core_task (user_id, completed_at desc nulls last, created desc)
  where done = true;
create index concurrently if not exists core_task_user_proj_done_idx
  on core_task (user_id, project_id, done);
"""

DROP_SQL = """
drop index concurrently if exists core_task_user_open_idx;
drop index concurrently if exists core_task_user_donecomp_idx;
drop index concurrently if exists core_task_user_proj_done_idx;
"""


def _split(sql):
    return [stmt.strip() + ";" for stmt in sql.strip().split(";") if stmt.strip()]


def _statements():
    # CREATE/DROP INDEX CONCURRENTLY no puede ir en un bloque de varias
    # sentencias (Postgres lo corre como transacción implícita): una por una,
    # cada creación con su borrado como reversa.
    return [
        _pg.postgres_only(create, drop)
        for create, drop in zip(_split(CREATE_SQL), _split(DROP_SQL))
    ]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0041_revoke_client_function_execute"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                *_statements(),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="task",
                    index=models.Index(
                        fields=["user_id", "due_date", "-created"],
                        condition=Q(done=False),
                        name="core_task_user_open_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="task",
                    index=models.Index(
                        models.F("user_id"),
                        models.OrderBy(
                            models.F("completed_at"), descending=True, nulls_last=True
                        ),
                        models.OrderBy(models.F("created"), descending=True),
                        condition=Q(done=True),
                        name="core_task_user_donecomp_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="task",
                    index=models.Index(
                        fields=["user_id", "project_id", "done"],
                        name="core_task_user_proj_done_idx",
                    ),
                ),
            ],
        ),
    ]

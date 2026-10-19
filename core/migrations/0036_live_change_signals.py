"""Señales en vivo: avisar al cliente cuando cambian los datos de un usuario.

Un trigger AFTER INSERT/UPDATE/DELETE en las tablas que pinta el dashboard
manda un broadcast de Supabase Realtime al canal privado ``user:<user_id>``
con ``{"table", "op"}`` y nada más. El cliente (``useLiveInvalidation`` en el
frontend) escucha ese canal y vuelve a pedir sus queries por GraphQL, así que
los permisos siguen viviendo en Django y no hay que replicarlos en RLS.

Blindajes, porque estos triggers corren dentro de CADA escritura:

- El ``realtime.send`` va dentro de ``exception when others then null``. Si el
  aviso falla (Realtime caído, función ausente en un Postgres sin Supabase), la
  escritura del usuario se guarda igual.
- Interruptor por transacción: ``set local app.live_off = '1'`` apaga los
  avisos para un proceso masivo sin tocar el esquema.
- Apagado de emergencia, sin deploy:
  ``alter table core_task disable trigger core_task_live;`` (uno por tabla).

Tablas: las que lee el dashboard y Quick Notes. Fuera a propósito
``core_interactionday`` (se escribe en cada mutation: duplicaría todo),
credenciales OAuth/iCloud, ``core_profile`` y la contabilidad interna.

Solo Postgres (``postgres_only``): en SQLite de tests/dev es no-op. La política
de ``realtime.messages`` se crea solo si existen los esquemas de Supabase.
"""

from django.db import migrations

from ._pg import postgres_only

LIVE_TABLES = [
    "core_task",
    "core_taskblocker",
    "core_project",
    "core_projectnote",
    "core_idea",
    "core_category",
    "core_routine",
    "core_routineoccurrence",
    "core_activity",
    "core_quicknote",
    "core_notesection",
]

FUNCTION_SQL = """
create or replace function public.notify_user_change() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  uid uuid;
begin
  if TG_OP = 'DELETE' then
    uid := old.user_id;
  else
    uid := new.user_id;
  end if;

  if uid is null or coalesce(current_setting('app.live_off', true), '') = '1' then
    return null;
  end if;

  begin
    perform realtime.send(
      jsonb_build_object('table', TG_TABLE_NAME, 'op', TG_OP),
      'changed',
      'user:' || uid::text,
      true
    );
  exception when others then
    -- Un aviso perdido solo retrasa el refresco hasta el polling de respaldo;
    -- una escritura perdida es inaceptable.
    null;
  end;

  return null;
end
$$;
"""

DROP_FUNCTION_SQL = "drop function if exists public.notify_user_change();"

TRIGGERS_SQL = "\n".join(
    f"""
drop trigger if exists {t}_live on public.{t};
create trigger {t}_live
  after insert or update or delete on public.{t}
  for each row execute function public.notify_user_change();
"""
    for t in LIVE_TABLES
)

DROP_TRIGGERS_SQL = "\n".join(
    f"drop trigger if exists {t}_live on public.{t};" for t in LIVE_TABLES
)

# Cada usuario solo puede unirse a su propio canal. No hay política de INSERT:
# los clientes no pueden emitir en estos canales, solo el trigger (que corre
# como dueño y no pasa por RLS).
POLICY_SQL = """
do $$
begin
  if to_regclass('realtime.messages') is not null
     and to_regprocedure('auth.uid()') is not null then
    execute 'drop policy if exists "live: user reads own channel" on realtime.messages';
    execute $p$
      create policy "live: user reads own channel"
      on realtime.messages
      for select
      to authenticated
      using (
        (select realtime.topic()) = 'user:' || (select auth.uid())::text
        and realtime.messages.extension in ('broadcast')
      )
    $p$;
  end if;
end
$$;
"""

DROP_POLICY_SQL = """
do $$
begin
  if to_regclass('realtime.messages') is not null then
    execute 'drop policy if exists "live: user reads own channel" on realtime.messages';
  end if;
end
$$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_task_position"),
    ]

    operations = [
        postgres_only(FUNCTION_SQL, DROP_FUNCTION_SQL),
        postgres_only(TRIGGERS_SQL, DROP_TRIGGERS_SQL),
        postgres_only(POLICY_SQL, DROP_POLICY_SQL),
    ]

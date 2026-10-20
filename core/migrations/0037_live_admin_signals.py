"""Señales en vivo para el portal de admin (canal ``admin``).

Las señales por usuario (0036) no sirven al admin: lo que mira (usuarios
nuevos, planes, feedback, eventos de las tiendas, auditoría) es de todos. Aquí
otra función, ``notify_admin_change()``, manda ``{table, op}`` al canal privado
``admin``, y una política de ``realtime.messages`` deja unirse solo a quien
tiene ``AccountProfile.is_admin``. El cliente es ``useAdminLive`` en
``frontend/src/components/admin/AdminShell.tsx``.

Mismos blindajes que 0036: el aviso va dentro de ``exception when others then
null`` (la escritura nunca falla por él) y respeta ``app.live_off``.

``assistant_accountprofile`` se actualiza en CADA escritura del usuario
(``bump_context_version`` sube ``context_version``): ~6 000 updates contra 26
inserts al 2026-10-20. Por eso su trigger de UPDATE solo dispara si cambia algo
que el admin pinta (plan, facturación, beta, admin), con ``WHEN``.

Apagado de emergencia, sin deploy:
``alter table public.feedback_bugreport disable trigger feedback_bugreport_admin_live;``
(uno por trigger; los de accountprofile son ``…_admin_live`` y ``…_admin_live_upd``).
"""

from django.db import migrations

from ._pg import postgres_only

# Tablas en las que cualquier cambio interesa al admin.
ADMIN_TABLES = [
    "feedback_bugreport",
    "billing_storewebhookevent",
    "admin_api_adminauditlog",
]

PROFILE = "assistant_accountprofile"
# Columnas de AccountProfile que se ven en /admin (usuarios, billing, beta).
PROFILE_COLUMNS = [
    "plan",
    "plan_renews_at",
    "billing_source",
    "cancel_at_period_end",
    "is_admin",
    "is_billing_exempt",
    "billing_exempt_until",
    "beta_cohort",
    "beta_status",
]

FUNCTION_SQL = """
create or replace function public.notify_admin_change() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if coalesce(current_setting('app.live_off', true), '') = '1' then
    return null;
  end if;

  begin
    perform realtime.send(
      jsonb_build_object('table', TG_TABLE_NAME, 'op', TG_OP),
      'changed',
      'admin',
      true
    );
  exception when others then
    -- Un aviso perdido solo retrasa el refresco del admin; una escritura
    -- perdida es inaceptable.
    null;
  end;

  return null;
end
$$;

-- La política de realtime.messages corre con el rol del usuario, que no puede
-- leer assistant_accountprofile: se pregunta por una función con privilegios.
create or replace function public.live_is_admin() returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(
    (select is_admin from public.assistant_accountprofile
      where user_id = (select auth.uid())),
    false
  );
$$;

revoke all on function public.live_is_admin() from public;
grant execute on function public.live_is_admin() to authenticated;
"""

DROP_FUNCTION_SQL = """
drop function if exists public.notify_admin_change();
drop function if exists public.live_is_admin();
"""

_changed = " or ".join(
    f"old.{c} is distinct from new.{c}" for c in PROFILE_COLUMNS
)

TRIGGERS_SQL = "\n".join(
    f"""
drop trigger if exists {t}_admin_live on public.{t};
create trigger {t}_admin_live
  after insert or update or delete on public.{t}
  for each row execute function public.notify_admin_change();
"""
    for t in ADMIN_TABLES
) + f"""
drop trigger if exists {PROFILE}_admin_live on public.{PROFILE};
create trigger {PROFILE}_admin_live
  after insert or delete on public.{PROFILE}
  for each row execute function public.notify_admin_change();

drop trigger if exists {PROFILE}_admin_live_upd on public.{PROFILE};
create trigger {PROFILE}_admin_live_upd
  after update on public.{PROFILE}
  for each row when ({_changed})
  execute function public.notify_admin_change();
"""

DROP_TRIGGERS_SQL = "\n".join(
    f"drop trigger if exists {t}_admin_live on public.{t};" for t in ADMIN_TABLES
) + f"""
drop trigger if exists {PROFILE}_admin_live on public.{PROFILE};
drop trigger if exists {PROFILE}_admin_live_upd on public.{PROFILE};
"""

POLICY_SQL = """
do $$
begin
  if to_regclass('realtime.messages') is not null
     and to_regprocedure('auth.uid()') is not null then
    execute 'drop policy if exists "live: admins read admin channel" on realtime.messages';
    execute $p$
      create policy "live: admins read admin channel"
      on realtime.messages
      for select
      to authenticated
      using (
        (select realtime.topic()) = 'admin'
        and realtime.messages.extension in ('broadcast')
        and (select public.live_is_admin())
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
    execute 'drop policy if exists "live: admins read admin channel" on realtime.messages';
  end if;
end
$$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_live_change_signals"),
        ("assistant", "0014_alter_accountprofile_billing_source"),
        ("feedback", "0001_initial"),
        ("billing", "0001_initial"),
        ("admin_api", "0001_initial"),
    ]

    operations = [
        # Políticas y triggers dependen de las funciones: se crean primero y,
        # al revertir, se quitan al final (RunPython revierte en orden inverso).
        postgres_only(FUNCTION_SQL, DROP_FUNCTION_SQL),
        postgres_only(TRIGGERS_SQL, DROP_TRIGGERS_SQL),
        postgres_only(POLICY_SQL, DROP_POLICY_SQL),
    ]

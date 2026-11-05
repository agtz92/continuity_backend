"""Client roles can't call our SECURITY DEFINER functions over /rest/v1/rpc.

Clears the Supabase advisor warnings 0028/0029. live_is_admin() stays callable
by `authenticated` because the Realtime admin-channel policy needs it.
See core/rls.py (FUNCTIONS_SQL).
"""

from django.db import migrations

from core.rls import FUNCTIONS_SQL

from . import _pg

# Reverse restores the grants Supabase's defaults had given them.
REVERSE_SQL = """
do $$
declare
  f record;
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    return;
  end if;
  for f in
    select p.oid::regprocedure as sig
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.prosecdef
      and pg_get_userbyid(p.proowner) = current_user
  loop
    execute format('grant execute on function %s to anon, authenticated', f.sig);
  end loop;
end
$$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0040_rls_deny_client_roles"),
    ]

    operations = [
        _pg.postgres_only(FUNCTIONS_SQL, REVERSE_SQL),
    ]

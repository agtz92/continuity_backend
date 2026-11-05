"""Row Level Security posture for the Supabase Postgres database.

Why deny-all instead of "owner can read own rows"
-------------------------------------------------
No client reads tables directly. Web and mobile talk to Django (GraphQL / REST),
and Django connects as ``postgres`` (BYPASSRLS), so RLS never applies to it.
Clients use Supabase only for Auth and private *broadcast* Realtime channels
(policies on ``realtime.messages``, see migrations 0036/0037).

The anon key ships inside the web and mobile bundles, so anyone can call
PostgREST / pg_graphql as ``anon`` or, with any valid login, as
``authenticated``. Those two roles must reach **nothing** in ``public``.
Writing ``user_id = auth.uid()`` policies would *open* a second read path that
bypasses every check Django does (plan gating, soft deletes, quotas), so we
don't.

Three layers, each enough on its own:
1. RLS enabled on every table (no permissive policy → no rows).
2. A RESTRICTIVE ``using (false)`` policy for anon/authenticated, so a
   permissive policy added by mistake later still can't let rows through.
3. No table/sequence privileges for anon/authenticated (PostgREST answers
   "permission denied" before RLS is even evaluated).

``apply_rls_posture`` is idempotent. It runs from migration 0040 and again after
every ``migrate`` (``CoreConfig.ready`` → post_migrate), so a table created by a
future migration is covered without anyone remembering to do it.
``python manage.py check_rls`` verifies the posture against the live database.
"""

CLIENT_ROLES = ("anon", "authenticated")
DENY_POLICY = "deny direct client access"

APPLY_SQL = f"""
do $$
declare
  r record;
begin
  if not exists (select 1 from pg_roles where rolname = 'anon')
     or not exists (select 1 from pg_roles where rolname = 'authenticated') then
    return;  -- not a Supabase database (plain local Postgres): nothing to lock
  end if;

  for r in
    select c.relname
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'p')
  loop
    execute format('alter table public.%I enable row level security', r.relname);
    if not exists (
      select 1 from pg_policies
      where schemaname = 'public' and tablename = r.relname
        and policyname = '{DENY_POLICY}'
    ) then
      execute format(
        'create policy %I on public.%I as restrictive for all '
        'to anon, authenticated using (false) with check (false)',
        '{DENY_POLICY}', r.relname);
    end if;
  end loop;

  revoke all on all tables in schema public from anon, authenticated;
  revoke all on all sequences in schema public from anon, authenticated;
  alter default privileges in schema public
    revoke all on tables from anon, authenticated;
  alter default privileges in schema public
    revoke all on sequences from anon, authenticated;
end
$$;
"""

# Reverse of the migration: drop only what we added. RLS stays on (0011 owns
# that) and grants are not restored: re-granting would re-open PostgREST.
REVERSE_SQL = f"""
do $$
declare
  r record;
begin
  for r in
    select tablename from pg_policies
    where schemaname = 'public' and policyname = '{DENY_POLICY}'
  loop
    execute format('drop policy %I on public.%I', '{DENY_POLICY}', r.tablename);
  end loop;
end
$$;
"""

# One row per public table that breaks the posture, with the reason.
VIOLATIONS_SQL = f"""
select c.relname,
       array_remove(array[
         case when not c.relrowsecurity then 'rls disabled' end,
         case when not exists (
           select 1 from pg_policies p
           where p.schemaname = 'public' and p.tablename = c.relname
             and p.policyname = '{DENY_POLICY}' and p.permissive = 'RESTRICTIVE'
         ) then 'missing restrictive deny policy' end,
         case when has_table_privilege('anon', c.oid,
           'SELECT,INSERT,UPDATE,DELETE') then 'anon has privileges' end,
         case when has_table_privilege('authenticated', c.oid,
           'SELECT,INSERT,UPDATE,DELETE') then 'authenticated has privileges' end
       ], null) as problems
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind in ('r', 'p')
order by c.relname
"""


def is_supabase(connection) -> bool:
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cur:
        cur.execute(
            "select count(*) from pg_roles where rolname in ('anon', 'authenticated')"
        )
        return cur.fetchone()[0] == 2


def apply_rls_posture(connection) -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cur:
        cur.execute(APPLY_SQL)


def rls_violations(connection) -> list[tuple[str, list[str]]]:
    """[(table, [problems])] for every public table that isn't locked down."""
    with connection.cursor() as cur:
        cur.execute(VIOLATIONS_SQL)
        return [(name, list(problems)) for name, problems in cur.fetchall() if problems]

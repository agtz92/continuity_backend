"""Read-only check that every public table is closed to Supabase client roles.

    python manage.py check_rls        # exit 1 and list offenders if any

Safe against production: it only reads pg_catalog. See core/rls.py.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.rls import is_supabase, rls_violations


class Command(BaseCommand):
    help = "Verify RLS deny-all posture on every public table (read-only)."

    def handle(self, *args, **options):
        if not is_supabase(connection):
            self.stdout.write("Not a Supabase Postgres database; nothing to check.")
            return
        bad = rls_violations(connection)
        if bad:
            for table, problems in bad:
                self.stderr.write(f"  {table}: {', '.join(problems)}")
            raise CommandError(f"{len(bad)} table(s) open to anon/authenticated")
        self.stdout.write(self.style.SUCCESS("All public tables locked to anon/authenticated."))

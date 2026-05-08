"""Project-level pytest config.

Runs BEFORE Django imports settings — sets env vars so the test run is
fully isolated from any local dev configuration:

* `DATABASE_URL` is forced to an in-memory SQLite DB so we never touch the
  developer's Postgres / Supabase database.
* `DJANGO_SECRET_KEY` and `SUPABASE_JWT_SECRET` get deterministic test
  values so JWT-signing tests are reproducible.

Anything in the developer's real environment that would otherwise leak
into a test run (live DB URL, real Supabase URL, production secret) is
overridden here.
"""

import os

# Force-override (NOT setdefault) so values from a developer's .env or
# shell environment never leak into a test run. python-decouple reads
# os.environ before the .env file, so as long as we set these BEFORE
# Django imports settings, the test values always win.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DJANGO_SECRET_KEY"] = "test-secret-key"
os.environ["DJANGO_DEBUG"] = "True"
os.environ["SUPABASE_JWT_SECRET"] = "test-jwt-secret"
# Empty so the JWKS path is skipped during tests; we exercise the HS256
# fallback with the secret above.
os.environ["SUPABASE_URL"] = ""

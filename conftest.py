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

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DJANGO_DEBUG", "True")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
# Empty so the JWKS path is skipped during tests; we exercise the HS256
# fallback with the secret above.
os.environ.setdefault("SUPABASE_URL", "")

# Backend testing guide

Tests for the Django + Strawberry GraphQL backend, using `pytest` + `pytest-django`. Designed to be **fully isolated from your dev environment**: no shared database, no live Supabase, no real network calls.

## Install

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate           # Windows PowerShell
# source .venv/bin/activate         # macOS/Linux
pip install -r requirements-dev.txt
```

`requirements-dev.txt` pulls in the full `requirements.txt` plus `pytest` and `pytest-django`.

## Run

```bash
pytest                              # full suite
pytest core/tests/test_errors.py    # one file
pytest -k "not_found"               # filter by name
pytest -v                           # verbose
pytest -x                           # stop on first failure
```

## How isolation works

* **`conftest.py`** at repo root runs *before* Django imports settings and forces:
  * `DATABASE_URL=sqlite:///:memory:` — your real Postgres / Supabase DB is never touched.
  * `SUPABASE_JWT_SECRET=test-jwt-secret` — deterministic, only used by the auth-view tests.
  * `SUPABASE_URL=""` — disables the JWKS path so we don't hit the network.
* **pytest-django** creates and tears down the test DB per session. With SQLite in-memory this is instantaneous.
* The `db` fixture (used implicitly by `@pytest.mark.django_db`) wraps each test in a transaction and rolls it back on teardown — **zero state leaks between tests, ordering doesn't matter**.
* No test makes outbound HTTP. JWT signing is local (HS256 with the test secret).

## File-by-file

### `core/tests/conftest.py`
Shared fixtures:
* `user_a`, `user_b` — fresh UUIDs per test for multi-user scenarios.
* `execute_query(document, user_id, variable_values)` — runs `schema.execute_sync` with a synthetic context. Pass `user_id=None` to simulate an unauthenticated request and exercise the resolver-level guard.
* `project_factory`, `task_factory`, `idea_factory`, `category_factory` — minimal DB factories that take a `user_id` and accept overrides.

### `core/tests/test_queries.py` — the `dashboard` query
* `test_dashboard_empty_for_new_user` — a fresh user sees empty arrays and `lastBackup=None`.
* `test_dashboard_returns_owned_data` — created projects/tasks/ideas appear in the dashboard payload with correct shape.
* `test_dashboard_isolates_users` — user A and user B both have data; each sees only their own. **Pins the multi-tenant security boundary.**

### `core/tests/test_mutations.py` — every mutation in the schema
* **Projects**: `test_create_project`, `test_update_project_changes_fields`, `test_delete_project`.
* **Tasks**: `test_create_task_updates_project_last_activity` (creating a task on a project bumps its `last_activity`), `test_update_task` (verifies `completed_at` flips when `done=true`), `test_toggle_task_creates_update_when_completing` (the toggle writes a row to `Update`), `test_toggle_task_no_update_when_uncompleting`, `test_delete_task`.
* **Ideas**: `test_create_idea`, `test_promote_idea_creates_project_and_deletes_idea`, `test_delete_idea`.
* **Categories**: `test_create_category`, `test_create_category_is_idempotent_per_user` (uses `get_or_create`), `test_update_category`, `test_delete_category`.
* **Updates**: `test_add_update_bumps_project_last_activity`.
* **Backup**: `test_mark_backup_creates_meta`, `test_mark_backup_updates_existing_meta` (idempotent, single row per user).

### `core/tests/test_errors.py` — the error contract the frontend depends on
* **Unauthenticated**:
  * `test_dashboard_query_requires_auth` — no `user_id` → `extensions.code == "UNAUTHENTICATED"`.
  * `test_create_project_requires_auth` — same for mutations.
  * `test_toggle_task_requires_auth` — verifies UNAUTHENTICATED takes precedence over NOT_FOUND.
* **Not found**:
  * `test_update_missing_project_is_not_found`, `test_update_missing_task_is_not_found`, `test_toggle_missing_task_is_not_found`, `test_promote_missing_idea_is_not_found`.
  * `test_create_task_with_unknown_project_is_not_found` — referencing a non-existent foreign-key project on creation surfaces NOT_FOUND.
  * `test_add_update_to_unknown_project_is_not_found`.
* **Cross-user isolation** — the most security-critical group:
  * `test_user_b_cannot_update_user_a_project` — returns NOT_FOUND (intentionally not 403, to avoid leaking row existence).
  * `test_user_b_cannot_toggle_user_a_task`.
  * `test_user_b_cannot_create_task_in_user_a_project`.
  * `test_delete_silently_succeeds_for_foreign_id` — pins the current behavior of `delete_*` mutations: they filter by `user_id` so a foreign id is a no-op that returns `True`. If you ever change this to raise NOT_FOUND, this test fails by design and forces you to update the frontend too.

### `core/tests/test_auth_view.py` — `JWTAuthGraphQLView`
The schema tests bypass HTTP. This file specifically covers the auth boundary:
* `test_missing_auth_returns_401` — no header → 401, body has `extensions.code = "UNAUTHENTICATED"`.
* `test_bad_token_returns_401` — garbage token → 401.
* `test_expired_token_returns_401` — valid signature but `exp` in the past → 401.
* `test_valid_token_lets_request_through` — HS256 token signed with `SUPABASE_JWT_SECRET` reaches the resolver and returns the user's (empty) dashboard.

## CI snippet

```yaml
backend:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install -r requirements-dev.txt
    - run: pytest
```

## What is NOT tested (yet)

* **JWKS / asymmetric JWT verification.** The legacy HS256 path is exercised by `test_auth_view.py`. The modern JWKS path requires a live Supabase project; it's covered by manually testing the deployed environment.
* **Rate limiting** (`graphql:ip` and `graphql:user` groups in `JWTAuthGraphQLView`). Cache-backed throttling — covered indirectly because tests run with the default Django local-memory cache and limits are high enough not to trigger.

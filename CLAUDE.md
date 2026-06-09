# Backend — notas para agentes

Django + Strawberry GraphQL. Auth Supabase JWT (`core/auth.py` → `info.context.user_id`).
El schema raíz fusiona las apps con `merge_types()` en `core/schema.py`. Admin gateado por
`_admin_user_id(info)` (`core/admin_api/permissions.py`) + auditoría `audit_record(...)`
(`core/admin_api/audit.py`). Migraciones contra Postgres de Supabase (`DATABASE_URL`).

## Onboarding — pasos

`core/services/onboarding.py` define `TOTAL_STEPS` (hoy **5**: nombre · tema ·
avatar · plan · personalizar Today). La finalización se rige por `status`
(`COMPLETED`/`SKIPPED`), **no** por el conteo de pasos, así que bumpear
`TOTAL_STEPS` no afecta a usuarios existentes ni requiere migración. Detalle del
paso 5: `../frontend/docs/onboarding-paso5-personalizar-today.md`.

**`onboardingState` provisiona el `AccountProfile`.** El resolver (`core/schema.py`)
llama `get_or_create_profile(uid)` (de `core/assistant/quotas.py`) en vez de solo
leer el perfil. Esto asegura que la decisión de exención early-adopter
(`is_billing_exempt`/`plan="pro"`, gateada por `EARLY_ADOPTER_CAP`) ya corrió
cuando el paso 4 del onboarding decide qué pantalla mostrar (elegir plan vs.
"indultado"). Antes el resolver solo hacía `filter().first()`, así que un usuario
nuevo cuyo primer request era el onboarding veía `is_billing_exempt=False` hasta
que algún request al assistant creaba el perfil — race que mostraba la pantalla
equivocada al azar. Cuando se quite la auto-exención, el flag quedará en `False` y
el paso 4 mostrará el selector de plan correctamente.

## App `core/feedback` — buzón de bug reports (usuario → admin, one-way)

Reportes de bugs que el usuario manda desde web o app y caen en un **inbox de admin**.
Canal de **un solo sentido**: no hay respuestas. Invariante de diseño — **no** agregar
mutaciones admin→usuario ni campos de respuesta.

- **Modelo:** `core/feedback/models.py` → `BugReport` (`user_id`, `topic`, `message`,
  `platform` web|app, `status` new|read|archived, `created`, `updated_at`). El **email NO se
  guarda** aquí: vive en Supabase auth y se resuelve on-demand en la query admin con
  `get_users_map` (mismo patrón que `adminUsers`/`adminSubscribers`; best-effort, queda "" si
  no hay service role key).
- **Schema:** `core/feedback/schema.py`.
  - Usuario: `submitBugReport(data: BugReportInput!) -> Boolean` (`FeedbackMutation`). Valida
    longitudes (topic ≤120, message ≤4000) y aplica un **throttle** suave por DB
    (`RATE_LIMIT_PER_HOUR = 10` por usuario/hora).
  - Admin: `adminBugReports(page, perPage, status)`, `adminBugReportsUnreadCount`
    (`AdminFeedbackQuery`); `adminBugReportSetStatus(id, status)`, `adminBugReportDelete(id)`
    (`AdminFeedbackMutation`, con `audit_record` acción `feedback.set_status` / `feedback.delete`,
    `target_type="bug_report"`).
  - Los métodos Python de las mutaciones admin se llaman `admin_bug_report_*` (no `set_status`
    /`delete` a secas) para evitar el `UserWarning: Mutation has overridden fields` al fusionar
    con announcements, que usa esos mismos nombres.
- **Registro:** `INSTALLED_APPS` (`core.feedback.apps.FeedbackConfig`) + tipos añadidos a los
  `merge_types("Query"/"Mutation", ...)` en `core/schema.py`.

Clientes: web `continuity/frontend` (`/report-bug` + inbox `/admin/feedback`), móvil
`continuity-mobile` (pantalla `(more)/report-bug`, solo envío). La lista de temas vive en cada
cliente (`bugTopics.ts`) y debe mantenerse en sync; el backend guarda `topic` como texto plano.

# Backend — notas para agentes

Django + Strawberry GraphQL. Auth Supabase JWT (`core/auth.py` → `info.context.user_id`).
El schema raíz fusiona las apps con `merge_types()` en `core/schema.py`. Admin gateado por
`_admin_user_id(info)` (`core/admin_api/permissions.py`) + auditoría `audit_record(...)`
(`core/admin_api/audit.py`). Migraciones contra Postgres de Supabase (`DATABASE_URL`).

## CMS público (`core/cms`) — schema sin auth para el sitio de marketing

`core/cms/schema_public.py` expone solo lecturas de contenido **PUBLISHED** (blog, help
resources/categories, pages) en `/public-graphql/`, sin JWT, para que el sitio (continuu.it) lo
consuma por SSR/ISR. El frontend lo trae estático pasando un `locale` explícito por ruta (no por
cookie) — ver `docs/marketing-performance.md` y `frontend/CLAUDE.md`.

**Performance — invariantes al tocar estos resolvers:**
- Las queries de **lista** (`publicBlogPosts`, `publicHelpResources`) hacen
  `.defer("content_html", "content_json")` y serializan con `include_content=False`. El cuerpo
  (`content_html`) puede pesar mucho; traerlo en listas infla el payload. **No** leas `m.content_html`
  en el path de lista: sobre un queryset diferido dispara una query por fila (N+1).
- Las queries de **detalle** (`publicBlogPost`, `publicHelpResource`, `publicPage`) sí traen el cuerpo.
- `publicHelpCategories` usa `annotate(Count("resources", filter=Q(status=PUBLISHED)))` para contar
  publicados en **una** query (antes era un `COUNT` por categoría → N+1). Mantenerlo así.
- Tests: `core/cms/tests/test_help_resources.py`, `test_admin_cms.py`.

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

## Quick Notes — cuaderno tipo Notion (notas con secciones plegables)

Notas top-level **categorizables** y **opcionalmente ligadas a un proyecto** (o sueltas),
cada una con una lista ordenable de **secciones plegables** (toggles tipo Notion). Distinto
de `Idea` (captura plana) y de `ProjectNote` (sub-notas encerradas en un proyecto). Plan,
wireframes y detalle: `../docs/quick-notes/PLAN.md`.

- **Modelos** (`core/models.py`, ambos heredan de `TimestampedModel`):
  - `QuickNote` → `title`, `category` (FK `Category`, `SET_NULL`), `project` (FK `Project`,
    `SET_NULL`), `pinned`, `updated_at`. `SET_NULL` en ambos FKs: borrar categoría/proyecto
    **no** borra la nota. Orden `["-pinned", "-updated_at"]`.
  - `NoteSection` → `note` (FK `QuickNote`, `CASCADE`), `heading`, `body` (markdown libre),
    `position`, `collapsed`, `updated_at`. Orden `["position", "created"]`.
- **Servicio:** `core/services/quick_notes.py`. CRUD de nota + secciones, `set_pin`,
  `reorder_sections(note_id, ordered_ids)`. Editar/añadir/borrar secciones hace
  `_touch_note` (bump de `updated_at` de la nota para que flote arriba). Valida que
  `category`/`project` referenciados sean del mismo `user_id`. Dispara `log_event` y
  `bump_context_version` igual que ideas.
- **Schema:** `core/schema.py`. Tipos `QuickNote`/`NoteSection`, inputs `QuickNoteInput`
  (`title/categoryId/projectId/pinned`) y `NoteSectionInput` (`heading/body/position/collapsed`).
  Queries `quickNotes(search, categoryId, projectId, pinned)` y `quickNote(id)` —
  **fuera del `dashboard`** (se cargan lazy al abrir Notes; los cuerpos pueden ser grandes).
  Mutations: `createQuickNote`, `updateQuickNote`, `setQuickNotePinned`, `deleteQuickNote`,
  `addNoteSection`, `updateNoteSection`, `deleteNoteSection`, `reorderNoteSections`.
- **Quotas** (`core/quotas.py`): `quick_notes` (Free 50 / Pro 1000 / Studio·Admin ∞) y
  `sections_per_note` (Free 20 / resto ∞). Para `sections_per_note`, `_count` recibe el
  id de la nota por el parámetro `project_id` de `check_entity_quota` (slot genérico de "padre").
  `quick_notes` **no** es kind bloqueante (igual que `notes_per_project`).
- **Activity:** `ActivityKind.QUICK_NOTE_CREATED` / `QUICK_NOTE_DELETED` → aparecen en el Log
  de ambos clientes (icono `NotebookPen`, i18n `views.log.entries.quickNote*`).
- **Migración:** `core/migrations/0020_*` (crea ambas tablas; aditiva). **Tests:**
  `core/tests/test_quick_notes.py`.

### Integración con el onboarding
- **Seed** (`core/services/seed.py` → `_create_example_content`): los usuarios **nuevos**
  reciben una nota de ejemplo "How to use Notes" con 2 secciones (la 2ª `collapsed=True`)
  junto al proyecto/tareas/rutina/idea de ejemplo. Idempotente (no re-siembra). Test en
  `core/tests/test_seed.py`.
- El **tour** (paso de Notes) y la **vista**/pantallas viven en los clientes — ver sus
  `CLAUDE.md`. No se tocó `TOTAL_STEPS` (es un paso del tour, no del onboarding).

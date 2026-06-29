# AUDIT.md — Beta lifecycle management (Fase 0)

> **⚑ NOTA (2026-06-26):** Este documento es la auditoría de la Fase 0 (estado *previo* al
> trabajo). La propuesta que sigue de aquí (`PROPOSAL.md`) **ya está implementada y
> desplegada** — ver el banner de estado en ese archivo. Se conserva como referencia histórica
> del punto de partida.

Auditoría del estado actual **antes** de proponer cambios. Responde las 5 preguntas
de la Fase 0 con referencias a archivo:línea. Stack real: **Django 5.1 + Strawberry
GraphQL** (backend en Render), **Next.js** (frontend), **Supabase solo para Auth (JWT)**,
**Postgres** como DB de la app vía Django ORM, **Stripe** para billing.

> Nota de stack: la spec original asume un entorno Supabase-nativo (`auth.users`
> metadata, `pg_cron`). El repo **no** es eso. Las propuestas (PROPOSAL.md) se aterrizan
> al stack real: campos en `AccountProfile`, cron como management command en Render.

---

## 1. ¿Cómo funciona el signup hoy? ¿Dónde se crea el registro del usuario? ¿Dónde se pone el flag de exención y cómo se llama?

**Auth lo dueña Supabase.** El registro de identidad (email, verificación, magic link)
vive en `auth.users` de Supabase. Django **no** crea ese registro; verifica el JWT en
`core/auth.py` (`verify_supabase_jwt`) y expone `info.context.user_id`.

**La fila de aplicación del usuario es `AccountProfile`** (`core/assistant/models.py:35`),
con `user_id` (UUID, PK) como única referencia a la identidad de Supabase. Se crea de forma
**lazy** (perezosa) en el **primer request autenticado**, no en el signup. Es la fila
canónica de billing/quota/cache.

**El flag de exención ya existe y se llama `is_billing_exempt`** (`AccountProfile`,
`core/assistant/models.py:59`, `BooleanField(default=False, db_index=True)`). Añadido en
`core/assistant/migrations/0005_studio_tier_and_billing_exempt.py`.

**La conflación que la spec describe YA está implementada**, en
`core/assistant/quotas.py:54-61`:

```python
EARLY_ADOPTER_CAP = 50

def get_or_create_profile(user_id):
    profile, created = AccountProfile.objects.get_or_create(user_id=user_id)
    if created and AccountProfile.objects.count() <= EARLY_ADOPTER_CAP:
        profile.plan = "pro"
        profile.is_billing_exempt = True
        profile.save(update_fields=["plan", "is_billing_exempt", "updated_at"])
    return profile
```

Es decir: los primeros 50 perfiles creados reciben automáticamente `plan='pro'` +
`is_billing_exempt=True`. **Esto funde "estás en el cohorte beta" con "no te cobramos".**
Ese es exactamente el punto a separar.

**Punto de provisión (dónde "corre" la decisión):** `get_or_create_profile()` se invoca
desde el resolver `onboardingState` en `core/schema.py:878`, precisamente para que la
decisión de exención ya haya corrido cuando el paso 4 del onboarding decide qué pantalla
mostrar (ver `backend/CLAUDE.md` → "Onboarding"). El propio CLAUDE.md ya anticipa el
retiro: *"Cuando se quite la auto-exención, el flag quedará en False y el paso 4 mostrará
el selector de plan."*

**Implicación para el feature:** el `created=True` de `get_or_create_profile` es el hook
natural para (a) la decisión de enrollment beta y (b) disparar el welcome email. Ocurre
post-verificación porque requiere un JWT válido de un usuario ya verificado.

---

## 2. ¿Qué emails envía hoy el sistema y desde dónde?

| Email | Trigger | Fuente | Canal |
|---|---|---|---|
| Confirmar signup | Registro | **Supabase Auth** | Email (Supabase) |
| Magic link | Login sin pass | **Supabase Auth** | Email (Supabase) |
| Reset de contraseña | Solicitud | **Supabase Auth** | Email (Supabase) |
| Weekly digest | Cron horario | Django mgmt command `send_weekly_digest` | **Push (Expo) / Telegram** — no email |
| Daily digest | Cron horario | Django mgmt command `send_daily_digest` | Push (Expo) / Telegram |
| Due reminders | Cron horario | Django mgmt command `send_due_reminders` | Push (Expo) / Telegram |
| Announcement push | Cron horario | Django mgmt command `send_announcement_push` | Push (Expo) / Telegram |

**Hallazgo clave: NO existe ningún provider de email transaccional de producto.** La app
de notificaciones (`core/notifications/`) tiene un **outbox idempotente** robusto, pero sus
providers son solo `expo.py` (push) y `telegram.py` (`core/notifications/providers/`). No
hay Resend ni ningún canal email.

**El outbox existente** (`core/notifications/dispatcher.py`): `enqueue()` hace UPSERT de
una fila `Notification` keyed por `(user_id, channel, kind, dedupe_key)`; los eventos ya
`SENT` se saltan → **idempotencia nativa**. Tiene status, retry y visibilidad en el admin
(`/admin/system/jobs`). Este es el patrón a reusar para el welcome y la secuencia de
inactividad (decisión confirmada con el dueño).

**Conclusión:** los emails auth siguen en Supabase; **todos** los emails de producto
(welcome + secuencia + futuros) son nuevos y van por **Resend** con sender
`alfredo@continuu.it`, idealmente sobre la infraestructura de outbox existente.

---

## 3. ¿Existe una tabla de event log? Schema y tipos de evento.

**Sí: el modelo `Activity`** (`core/models.py:370`, hereda de `TimestampedModel` → trae
`user_id` + `created`). Schema:

```
Activity(
  user_id, created (de TimestampedModel),
  kind            CharField(choices=ActivityKind, db_index=True),
  entity_id       UUID nullable,
  entity_title    str,
  project_id      UUID nullable,
  target_project_id UUID nullable,
  note, previous_value, new_value  (text)
)
índices: (user_id, -created), (user_id, kind), (user_id, project_id)
```

Helper de escritura: `core.services.activities.log_event`. (Ojo: `core/services/activity.py`
está **removido** y lanza ImportError — usar `activities`, plural.)

**`ActivityKind` actual** (`core/models.py:267-283`): `note`, `project_created`,
`project_deleted`, `project_status_changed`, `project_due_date_changed`, `task_created`,
`task_completed`, `task_deleted`, `task_due_date_changed`, `idea_created`, `idea_deleted`,
`idea_promoted`, `routine_created`, `routine_completed`, `routine_deleted`,
`quick_note_created`, `quick_note_deleted`.

**Mapeo contra los 4 "eventos significativos" de la spec:**

| Spec | Estado en el código |
|---|---|
| `project_created` | ✅ existe (`PROJECT_CREATED`) |
| `project_state_changed` | ✅ existe como `project_status_changed` (`PROJECT_STATUS_CHANGED`) |
| `loop_closed` | ❌ **no existe** — la feature "loop" no está construida |
| `sunday_review_completed` | ❌ **no existe** — no es feature de la app (decisión del dueño) |

**Decisión (dueño):** la **lista de eventos significativos será configurable** (vía
`app_config`, ya que el dueño controla esa lista) y debe ser **amplia** — cualquier señal de
que el usuario está usando la app, no solo proyectos. **Default propuesto:** todas las
`ActivityKind` de creación / cambio de estado / completado / promoción —
`project_created`, `project_status_changed`, `task_created`, `task_completed`, `idea_created`,
`idea_promoted`, `routine_created`, `routine_completed`, `quick_note_created`. Se excluyen los
`*_deleted` y `note`. `loop_closed` / `sunday_review_completed` quedan como valores válidos que
se activan cuando/si esas features existan, sin recompilar.

**Modelo de inactividad = ventana rodante (no anclada al enrolamiento).** El reloj se mide
desde la **última actividad significativa** (`last_significant_event_at`, derivable como
`MAX(Activity.created)` sobre los kinds significativos; fallback `beta_enrolled_at` si no hay
ninguno), **no** desde `beta_enrolled_at`. Esto detecta lapsos *después* de actividad inicial.
Cualquier evento significativo reinicia el reloj, limpia `reclaim_warned_at` y re-arma la
secuencia. Día 3/7/14/21 se cuentan desde ese último evento.

> Corrige un bug del diseño original de la spec: medir "sin eventos **desde** `beta_enrolled_at`"
> haría que un usuario activo la 1ª semana y luego dormido nunca dispare la secuencia.

**Reclaim en tres tiers (decisión dueño):** el reclaim automático distingue tres tipos de
usuario, derivados de `Activity` vía `first_significant_event_at` / `last_significant_event_at`:

- **Fantasma (`never_started`):** sin ningún evento significativo desde el enrolamiento. Recibe
  nudges día 3/7/14 (desde `beta_enrolled_at`) y **reclaim automático el día 21**.
- **Breve (`briefly_active`):** tiene ≥1 evento pero el span de actividad
  (`last - first`) es **< `established_min_activity_days` (30d)**. Al apagarse recibe nudges de
  re-engagement (rolling, re-armados por episodio) y **reclaim tras ~`brief_reclaim_days` (60d)**
  de inactividad.
- **Establecido (`established`):** span de actividad **≥ 30d**. Nudges de re-engagement al
  apagarse y **reclaim solo tras ~`dormant_reclaim_days` (180d, ~6 meses)** de inactividad.

Reclaim siempre con email de aviso previo; cualquier evento significativo reinicia el reloj y
re-arma. Umbrales configurables en `app_config` (defaults): `ghost_nudge_days=[3,7,14]`,
`ghost_reclaim_day=21`, `brief_reclaim_days=60`, `dormant_reclaim_days=180`,
`established_min_activity_days=30`.

**Falta para el feature:** tipos de evento "de sistema" que la spec pide loguear:
`beta_reclaimed` y `admin_action`. `Activity` es per-usuario y encaja para `beta_reclaimed`.
Para `admin_action` ya existe un mecanismo de auditoría dedicado (ver §4) que probablemente
encaje mejor — se decide en PROPOSAL.

---

## 4. ¿Existe panel/route admin? ¿Cómo está gateado?

**Sí, ya existe un panel admin completo.** No hay que crearlo desde cero.

**Frontend** (Next.js): `frontend/src/app/(app)/admin/` con páginas ya construidas:
`page.tsx` (dashboard), `users/` (+ `users/[userId]`), `billing/`, `announcements/`,
`feedback/`, `content/*` (CMS), `database/`, `system/audit`, `system/jobs`, `system/stats`.
Shell en `frontend/src/components/admin/AdminShell.tsx`.

**Gating (backend):** NO es por `ADMIN_EMAILS` env (como sugiere la spec). Es por el flag
**`AccountProfile.is_admin`** (`core/assistant/models.py`), verificado en
`core/admin_api/permissions.py` → `_admin_user_id(info)` lanza `GraphQLError` code
`FORBIDDEN` si el usuario no es admin. El admin se promueve con el management command
`core/assistant/management/commands/promote_admin.py`.

**API admin:** `core/admin_api/schema.py` (Strawberry), con tipos ya existentes como
`AdminUserSummary`, `AdminUserDetail`, `AdminUserPage`, `UserCounts`, `AdminNotificationJob`,
`PlanCount`, `AdminSystemStats`, etc. Fusionado al schema raíz vía `merge_types` en
`core/schema.py`.

**Auditoría de acciones admin:** ya existe `core/admin_api/audit.py` → `audit_record(...)`
(usado p.ej. por feedback: acciones `feedback.set_status`, `feedback.delete` con
`target_type`). Este es el candidato natural para el requisito de loguear cada escritura
admin (en vez de meter `admin_action` en `Activity`).

**Implicación:** reusar panel + `is_admin` + `audit_record`. Solo agregar una sección
"Beta" (lista/edición/controles globales/pipeline) y nuevos campos en
`AdminUserSummary`/`AdminUserDetail`. **No** crear un route nuevo ni un gating paralelo.

---

## 5. ¿Qué proveedor de pago está cableado y cómo interactúa el flag exempt con él?

**Stripe** (`stripe==11.4.1`), app `core/billing/`: `services.py`, `stripe_client.py`,
`webhooks.py` (`/billing/` urls, webhook `@csrf_exempt`), `plans.py`, `schema.py`.

**Estado en `AccountProfile`:** `stripe_customer_id`, `stripe_subscription_id`,
`stripe_price_id`, `plan_renews_at`, `cancel_at_period_end`.

**Cómo interactúa `is_billing_exempt`:**

- `core/billing/services.py:151-210` → `sync_subscription_to_profile()`: *"Respects
  `is_billing_exempt`: exempt accounts are never downgraded, only logged."* Si
  `profile.is_billing_exempt` es True, se **salta el downgrade** aunque Stripe diga que la
  suscripción terminó (`services.py:208`). Protege a usuarios comp/cortesía del churn por
  limpieza de suscripciones stale.
- `core/quotas.py:111-115` → `effective_plan()`: hoy retorna `profile.plan` tal cual;
  `is_billing_exempt` es **ortogonal** ("plan dicta features, exempt dicta si Stripe cobra").

**Conclusión:** `is_billing_exempt` ya está correctamente desacoplado de `plan` a nivel de
features. El problema es **solo el punto de asignación** (`get_or_create_profile` lo enciende
junto con el cohorte beta). Separar los conceptos no requiere tocar la lógica Stripe ↔ exempt
existente; solo cambiar **quién/cuándo** enciende el flag y **por qué** (`billing_exempt_reason`).

---

## Resumen de hallazgos → ganchos para el diseño

1. **`AccountProfile` es el hogar de los campos beta/billing** (decisión confirmada). Ya
   tiene `is_billing_exempt`; se extiende con los campos beta + `billing_exempt_reason` +
   `billing_exempt_until`.
2. **La conflación está en `quotas.py:get_or_create_profile`** (cap=50). Ahí se reemplaza la
   lógica por la decisión enrollment/cupo, y se usa como hook de welcome.
3. **Eventos = modelo `Activity`** + `activities.log_event`. Lista de eventos significativos
   **amplia y configurable** (proyectos, tareas, ideas, rutinas, quick notes). Inactividad
   medida como **ventana rodante desde la última actividad**, no desde el enrolamiento.
   `loop_closed`/`sunday_review_completed` no existen aún.
4. **Outbox de notificaciones reutilizable** para idempotencia/retry/visibilidad; falta
   crear el provider **Resend** (no existe email). `email_sends` se modela como pide la spec
   encima del outbox.
5. **Panel admin + `is_admin` + `audit_record` ya existen**; se extienden, no se recrean.
6. **Cron = Render Cron Job** (`continuity-notifications-hourly`, mgmt commands), no pg_cron.
   La secuencia diaria será un nuevo management command en un Render Cron.
7. **Stripe ↔ exempt ya desacoplado** correctamente; el feature solo cambia el punto de
   asignación del flag.

---

**STOP.** Siguiente deliverable: `PROPOSAL.md` (schema + migración exacta, cambios de signup,
diseño admin, plan de test, schedule del cron). Espera tu revisión de este AUDIT antes de
continuar.

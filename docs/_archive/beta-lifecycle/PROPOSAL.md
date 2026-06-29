# PROPOSAL.md — Beta lifecycle management (diseño técnico)

> **⚑ ESTADO (actualizado 2026-06-26): IMPLEMENTADO.** Este diseño ya está construido. En
> código: campos beta/exención en `AccountProfile` (`core/assistant/models.py`), decisión de
> enrolamiento en `_apply_enrollment_decision` (`core/assistant/quotas.py`), servicio
> `core/services/beta_lifecycle.py`, emails vía Resend en `core/notifications/lifecycle.py`
> con idempotencia (`EmailSend`), cron `core/management/commands/run_beta_lifecycle.py`, y
> admin en `core/admin_api/beta_schema.py`. Tests en `core/tests/test_beta_lifecycle.py`. Se
> conserva como el registro de diseño; el envío real sigue gobernado por el flag `dry_run`
> (ver `BETA_LIFECYCLE_README.md`).

Aterriza el `AUDIT.md` a implementación: schema + migraciones exactas, cambio de signup,
lógica del cron de inactividad (3 tiers + ventana rodante), welcome, cold start, admin, y plan
de test. Stack real: **Django + Strawberry + Render + Stripe + Supabase Auth + Resend**.

> Default operativo: **`dry_run = true`** para todo envío de producto hasta que el dueño lo apague.

---

## 0. ⚠️ Interferencia con el feature Graveyard (estados de proyecto) — RESUELTA

El feature de Graveyard / cierre de estados (migraciones `0024`/`0025`, `core/services/stalled.py`,
`detect_stalled_projects`) **sí interfiere** con la detección de inactividad. Análisis:

**El choque:** `detect_and_mark_stalled()` corre **cada hora** (ya cableado en
`continuity-notifications-hourly`, [render.yaml:55](backend/render.yaml:55)) y al auto-marcar un
proyecto `active → stalled` (tras 14d idle del proyecto) escribe un evento
`log_event(kind=PROJECT_STATUS_CHANGED, new_value='stalled')`
([stalled.py:60](backend/core/services/stalled.py:60)) — **generado por el sistema, no por el
usuario**. Como `project_status_changed` está en `significant_event_kinds`, ese evento movería
`last_significant_event_at` y **resetearía el reloj de inactividad → el reclaim nunca (o tarde)
dispara**. Pega sobre todo a los tiers **breve/establecido** (los que tienen proyectos
stalleables); a un fantasma puro no le afecta (no tiene proyectos).

**Por qué es sutil:** el stall ocurre ~día 14 (justo donde la secuencia avisa). Si el usuario
tiene varios proyectos, cada uno stallea en momentos distintos → varios eventos falsos que
empujan el reloj repetidamente.

**Fix (aplicado en este diseño):** los eventos significativos **excluyen**
`project_status_changed` con `new_value='stalled'`. Que un proyecto pase a *stalled* es lo
**opuesto** a engagement (lo confirma que el productor sea un sweep automático). Kill / launch /
revive / pause **manuales** del usuario sí cuentan (su `new_value` ≠ `stalled`). El filtro se
encapsula en un helper único `significant_events_q()` reutilizado por el cron (§6.1) y por el
admin (§8), para que ambos midan idéntico.

**Otros puntos menores (sin bloqueo):**
- **Cadena `&&` del cron horario:** hoy termina en `detect_stalled_projects`. Mi `send_lifecycle_welcome`
  debe insertarse de modo que un fallo previo no lo bloquee (ver §10) — uso `;` o lo pongo primero.
- **Choque de nombres:** `ProjectStatus.KILLED` (proyecto) vs `BetaStatus.MANUALLY_KILLED` (cuenta beta)
  son modelos distintos; sin conflicto técnico, solo cuidar etiquetas en el admin para no confundir.
- **`autopsy.py` / `GraveyardInsight`:** verificado — **no** emite eventos `Activity`, así que no
  genera señales falsas. Sin interferencia.

---

## 1. Decisiones de arquitectura (lo que la spec me dejó proponer)

| Pregunta de la spec | Decisión | Por qué |
|---|---|---|
| `auth.users` metadata vs tabla nueva | **Extender `AccountProfile`** (`core/assistant/models.py`) | Ya es la fila canónica de billing/quota y ya tiene `is_billing_exempt`. Django no administra `auth.users` metadata. |
| Mecanismo de cron | **Render Cron Jobs** (management commands), no pg_cron | Es el patrón ya usado (`continuity-notifications-hourly`). pg_cron no encaja en el deploy. |
| Hora del cron | **Diario 15:00 UTC** | ≈10am ET / 7am PT — mañana en América, buen horario para nudges de comportamiento. |
| Framework admin | **Next.js `/admin` + Strawberry `admin_api`** existentes | Ya hay panel, gating `is_admin` y `audit_record`. Solo agrego sección Beta. |
| Idempotencia / ledger | Tabla **`email_sends`** + provider **Resend** en el patrón de providers existente | `Notification` (outbox) está modelado para push; email merece su propio ledger limpio con `dry_run`/`resend_message_id`/conteo de fallos. Reuso la abstracción de provider y la visibilidad en `/admin/system/jobs`. |
| Eventos significativos | Configurables en `app_config`; inactividad por **ventana rodante** computada en el cron vía agregado sobre `Activity` | Sin tocar el hot-path de `log_event`; el cohorte beta es chico y el `MIN/MAX` por usuario es barato. |

---

## 2. Modelo de datos

### 2.1 Campos nuevos en `AccountProfile` (app `assistant`)

```python
# core/assistant/models.py

class BetaStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    RECLAIMED = "reclaimed", "Reclaimed"
    MANUALLY_PAUSED = "manually_paused", "Manually paused"
    MANUALLY_KILLED = "manually_killed", "Manually killed"


class BillingExemptReason(models.TextChoices):
    BETA = "beta", "Beta"
    FRIEND = "friend", "Friend"
    INVESTOR = "investor", "Investor"
    PARTNER = "partner", "Partner"
    MANUAL = "manual", "Manual"


class AccountProfile(models.Model):
    # ... campos existentes (plan, stripe_*, is_admin, is_billing_exempt, ...) ...

    # --- Beta cohort (independiente de billing) ---
    beta_cohort = models.BooleanField(default=False, db_index=True)
    beta_status = models.CharField(
        max_length=16, choices=BetaStatus.choices, blank=True, default="", db_index=True
    )
    beta_enrolled_at = models.DateTimeField(null=True, blank=True)
    reclaim_warned_at = models.DateTimeField(null=True, blank=True)

    # --- Billing exemption (independiente de beta) ---
    # is_billing_exempt YA existe.
    billing_exempt_reason = models.CharField(
        max_length=16, choices=BillingExemptReason.choices, blank=True, default=""
    )
    billing_exempt_until = models.DateTimeField(null=True, blank=True)
```

`beta_status` queda `""` para no-beta; se pone `active` al enrolar. (Mantengo `is_billing_exempt`
tal cual — no se renombra, para no romper `core/billing/services.py` ni `core/quotas.py`.)

### 2.2 Tabla `app_config` (key/value tipado)

```python
# core/models.py

class AppConfig(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField()  # bool / int / list, según la key
    updated_at = models.DateTimeField(auto_now=True)
```

Helper con cache: `core/services/app_config.py` → `get(key, default)`, `get_bool`, `get_int`,
`get_list`, `set(key, value)` (invalida cache). Seed inicial vía data migration:

| key | default | tipo |
|---|---|---|
| `dry_run` | `true` | bool |
| `beta_enrollment_open` | `false` | bool |
| `beta_spot_cap` | `50` | int |
| `significant_event_kinds` | `["project_created","project_status_changed","task_created","task_completed","idea_created","idea_promoted","routine_created","routine_completed","quick_note_created"]` | list |

> Nota (Graveyard, §0): incluimos `project_status_changed` pero el helper `significant_events_q()`
> **excluye** las transiciones a `'stalled'` (auto-generadas por el sweep). Así kill/launch/revive
> manuales cuentan, y el auto-stall del sistema no falsea el reloj de inactividad.
| `ghost_nudge_days` | `[3,7,14]` | list |
| `ghost_reclaim_day` | `21` | int |
| `reengage_days` | `[7,14]` | list |
| `brief_reclaim_days` | `60` | int |
| `dormant_reclaim_days` | `180` | int |
| `established_min_activity_days` | `30` | int |
| `reclaim_warn_grace_days` | `7` | int |

### 2.3 Tabla `email_sends` (ledger de idempotencia + auditoría)

```python
# core/notifications/models.py

class EmailSend(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        DRY_RUN = "dry_run", "Dry run"

    id = models.BigAutoField(primary_key=True)
    user_id = models.UUIDField(db_index=True)
    email_id = models.CharField(max_length=32)   # welcome_beta, inactivity_1, reengage_1, ...
    # "" para emails one-time (welcome_*, inactivity_1..4). Para los re-armables
    # (reengage_*, reclaim_*) = ISO date del ancla del episodio (última actividad).
    episode_key = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices)
    dry_run = models.BooleanField(default=True)
    resend_message_id = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)  # fallos consecutivos
    created = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user_id", "email_id"]),
            models.Index(fields=["status", "-created"]),
        ]
        constraints = [
            # Idempotencia REAL: un solo envío real por (user, email_id, episodio).
            # Las filas dry_run NO cuentan → flip a real no queda bloqueado.
            models.UniqueConstraint(
                fields=["user_id", "email_id", "episode_key"],
                condition=models.Q(dry_run=False),
                name="uniq_real_email_send",
            ),
        ]
```

**Regla de idempotencia:** antes de un envío real se verifica que no exista fila con
`dry_run=False` para `(user_id, email_id, episode_key)`. Las filas `dry_run=True` se escriben
solo para preview/auditoría en el admin y **nunca** bloquean un envío real posterior.

---

## 3. Migraciones (orden)

1. `assistant/000X_beta_billing_fields` — `AddField` × 5 en `AccountProfile` (§2.1). Aditiva, sin defaults peligrosos.
2. `core/000X_app_config` — crea `AppConfig` + **data migration** que siembra las 11 keys (§2.2).
3. `notifications/000X_email_sends` — crea `EmailSend` (§2.3).
4. `assistant/0011_backfill_beta_cohort` — **data migration (reversible, decisión del dueño 2026-06-15):** **todos los `AccountProfile` actuales EXCEPTO 3 cuentas excluidas** → `beta_cohort=True`, `beta_status="active"`, `billing_exempt_reason="beta"`, `is_billing_exempt=True`, `beta_enrolled_at = created`; `plan` free→pro (nunca degrada studio/admin). Los 3 excluidos quedan fuera del cohorte (su billing NO se toca aquí).

> El backfill es la decisión que necesito confirmada antes de correr la migración 4 (ver tu task del martes).

---

## 4. Signup — separar los dos conceptos

Reemplazo la lógica de exención en `get_or_create_profile` ([quotas.py:54-61](backend/core/assistant/quotas.py:54)):

```python
# core/assistant/quotas.py
from django.db import transaction
from core.services import app_config

def get_or_create_profile(user_id):
    profile, created = AccountProfile.objects.get_or_create(user_id=user_id)
    if created:
        _apply_enrollment_decision(profile)   # reemplaza el bloque EARLY_ADOPTER_CAP
    return profile

def _apply_enrollment_decision(profile):
    now = timezone.now()
    with transaction.atomic():
        open_ = app_config.get_bool("beta_enrollment_open")
        cap = app_config.get_int("beta_spot_cap")
        active = (AccountProfile.objects
                  .filter(beta_cohort=True, beta_status=BetaStatus.ACTIVE)
                  .count())
        if open_ and active < cap:
            profile.beta_cohort = True
            profile.beta_status = BetaStatus.ACTIVE
            profile.beta_enrolled_at = now
            profile.plan = "pro"                      # beta = features Pro
            profile.is_billing_exempt = True
            profile.billing_exempt_reason = BillingExemptReason.BETA
            profile.billing_exempt_until = None
        else:
            profile.beta_cohort = False               # paga normal (defaults)
            profile.is_billing_exempt = False
        profile.save(update_fields=[
            "beta_cohort", "beta_status", "beta_enrolled_at", "plan",
            "is_billing_exempt", "billing_exempt_reason", "billing_exempt_until",
            "updated_at",
        ])
```

- **No toca** el flujo de confirmación / magic link (eso vive en Supabase). Solo asigna campos en el punto donde hoy ya se asignaba la exención.
- Corre en el **primer request autenticado** (post-verificación). El `onboardingState` resolver ([schema.py:878](backend/core/schema.py:878)) ya lo invoca → la decisión es determinista para el paso 4 del onboarding (como documenta `backend/CLAUDE.md`).
- Race del cap: `transaction.atomic` + recount. A escala beta (~50) el riesgo es mínimo; si se quiere blindar, un advisory lock por `beta_spot_cap`.

---

## 5. Welcome email (cuasi-real-time, horario)

- Al enrolar/crear perfil **no** se envía inline (no metemos red en el path de request).
- Command **`send_lifecycle_welcome`** añadido al cron **horario existente** (`continuity-notifications-hourly`): busca `AccountProfile` creados sin fila `email_sends` de welcome y envía:
  - `beta_cohort=True` → `welcome_beta`
  - else → `welcome_regular`
- Idempotente por `email_sends`. Respeta `dry_run`. Latencia ≤ 1h (aceptable para un welcome).

---

## 6. Cron diario de inactividad — `run_beta_lifecycle`

Nuevo command, Render Cron **`0 15 * * *`**. Para cada `AccountProfile` con
`beta_cohort=True` y `beta_status="active"`:

### 6.1 Clasificación (ventana rodante)
```
# significant_events_q(): helper ÚNICO compartido con el admin (§8).
# Excluye el auto-stall de Graveyard (ver §0): un project_status_changed→'stalled'
# es ruido del sistema, no engagement; contarlo bloquearía el reclaim.
def significant_events_q():
    sig = app_config.get_list("significant_event_kinds")
    return Q(kind__in=sig) & ~Q(kind="project_status_changed", new_value="stalled")

agg = (Activity.objects.filter(Q(user_id=u) & significant_events_q())
       .aggregate(first=Min("created"), last=Max("created")))
if agg["first"] is None:
    tier = "ghost";       anchor = beta_enrolled_at
else:
    span = agg["last"] - agg["first"]
    tier = "established" if span.days >= established_min_activity_days else "brief"
    anchor = agg["last"]
days_inactive = (now - anchor).days
```

### 6.2 Acción por tier (se envía **un solo** email por corrida: el umbral más alto vencido y no enviado)

| Tier | Nudges | Warn (set `reclaim_warned_at`) | Reclaim |
|---|---|---|---|
| **ghost** | d3 `inactivity_1`, d7 `inactivity_2` | d14 `inactivity_3` | d21 `inactivity_4` (si warned ≥ `grace` días) |
| **brief** | reengage_days `reengage_1/2` | `brief_reclaim_days - grace` `reclaim_warn` | `brief_reclaim_days` (~60) `reclaim_final` |
| **established** | reengage_days `reengage_1/2` | `dormant_reclaim_days - grace` `reclaim_warn` | `dormant_reclaim_days` (~180) `reclaim_final` |

- **`episode_key`**: `""` para ghost (one-time); `anchor.date().isoformat()` para brief/established (re-arma al cambiar la última actividad).
- **Reclaim** (`inactivity_4` / `reclaim_final`): `beta_status="reclaimed"`, `is_billing_exempt=False`, `billing_exempt_reason=""`, y `audit_record(action="beta.reclaimed", ...)`. **Invariante:** nunca se reclama sin un `reclaim_warned_at` previo con ≥ `grace` días de antigüedad.
- **Reset de episodio:** si `days_inactive < primer_umbral` y `reclaim_warned_at` está set → se limpia (el usuario volvió).

### 6.3 Stop conditions
`beta_status != active` (paused/killed/reclaimed) o `beta_cohort=False` → se omite. Cualquier
evento significativo mueve `anchor` → la próxima corrida recalcula y, de hecho, halta la
secuencia (y como reclaim exige warn + grace, un usuario que vuelve siempre se detecta antes).

### 6.4 `dry_run` (default true)
Cuando `app_config.dry_run=True`: clasifica y **registra en `email_sends` con `dry_run=True`**,
pero **no** llama a Resend y **no** muta `reclaim_warned_at` / `beta_status` / `is_billing_exempt`.
Es preview puro → el admin ve "qué pasaría" sin efectos. Flag `--dry-run/--no-dry-run` para
override manual en pruebas.

### 6.5 Envío + fallos
Provider **Resend** nuevo en `core/notifications/providers/resend.py` (implementa la interfaz
`base.py` / `ProviderError`). En éxito: `status=sent`, `resend_message_id`, `sent_at`. En error:
`status=failed`, `error`, `attempts += 1`; reintenta en la siguiente corrida. Con `attempts >= 3`
se marca y **aparece en `/admin/system/jobs`**.

---

## 7. Cold start (primer deploy real)

`run_beta_lifecycle` es idempotente por diseño, así que el primer run real ya hace lo correcto:
como no hay envíos previos y se manda **solo el umbral más alto vencido**, cada usuario recibe
**un único** email, no la secuencia retroactiva:

| Situación | Resultado |
|---|---|
| ghost > d21 | `inactivity_4` + reclaim |
| ghost d14–20 | `inactivity_3` + `reclaim_warned_at=today` |
| ghost d7–13 | `inactivity_2` |
| ghost d3–6 | `inactivity_1` |
| brief/established pasado su umbral de reclaim | `reclaim_warn` + `reclaim_warned_at=today` (el reclaim ocurre en una corrida posterior, tras `grace` — nunca el mismo día) |

Se corre **primero en `dry_run`** para revisar a quién le caería antes de enviar.

---

## 8. Admin (extender lo existente)

**Backend (`core/admin_api/`):**
- `AdminUserSummary` / `AdminUserDetail`: + `beta_cohort`, `beta_status`, `is_billing_exempt`, `billing_exempt_reason`, `billing_exempt_until`, `beta_enrolled_at`, `days_since_last_significant_event` (annotate `Max(Activity.created)` filtrado por **`significant_events_q()`** — el mismo helper del cron, §0/§6.1, para que el admin y el reclaim midan idéntico), `last_email` (id + sent_at desde `email_sends`).
- Filtros en `adminUsers`: `beta_status`, `billing_exempt`, `days_inactive`.
- Query `adminBetaPipeline`: counts por `beta_status`, counts en cada umbral (d3/7/14/21+), reclaims recientes.
- Mutations: `adminSetBetaFields(userId, …)`, `adminSetBillingExempt(userId, …)`, `adminSetAppConfig(key, value)`. **Cada una** → `audit_record(...)` (acción `beta.update` / `billing.update` / `config.update`).
- **Invariante de código:** las mutations admin **nunca** tocan `is_billing_exempt` salvo `adminSetBillingExempt` explícita. El reclaim automático es el único que lo apaga por inactividad.

**Frontend (`frontend/src/app/(app)/admin/`):**
- Nueva página `/admin/beta`: tabla (email, signup, beta_cohort, beta_status, exempt, reason, días inactivo, último email) + filtros.
- Reuso `users/[userId]` para edición por usuario (toggles + selects).
- Panel de controles globales (toggle `beta_enrollment_open`, editar `beta_spot_cap`).
- Cards de pipeline summary. Item "Beta" en `AdminShell`.

---

## 9. Plan de test

`pytest` desde el `.venv` de la raíz (ver memoria de tests). Inyectar `now` en el command para
viajar en el tiempo; provider Resend **fake** (sin red); `dry_run` por defecto en tests.

**Casos:**
- Signup: enrollment abierto+cupo → beta+exempt='beta'; cerrado o cupo lleno → regular sin exención.
- Clasificación de tiers: ghost / brief (<30d span) / established (≥30d span).
- Mapeo umbral→email por tier; envío de un solo email por corrida.
- Re-arma por episodio: lapso → emails; actividad (cambia `anchor`) → nuevo `episode_key` → vuelve a poder enviar.
- Idempotencia: no doble envío real; filas `dry_run` no bloquean el real.
- `dry_run=True`: sin efectos (no muta status/exempt/warned, no llama Resend, sí escribe ledger).
- Reclaim: set `reclaimed` + `is_billing_exempt=False` + `audit_record`; **nunca** sin warn + grace.
- Acciones manuales admin: no tocan `is_billing_exempt` (salvo la mutation explícita).
- Cold start: un solo email según umbral; warn-antes-de-reclaim en tiers activos.

---

## 10. Cron / deploy (render.yaml)

```yaml
  - type: cron
    name: continuity-beta-lifecycle-daily
    runtime: python
    rootDir: backend
    plan: starter
    schedule: "0 15 * * *"          # diario 15:00 UTC (~10am ET / 7am PT)
    buildCommand: "./build.sh"
    startCommand: "python manage.py run_beta_lifecycle"
    # envVars: DJANGO_SECRET_KEY, DATABASE_URL, SUPABASE_*, RESEND_API_KEY, EMAIL_FROM, APP_URL
```

Al job **horario existente** se le añade `send_lifecycle_welcome` (welcomes + retries de emails
fallidos). **Ojo (§0):** ese startCommand encadena con `&&`, así que un fallo de un paso previo
(p.ej. `detect_stalled_projects`) abortaría el welcome. Lo inserto **antes** de los pasos
existentes o cambio la cadena a `;` para que cada paso corra independiente:

```yaml
startCommand: "python manage.py send_lifecycle_welcome ; python manage.py send_weekly_digest ; … ; python manage.py detect_stalled_projects"
```

**Env vars nuevas:** `RESEND_API_KEY`, `EMAIL_FROM=alfredo@continuu.it`, `APP_URL`.

---

## 11. Resumen de archivos a tocar/crear

| Acción | Archivo |
|---|---|
| + campos beta/billing | `core/assistant/models.py` (+ migración) |
| + AppConfig + seed | `core/models.py`, `core/services/app_config.py` (+ migración) |
| + EmailSend | `core/notifications/models.py` (+ migración) |
| signup | `core/assistant/quotas.py` |
| provider Resend | `core/notifications/providers/resend.py` |
| welcome | `core/.../management/commands/send_lifecycle_welcome.py` |
| inactividad | `core/.../management/commands/run_beta_lifecycle.py` |
| admin API | `core/admin_api/schema.py` |
| admin UI | `frontend/src/app/(app)/admin/beta/…`, `users/[userId]`, `AdminShell` |
| cron + env | `backend/render.yaml` |
| tests | `core/assistant/tests/`, `core/notifications/tests/` |

---

**STOP.** Revisa este PROPOSAL. Cuando lo apruebes (y confirmes el backfill §3.4 y los valores
iniciales de `app_config`), arranco con las migraciones. Default `dry_run=true` hasta tu OK.

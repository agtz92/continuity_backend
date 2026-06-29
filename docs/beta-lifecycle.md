# Beta lifecycle — documentación de implementación

Sistema que **separa el cohorte beta de la exención de billing**, envía welcome +
una secuencia de inactividad por **Resend** (bilingüe en/es), y **reclama cupos
beta** no usados. Cron diario en Render. `dry_run=true` por default hasta go-live.

> **Documento canónico único** de esta feature (diseño + operación). Los artefactos de
> desarrollo (historia) se archivaron en `../../docs/_archive/beta-lifecycle/`:
> `AUDIT.md` (auditoría Fase 0), `PROPOSAL.md` (spec con §0 sobre la interferencia con
> Graveyard), `EMAIL_BRIEF.md` (brief de copys), `EMAIL_PROPOSAL.md` (borradores de copys)
> y `BETA_LIFECYCLE_README.md` (runbook previo, ahora fusionado abajo en "Operación / deploy").

## Por qué

Antes, el signup auto-otorgaba `is_billing_exempt` a los primeros 50 usuarios
(`EARLY_ADOPTER_CAP` en `quotas.py`), fundiendo dos conceptos distintos:

- **beta_cohort** — ocupa un cupo, debe feedback, tiene lifetime deal.
- **is_billing_exempt** — simplemente "no se le cobra" (beta, amigo, inversor, partner, manual).

Ahora son independientes: un beta es exento con `reason="beta"`, pero la exención
puede otorgarse por otras razones sin ocupar cupo.

## Modelo de datos

- **`AccountProfile`** (`core/assistant/models.py`) + 6 campos: `beta_cohort`,
  `beta_status` (`BetaStatus`: active/reclaimed/manually_paused/manually_killed),
  `beta_enrolled_at`, `reclaim_warned_at`, `billing_exempt_reason`
  (`BillingExemptReason`), `billing_exempt_until`. (`is_billing_exempt` ya existía.)
- **`AppConfig`** (`core/models.py`) — key/value tipado (JSON). Accesores en
  `core/services/app_config.py` (`DEFAULTS` es la fuente de los valores iniciales).
- **`EmailSend`** (`core/notifications/models.py`) — ledger de idempotencia.
  Unique parcial `(user_id, email_id, episode_key) WHERE dry_run=false`: un solo
  envío real por combo; las filas `dry_run` son preview y nunca bloquean el real.

Migraciones: `assistant/0010` (campos), `assistant/0011` (backfill),
`core/0026` (AppConfig), `core/0027` (seed), `core/0028` (abre enrollment),
`notifications/0009` (EmailSend).

## Flujo

1. **Signup** (`quotas.py:_apply_enrollment_decision`, en el primer request
   autenticado): si `beta_enrollment_open` y `activos < beta_spot_cap` →
   beta + exento('beta') + plan pro; si no → regular que paga.
2. **Welcome** (`send_lifecycle_welcome`, cron horario): a quien no tiene welcome.
   `welcome_beta` / `welcome_regular` según cohorte.
3. **Inactividad** (`run_beta_lifecycle`, cron diario 15:00 UTC): clasifica cada
   beta activo y manda **un** email por corrida.

### Tiers de inactividad (ventana rodante desde la última actividad)

| Tier | Detección | Nudges | Reclaim auto |
|---|---|---|---|
| ghost | sin evento significativo desde enrolamiento | d3/7/14 | día 21 |
| brief | tiene actividad, span < 30d | reengage d7/14 | ~60d inactivo |
| established | span de actividad ≥ 30d | reengage d7/14 | ~180d inactivo |

Invariante: **nunca se reclama sin un aviso previo** (`reclaim_warned_at` ≥ grace).
El reclaim pone `beta_status=reclaimed`, `is_billing_exempt=false`, y loguea
`audit_record(action="beta.reclaimed")`. Acciones manuales del admin **nunca**
tocan `is_billing_exempt` — solo el reclaim automático.

### Interferencia con Graveyard (resuelta)

El sweep `detect_and_mark_stalled` (horario) escribe
`project_status_changed(new_value='stalled')` de forma automática. `significant_events_q()`
(`beta_lifecycle.py`, reutilizado por el admin) **excluye** ese evento para que el
auto-stall no resetee el reloj de inactividad. Kill/launch/revive manuales sí cuentan.

## Emails

- `core/notifications/email_templates.py` — **bilingüe** `{email_id: {en, es}}`
  (welcome_beta/regular, inactivity_1..4, reengage_1/2, reclaim_warn/final).
- `core/notifications/lifecycle.py` — `deliver()` idempotente: resuelve idioma vía
  `NotificationSettings.locale` (default en), respeta `dry_run` (sin efectos),
  registra en `EmailSend`, reintenta y cuenta fallos (admin a partir de 3).
- Provider `core/notifications/providers/resend.py` (REST vía `requests`).
- Sender `EMAIL_FROM` (default `Alfredo <alfredo@continuu.it>`); reply-to al fundador.
  Los emails de auth (confirm/magic-link/reset) siguen en Supabase.

## Admin

- Backend: `core/admin_api/beta_schema.py` (`AdminBetaQuery` / `AdminBetaMutation`,
  fusionados en `core/schema.py`). Queries: `adminBetaUsers`, `adminBetaPipeline`,
  `adminAppConfig`. Mutations: `adminSetBeta`, `adminSetBillingExempt`,
  `adminSetAppConfig`. Todo gateado por `_admin_user_id` + `audit_record`.
- Frontend: `frontend/src/app/(app)/admin/beta/page.tsx` (+ nav en `AdminShell`,
  documentos en `src/lib/graphql.ts`): pipeline, controles globales
  (enrollment/cap/dry_run), tabla filtrable y edición por usuario.

## Config (`app_config`, sin redeploy)

`dry_run` (default true), `beta_enrollment_open`, `beta_spot_cap` (50),
`significant_event_kinds`, `ghost_nudge_days` `[3,7,14]`, `ghost_reclaim_day` 21,
`reengage_days` `[7,14]`, `brief_reclaim_days` 60, `dormant_reclaim_days` 180,
`established_min_activity_days` 30, `reclaim_warn_grace_days` 7.

## Deploy / go-live

1. `migrate` (campos + seed + backfill: **todos los usuarios actuales excepto 3
   cuentas excluidas** → beta active/exento/pro; ver `assistant/0011`). `0028` abre
   enrollment.
2. Env vars (Render, ambos crons): `RESEND_API_KEY`, `EMAIL_FROM`, `FRONTEND_BASE_URL`.
3. Deploy con `dry_run=true` → revisar `/admin/beta` y `email_sends` (preview).
4. Test real a inbox propio (DNS Resend) + confirmar Stripe cobra a no-beta.
5. Go-live: `app_config.set("dry_run", False)` (o toggle en `/admin/beta`).

## Tests

SQLite forzado inline (ver `../CLAUDE.md` no — ver memoria de tests). Cobertura:
signup, clasificación de tiers, exclusión de auto-stall, secuencia fantasma,
reclaim con grace + audit, cold start (warn antes de reclaim), dry_run sin efectos,
idempotencia de `email_sends`, render bilingüe + selección por locale, y el admin
(list/pipeline/mutations + sweep de permisos).

Comando de tests (fuerza SQLite inline; el `conftest` no gana sobre el `.env` de Supabase):

```
DATABASE_URL="sqlite:////tmp/pb.db" /Users/alfredogutierrez/GitHub/continuity/.venv/bin/python -m pytest \
  core/notifications/ core/assistant/tests/test_quotas.py core/tests/test_beta_lifecycle.py -q ; rm -f /tmp/pb.db
```

## Operación / deploy (runbook)

Fusionado desde el antiguo `BETA_LIFECYCLE_README.md`. **Default: `dry_run = true`** — nada se
envía ni se reclama hasta apagarlo; en dry_run solo se escriben filas de preview en `email_sends`.

### Env vars (Render — declaradas en `render.yaml`, `sync: false` = se ponen en el dashboard)

| Var | Para qué |
|---|---|
| `RESEND_API_KEY` | Enviar emails. Vacío = no se manda nada real (solo dry_run). |
| `EMAIL_FROM` | Remitente. Default `Alfredo <alfredo@continuu.it>`. |
| `FRONTEND_BASE_URL` | URL para los CTA de los emails (`{{app_url}}`). |
| `SUPABASE_SERVICE_ROLE_KEY` | Resolver el email del usuario (ya existía). |

### Crons (Render)

- **Horario** (`continuity-notifications-hourly`): se le añadió `send_lifecycle_welcome` al inicio.
- **Diario** (`continuity-beta-lifecycle-daily`, **`0 15 * * *`** = 15:00 UTC): `run_beta_lifecycle`.

### Apagar `dry_run` (go-live) — sin redeploy

```python
# Render shell / Django shell
from core.services import app_config
app_config.set("dry_run", False)
app_config.set("beta_enrollment_open", True)  # si quieres abrir enrollment
```

(o desde el admin en `/admin/beta`). Para volver: `app_config.set("dry_run", True)`.

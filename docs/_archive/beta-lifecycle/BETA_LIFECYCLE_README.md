# Beta lifecycle — operación y deploy

> **⚑ ESTADO (actualizado 2026-06-26): IMPLEMENTADO Y DESPLEGADO.** El sistema está en código
> y corre como cron en Render (`run_beta_lifecycle`). Lo único que falta para envíos reales es
> apagar el flag `dry_run` (sigue en `true` por seguridad — ver abajo). Esta guía es operativa
> y vigente.

Sistema que separa **cohorte beta** de **exención de billing**, manda welcome +
secuencia de inactividad (3 tiers) vía Resend, y reclama cupos beta no usados.
Diseño completo en `PROPOSAL.md`; copys en `EMAIL_PROPOSAL.md`.

> **Default: `dry_run = true`.** Nada se envía ni se reclama hasta que lo apagues
> (ver abajo). En dry_run solo se escriben filas de preview en `email_sends`.

## Componentes

| Pieza | Archivo |
|---|---|
| Campos beta/billing en `AccountProfile` | `core/assistant/models.py` |
| Decisión de signup (enrollment vs regular) | `core/assistant/quotas.py` → `_apply_enrollment_decision` |
| Config global | `core/models.py` (`AppConfig`) + `core/services/app_config.py` |
| Ledger idempotente de emails | `core/notifications/models.py` (`EmailSend`) |
| Provider Resend | `core/notifications/providers/resend.py` |
| Envío idempotente + dry_run | `core/notifications/lifecycle.py` |
| Copys | `core/notifications/email_templates.py` |
| Welcome (cron horario) | `core/notifications/management/commands/send_lifecycle_welcome.py` |
| Inactividad/reclaim (cron diario) | `core/services/beta_lifecycle.py` + `core/management/commands/run_beta_lifecycle.py` |

## Env vars (Render)

| Var | Para qué |
|---|---|
| `RESEND_API_KEY` | Enviar emails. Vacío = no se manda nada real (solo dry_run). |
| `EMAIL_FROM` | Remitente. Default `Alfredo <alfredo@continuu.it>`. |
| `FRONTEND_BASE_URL` | URL para los CTA de los emails (`{{app_url}}`). |
| `SUPABASE_SERVICE_ROLE_KEY` | Resolver el email del usuario (ya existía). |

Ya están declaradas en `render.yaml` para ambos crons (marca `sync: false` = las pones en el dashboard).

## Crons (Render)

- **Horario** (`continuity-notifications-hourly`): se le añadió `send_lifecycle_welcome` al inicio (con `;` para que un fallo no bloquee lo demás).
- **Diario** (`continuity-beta-lifecycle-daily`, **`0 15 * * *`** = 15:00 UTC): `run_beta_lifecycle`.

## Config en runtime (`app_config`, sin redeploy)

Editable por fila en la tabla `app_config` (o por el admin cuando esté). Defaults sembrados por migración (`core/services/app_config.py:DEFAULTS`):

| key | default | qué controla |
|---|---|---|
| `dry_run` | `true` | apaga **todos** los envíos reales |
| `beta_enrollment_open` | `false` | si los nuevos signups entran a la beta |
| `beta_spot_cap` | `50` | cupos beta |
| `significant_event_kinds` | 9 kinds | qué cuenta como actividad (excluye auto-stall) |
| `ghost_nudge_days` / `ghost_reclaim_day` | `[3,7,14]` / `21` | secuencia fantasma |
| `reengage_days` | `[7,14]` | nudges de re-enganche (tiers activos) |
| `brief_reclaim_days` / `dormant_reclaim_days` | `60` / `180` | reclaim por tier |
| `established_min_activity_days` | `30` | umbral brief vs establecido |
| `reclaim_warn_grace_days` | `7` | días entre aviso y reclaim |

## Cómo apagar `dry_run` (go-live)

`dry_run` vive en `app_config`, **no** requiere redeploy. Cuando estés listo:

```python
# Render shell / Django shell
from core.services import app_config
app_config.set("dry_run", False)
app_config.set("beta_enrollment_open", True)  # si quieres abrir enrollment
```

(o desde el admin cuando esté la sección Beta). Para volver a dry_run: `app_config.set("dry_run", True)`.

## Orden de deploy seguro

1. `migrate` (aplica los campos + tablas + seed + backfill: **todos los usuarios actuales excepto 3 cuentas excluidas** → beta_cohort=active, exento 'beta', plan free→pro; ver `assistant/0011`).
2. Deploy con `dry_run=true` (default). Deja correr el cron diario 1 vez.
3. Revisa `email_sends` (dry_run rows) / admin: confirma a quién le caería qué.
4. Manda un test real a tu inbox (verifica DNS de Resend, anti-spam).
5. Confirma que Stripe está listo para cobrar a los no-beta (ya no hay exención automática).
6. `app_config.set("dry_run", False)` → go-live.

## Tests

SQLite en memoria. **Forzar SQLite inline** (el `conftest` no gana sobre el `.env` de Supabase):

```
DATABASE_URL="sqlite:////tmp/pb.db" /Users/alfredogutierrez/GitHub/continuity/.venv/bin/python -m pytest \
  core/notifications/ core/assistant/tests/test_quotas.py core/tests/test_beta_lifecycle.py -q ; rm -f /tmp/pb.db
```

Cobertura: signup (enrollment abierto/cerrado/cupo), clasificación de tiers, exclusión de auto-stall de Graveyard, secuencia fantasma, reclaim con grace + audit, cold start (warn antes de reclaim), dry_run sin efectos, idempotencia de `email_sends`.

# Notificaciones

Sistema de notificaciones (Telegram → WhatsApp) para empujar el resumen de analíticas y alertas a los canales que el usuario ya consulta.

**Estrategia**: arquitectura con abstracciones correctas desde el día 1 (Provider interface, outbox pattern, jobs idempotentes), pero implementación inicial mínima — Render Cron Jobs ejecuta management commands de Django, sin cola. Migrar a una cola real cuando duela; el contrato de `dispatcher.enqueue` no cambia.

---

## Estado actual

### Fase 1 — Esqueleto + Telegram link ✅

Listo en este módulo:

- **Modelos** ([models.py](models.py)): `NotificationSettings` (1 por user), `NotificationLink` (canal vinculado), `Notification` (outbox, dedupe por `(user_id, channel, kind, dedupe_key)`).
- **Providers** ([providers/](providers/)): `NotificationProvider` ABC, `TelegramProvider` (HTTP directo a `api.telegram.org`, sin SDK).
- **Dispatcher** ([dispatcher.py](dispatcher.py)): `enqueue()` UPSERT-idempotente; reusable por cualquier comando.
- **Webhook** ([views.py](views.py)): `/api/telegram/webhook/<secret>/` recibe `/start <token>` y vincula el `chat_id`.
- **GraphQL** ([schema.py](schema.py)): query `notificationSettings`, mutaciones `updateNotificationSettings`, `requestChannelLink(TELEGRAM)`, `disconnectChannel(...)`.
- **Comandos**:
  - `python manage.py setup_telegram_webhook --base-url <url>` — registra webhook con Telegram
  - `python manage.py test_notification --user-id <uuid> [--body "..."]` — envío manual end-to-end
- **Frontend**: `/settings/notifications` con conexión de Telegram y toggles por tipo de notificación.

### Fase 2 — Weekly digest (builder + comando) ✅

Listo:

- **Builder** ([builders.py](builders.py)): `build_weekly_digest(user_id) -> str` reusa `core.analytics.compute_analytics(user_id, LAST_7_DAYS)` y arma un mensaje MarkdownV2 con racha, top proyectos (con delta vs semana previa), backlog (vencidas/por vencer/abiertas, quick wins, almost there), proyectos durmiendo, ideas stale, funnel de ideas, horas de esfuerzo, y link al dashboard.
- **Comando** ([management/commands/send_weekly_digest.py](management/commands/send_weekly_digest.py)):
  - Diseñado para correr cada hora; respeta `setting.timezone + digest_day_of_week + digest_hour`.
  - Flags: `--force` (ignora horario, usa dedupe key única por timestamp para permitir re-envíos), `--user-id <uuid>`, `--all-verified`.
  - Dedupe natural en producción: `weekly:{iso_year}-W{iso_week}` → re-correr el cron es no-op.

Pendiente (lo único que queda de Fase 2):

- **Render Cron Job**. Agregar a `backend/render.yaml`:
  ```yaml
    - type: cron
      name: continuity-notifications-hourly
      runtime: python
      rootDir: backend
      plan: free
      schedule: "0 * * * *"
      buildCommand: "./build.sh"
      startCommand: "python manage.py send_weekly_digest && python manage.py send_sleeping_alerts && python manage.py send_due_reminders"
      envVars:
        # mismas refs que el web service: DATABASE_URL, SUPABASE_*, TELEGRAM_*, NOTIFICATIONS_DEFAULT_TIMEZONE
  ```
  El cron corre cada hora; el filtro de "es la hora del usuario" se hace dentro del comando, así que un solo cron cubre cualquier zona horaria. Los comandos `send_sleeping_alerts` / `send_due_reminders` aún no existen — Render los ignorará con error hasta que aterricen en Fase 3 (puedes dejar solo `send_weekly_digest` por ahora).

### Activación local de Fase 1

1. Crear bot con [@BotFather](https://t.me/BotFather) → `/newbot` → copiar token.
2. Variables de entorno (en `backend/.env`):
   ```
   TELEGRAM_BOT_TOKEN=<del paso anterior>
   TELEGRAM_BOT_USERNAME=<sin @, lo que va después de t.me/>
   TELEGRAM_WEBHOOK_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(32))">
   NOTIFICATIONS_DEFAULT_TIMEZONE=America/Mexico_City
   ```
3. Para webhook en localhost: túnel con `ngrok http 8000` o `cloudflared tunnel --url http://localhost:8000`.
4. Registrar webhook: `python manage.py setup_telegram_webhook --base-url https://<tu-tunel>`.
5. En la app → `/settings/notifications` → **Connect Telegram** → presionar Start en el bot → debe aparecer "✅ Connected".

En producción (Render): mismas envs en el dashboard, `--base-url https://continuity-backend.onrender.com`.

### Disparar el digest manualmente

Una vez que un usuario está conectado, puedes mandarle el resumen semanal en cualquier momento:

```powershell
python manage.py send_weekly_digest --force --user-id <uuid>
```

`--force` ignora el cron schedule (día/hora) y usa una `dedupe_key` única por ejecución, así que puedes correrlo varias veces y todas llegarán. Para enviar a todos los usuarios verificados de un golpe: `--all-verified --force`. Sin `--force`, solo manda a quienes están en su `(día, hora) local` configurada.

---

## Fase 3 — Sleeping alerts + Due reminders + Manuales

### Sleeping alerts

`management/commands/send_sleeping_alerts.py`:

- Para cada usuario con `sleeping_alerts_enabled`:
- Detectar proyectos donde `last_activity` cruzó **hoy** un umbral (7, 14, 30 días).
- `dedupe_key = f"sleeping:{project_id}:{threshold}"` → cada proyecto recibe máximo 3 alertas en su vida (una por umbral).
- Reutilizar `analytics.SLEEPING_THRESHOLD_DAYS`, `SLEEPING_BUCKET_MID`, `SLEEPING_BUCKET_LATE`.

```python
from core.analytics import SLEEPING_THRESHOLD_DAYS, SLEEPING_BUCKET_MID, SLEEPING_BUCKET_LATE
THRESHOLDS = [SLEEPING_THRESHOLD_DAYS, SLEEPING_BUCKET_MID, SLEEPING_BUCKET_LATE]

for project in Project.objects.filter(user_id=uid).exclude(status__in=["archived", "launched"]):
    days = (now - project.last_activity).days
    for t in THRESHOLDS:
        if days >= t:
            enqueue(
                user_id=uid,
                kind="sleeping_alert",
                dedupe_key=f"sleeping:{project.id}:{t}",
                body=builders.build_sleeping_alert(project, days_idle=days, threshold=t),
            )
```

### Due reminders

`management/commands/send_due_reminders.py`:

```python
for setting in NotificationSettings.objects.filter(due_reminders_enabled=True):
    cutoff = now + timedelta(hours=setting.due_reminder_lead_hours)
    tasks = Task.objects.filter(
        user_id=setting.user_id,
        done=False,
        due_date__isnull=False,
        due_date__lte=cutoff,
        due_date__gte=now,
    )
    for task in tasks:
        enqueue(
            user_id=setting.user_id,
            kind="due_reminder",
            dedupe_key=f"due:{task.id}",  # un aviso por tarea, ever
            body=builders.build_due_reminder(task),
        )
```

### Notificaciones manuales

Agregar a `notifications/schema.py`:

```python
@strawberry.mutation
def send_manual_notification(
    self, info: Info,
    target_user_ids: List[strawberry.ID],
    body: str,
    channels: Optional[List[NotificationChannel]] = None,
) -> int:
    uid = _user_id(info)
    settings = SettingsModel.objects.filter(user_id=uid, is_admin=True).first()
    if not settings:
        raise GraphQLError("Forbidden", extensions={"code": "FORBIDDEN"})

    sent = 0
    for target in target_user_ids:
        result = enqueue(
            user_id=uuid.UUID(str(target)),
            kind="manual",
            dedupe_key=f"manual:{uuid.uuid4()}",
            body=body,
            channels=[c.value for c in (channels or [])],
        )
        sent += result.sent
    return sent
```

Promover una cuenta a admin: `python manage.py shell` → `NotificationSettings.objects.filter(user_id="...").update(is_admin=True)`.

### Verificación Fase 3

- Crear proyecto, modificar `last_activity = now - timedelta(days=8)` por shell, correr `send_sleeping_alerts` → llega mensaje con threshold=7.
- Re-correr → no llega (dedupe).
- Crear tarea con `due_date = now + 23h`, correr `send_due_reminders` → llega.
- Mutación `sendManualNotification` con tu propio user_id (siendo admin) → llega.

---

## Fase 4 — WhatsApp vía Twilio

### Sandbox primero (sin esperar aprobaciones)

1. Activar [Twilio WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn) — gratis. Anotar `ACCOUNT_SID`, `AUTH_TOKEN`, número del sandbox (ej. `whatsapp:+14155238886`) y código de invitación (ej. `join brave-tiger`).
2. Variables nuevas:
   ```
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
   ```
3. `pip install twilio==9.x` y agregar a `requirements.txt`.
4. Crear `providers/whatsapp.py`:
   ```python
   from twilio.rest import Client
   from .base import NotificationProvider, DeliveryResult, ProviderError

   class TwilioWhatsAppProvider(NotificationProvider):
       channel = "whatsapp"

       def __init__(self):
           self.from_ = settings.TWILIO_WHATSAPP_FROM
           if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN):
               raise ProviderError("TWILIO_* not configured")
           self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

       def send(self, external_id, body, *, kind=None):
           try:
               msg = self.client.messages.create(
                   from_=self.from_,
                   to=f"whatsapp:{external_id}",
                   body=body,  # sandbox/24h-window allows free-form
               )
               return DeliveryResult(success=True, external_message_id=msg.sid)
           except Exception as e:
               return DeliveryResult(success=False, error=str(e))
   ```
5. UI: en `NotificationSettings.tsx` agregar sección **WhatsApp** con input de número (`+5215512345678`), botón Connect que llama `requestChannelLink(WHATSAPP)`. En sandbox marca `verified_at = now()` directamente sin webhook (instrucciones en UI: "Manda `join <código>` al +1 415 523 8886 desde WhatsApp").
6. Quitar el `raise NotImplementedError` de `requestChannelLink` para WhatsApp.

### Producción

Pasos en Twilio Console (1-3 días hábiles):

1. **WhatsApp Sender** → Request Access → Twilio gestiona el "embedded signup" con Meta.
2. Verificar negocio en Meta Business Manager (puede ser persona física como negocio).
3. Registrar **plantillas HSM** (una por `kind`):
   - `weekly_digest` — categoría **Utility** (~$0.012/conversación en MX). Variables: `{{1}}` streak, `{{2}}` proyectos top, etc.
   - `sleeping_alert` — Utility. Variables: `{{1}}` nombre del proyecto, `{{2}}` días idle.
   - `due_reminder` — Utility. Variables: `{{1}}` título de tarea, `{{2}}` cuándo vence.
4. Cada plantilla aprobada da un `content_sid`. Guardarlos en settings:
   ```python
   TWILIO_TEMPLATE_WEEKLY_DIGEST = "HX..."
   TWILIO_TEMPLATE_SLEEPING_ALERT = "HX..."
   TWILIO_TEMPLATE_DUE_REMINDER = "HX..."
   ```
5. Modificar `TwilioWhatsAppProvider.send` para que cuando `kind` mapee a un template, use `content_sid` + `content_variables` en lugar de `body`:
   ```python
   if kind in TEMPLATE_MAP:
       msg = self.client.messages.create(
           from_=self.from_, to=...,
           content_sid=TEMPLATE_MAP[kind],
           content_variables=json.dumps({"1": ..., "2": ...}),
       )
   ```
   El `body` libre solo funciona dentro de la ventana de 24h (después de que el usuario te escribe).
6. Los **builders** ahora tienen que devolver tanto el texto Markdown (para Telegram) como un dict de variables (para WhatsApp). Refactor sugerido: `build_weekly_digest(user_id) → BuiltMessage(text, variables)`.

### Verificación Fase 4

- **Sandbox**: vincular tu número → `python manage.py test_notification --user-id <uuid> --channel whatsapp` → llega en WhatsApp.
- **Producción**: tras aprobación, mismo flujo con número real → llega como template formateado.

---

## Fase 5 — Escalabilidad (diferida)

**No hacer hasta que duela.** Disparadores: cron tarda >5 min, fallos en pico, retraso percibido.

1. **`django-q2` sobre la misma Postgres** (sin Redis aún, ~$0/mes extra):
   ```python
   # En dispatcher.py:
   if settings.NOTIFICATIONS_USE_QUEUE:
       async_task("core.notifications.dispatcher._attempt_send", notif.id, link.id)
   else:
       _attempt_send(notif, link)  # camino actual
   ```
   Worker process en Render Starter ($7/mes) o como segundo `cron` que llame `python manage.py qcluster`.
2. **Métricas**: tasa éxito por canal, latencia p50/p95, tiempo de cron. Endpoint `/api/metrics/` (Prometheus format) o Sentry transactions.
3. **Sentry** para captura de errores en providers.
4. **Backoff exponencial** en el campo `attempts`: `_attempt_send` solo procesa si `attempts < 5` y `now > created + 2^attempts minutes`.
5. Cuando `django-q2` sea cuello de botella → migrar a Celery + Redis. La firma de `dispatcher.enqueue` no cambia.

---

## Sobre licencias y permisos (resumen)

**Telegram**: gratis, sin licencias, sin templates obligatorios. Único requisito: cumplir [Telegram Bot ToS](https://telegram.org/tos/bots) (no spam). Opt-in implícito porque el usuario tiene que iniciar la conversación con el bot.

**WhatsApp**: 3 capas obligatorias:

1. **WhatsApp Business Account** vinculada a Meta Business (verificación de identidad).
2. **Número dedicado** verificado (no puede tener WhatsApp normal/Business app instalado).
3. **Templates HSM** pre-aprobados por Meta para mensajes proactivos fuera de la ventana de 24h. Categorías: **Utility** (recordatorios — más barato), **Marketing** (promocionales — más caro), **Authentication** (OTPs), **Service** (respuestas).

Costos típicos vía Twilio en MX (verificar [pricing actual](https://www.twilio.com/whatsapp/pricing)):
- Utility conversation: ~$0.012 USD/conversación de 24h
- Marketing: ~$0.044 USD
- Twilio agrega ~$0.005 USD encima

El **sandbox de Twilio es gratis** y suficiente para validar todo el sistema antes de invertir en aprobaciones — el usuario manda un código de invitación y queda habilitado por 72h.

---

## Patrones a respetar

- **Idempotencia**: nunca llamar `Notification.objects.create()` directo; siempre `dispatcher.enqueue()` con `dedupe_key` significativo. Re-correr el cron tiene que ser un no-op.
- **Templates por canal y kind**: nunca `body=f"Hola {nombre}"` inline. Reusable + traducible a HSM cuando llegue WhatsApp.
- **Provider abstracto**: nuevas plataformas (email, push, SMS) son una clase nueva en `providers/`, no un refactor.
- **Zonas horarias**: el cron corre en UTC pero las decisiones de scheduling se toman en `setting.timezone`. No usar `timezone.now().hour` para decidir; convertir primero.
- **Markdown V2**: cualquier contenido dinámico va por `md_escape()` antes de ir a `body`.

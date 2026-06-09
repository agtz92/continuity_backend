# Notifications

Notification system (Telegram → WhatsApp) that pushes the analytics digest and alerts to channels users already check.

**Strategy**: right abstractions from day 1 (Provider interface, outbox pattern, idempotent jobs), but minimal initial implementation — Render Cron Jobs run Django management commands, no queue. Migrate to a real queue when it actually hurts; the `dispatcher.enqueue` contract doesn't change.

---

## Current status

### Phase 1 — Skeleton + Telegram link ✅

Already in this module:

- **Models** ([models.py](models.py)): `NotificationSettings` (1 per user, holds toggles + schedule per digest type), `NotificationLink` (linked channel), `Notification` (outbox, dedupe on `(user_id, channel, kind, dedupe_key)`). `NotificationKind` values: `weekly_digest`, `daily_digest`, `sleeping_alert`, `due_reminder`, `manual`.
- **Providers** ([providers/](providers/)): `NotificationProvider` ABC + `InlineButton` TypedDict, `TelegramProvider` (direct HTTP to `api.telegram.org`, no SDK; converts `buttons` into `reply_markup.inline_keyboard`).
- **Dispatcher** ([dispatcher.py](dispatcher.py)): `enqueue()` UPSERT-idempotent; reusable from any command. Accepts an optional `buttons=[{text,url}, ...]` that is threaded through to the provider — channel-agnostic, graceful degradation for providers that don't render inline keyboards.
- **Webhook** ([views.py](views.py)): `/api/telegram/webhook/<secret>/` receives `/start <token>` and binds the `chat_id`.
- **GraphQL** ([schema.py](schema.py)): `notificationSettings` query, `updateNotificationSettings`, `requestChannelLink(TELEGRAM)`, `disconnectChannel(...)` mutations.
- **Commands**:
  - `python manage.py setup_telegram_webhook --base-url <url>` — registers the webhook with Telegram
  - `python manage.py test_notification --user-id <uuid> [--body "..."]` — manual end-to-end send
- **Frontend**: `/settings/notifications` with Telegram connect flow and per-type toggles.

### Phase 2 — Weekly digest (builder + command) ✅

Done:

- **Builder** ([builders.py](builders.py)): `build_weekly_digest(user_id) -> str` reuses `core.analytics.compute_analytics(user_id, LAST_7_DAYS)` and renders a MarkdownV2 message with active days, top projects (with delta vs previous week), backlog (overdue / due soon / open, quick wins, almost there), sleeping projects, stale ideas, idea funnel, logged hours, and a dashboard link.
- **Command** ([management/commands/send_weekly_digest.py](management/commands/send_weekly_digest.py)):
  - Designed to run hourly; respects `setting.timezone + digest_day_of_week + digest_hour`.
  - Flags: `--force` (ignore schedule, uses a unique-per-run dedupe key so re-sends are allowed), `--user-id <uuid>`, `--all-verified`.
  - Natural production dedupe: `weekly:{iso_year}-W{iso_week}` → re-running the cron is a no-op.

**Render Cron Job ✅**. Defined in [backend/render.yaml](../../render.yaml) as `continuity-notifications-hourly` (`schedule: "0 * * * *"`, `plan: starter` — cron isn't on Render's free tier). The hourly cron currently runs:

```yaml
startCommand: "python manage.py send_weekly_digest && python manage.py send_daily_digest && python manage.py send_due_reminders"
```

The "is it the user's hour?" filter happens inside each command, so a single cron covers any timezone. When `send_sleeping_alerts` ships in Phase 3, append it to the same `&&` chain.

### Phase 2.5 — Daily pending digest ✅

A per-user "today's pending" snapshot delivered at a user-chosen hour each day. Built on the same outbox/provider/cron infrastructure as the weekly digest.

- **Settings fields** added to `NotificationSettings`: `daily_digest_enabled` (bool, default `False`), `daily_digest_hour` (0-23, default `8`). Migration: `0006_notificationsettings_daily_digest_enabled_and_more`.
- **Builder** ([builders.py](builders.py)): `build_daily_digest(user_id, today=None) -> str` shares `_daily_context()` and `_render_pending_sections()` with the due-warning builder. The context queries `Task` directly (tasks where `done=False` and `due_date <= end_of_today_local`, split into overdue vs due-today) and pulls today's pending routines via [core/services/routines.py](../services/routines.py) `list_due_in_range(user_id, today, today)`, filtering out ones with a completed `RoutineOccurrence`. Three sections (⏰ overdue, 📌 due today, 🔁 routines today), each lists ALL items — no cap. Closes with a `daily.cta` line ("💪 *Marca tu progreso* a lo largo del día").
- **Command** ([management/commands/send_daily_digest.py](management/commands/send_daily_digest.py)):
  - Runs hourly (same cron). Filters by `now_local.hour == setting.daily_digest_hour` in the user's `setting.timezone`.
  - Natural dedupe: `daily:{YYYY-MM-DD}` (the user's local date) → one delivery per day per user.
  - `--force` uses a unique `daily:test:{ts}` key so test runs always re-send. Same `--user-id` / `--all-verified` flags as `send_weekly_digest`.
  - Passes a localized inline button `[{"text": s["daily.openDashboard"], "url": DASHBOARD_URL}]` to `enqueue()` — Telegram renders it as a tappable button below the message.
- **GraphQL** ([schema.py](schema.py)): `dailyDigestEnabled` and `dailyDigestHour` exposed on both query and `NotificationSettingsInput`.
- **Frontend**: new "Pendientes diarios" section in `/settings/notifications` (toggle + hour selector). All settings mutations write the response back into the Apollo cache via an `update` callback in [NotificationSettings.tsx](../../../frontend/src/components/notifications/NotificationSettings.tsx) — necessary because `NotificationSettingsType` has no `id` and Apollo otherwise can't auto-merge mutation results into the query cache.

### Phase 2.6 — End-of-day pending warning ✅

A conditional warning that fires at a user-chosen hour **only if items are still open** that day. The same data as the daily digest, framed as a heads-up ("⚠️ Aún tienes pendientes — Quedan *N* items abiertos hoy").

- **Settings fields** in `NotificationSettings`: `due_reminders_enabled` (bool, default `True`), `due_reminder_hour` (0-23, default `19` — 7pm). The legacy `due_reminder_lead_hours` was removed in migration `0007_remove_notificationsettings_due_reminder_lead_hours_and_more` — the original per-task lead-hours design (in the obsolete Phase 3 section below) was rejected because the daily digest already covers per-task awareness; the warning serves a different need.
- **Builder** ([builders.py](builders.py)): `build_due_warning(user_id, today=None) -> str | None` returns `None` when nothing's pending so the command can skip the send entirely (no outbox row, no Telegram call). When there is pending work, it reuses `_render_pending_sections()` with a warning-flavored intro (`due.title`, `due.lead`, `due.cta`).
- **Command** ([management/commands/send_due_reminders.py](management/commands/send_due_reminders.py)):
  - Runs hourly (same cron). Filters by `now_local.hour == setting.due_reminder_hour`.
  - Dedupe: `due_warning:{YYYY-MM-DD}` → at most one warning per day per user.
  - Reports `sent`, `skipped_by_schedule`, `skipped_empty` separately so the empty-no-op path is observable.
  - Same flags as the other digest commands; same inline button.
- **GraphQL**: `dueReminderHour` replaces `dueReminderLeadHours` on the query and input.
- **Frontend**: the existing toggle "Aviso de pendientes a fin de día" now pairs with an hour selector instead of a hours-of-lead number input.

### Phase 1 local activation

1. Create the bot via [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Env vars (in `backend/.env`):
   ```
   TELEGRAM_BOT_TOKEN=<from previous step>
   TELEGRAM_BOT_USERNAME=<no @, the part after t.me/>
   TELEGRAM_WEBHOOK_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(32))">
   NOTIFICATIONS_DEFAULT_TIMEZONE=America/Mexico_City
   ```
3. For webhook in localhost: tunnel with `ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`.
4. Register webhook: `python manage.py setup_telegram_webhook --base-url https://<your-tunnel>`.
5. In the app → `/settings/notifications` → **Connect Telegram** → press Start in the bot → "✅ Connected" appears.

In production (Render): same envs in the dashboard, `--base-url https://continuity-backend.onrender.com`.

### Trigger a digest manually

Once a user is connected, you can send any of the notifications at any time:

```powershell
python manage.py send_weekly_digest  --force --user-id <uuid>
python manage.py send_daily_digest   --force --user-id <uuid>
python manage.py send_due_reminders  --force --user-id <uuid>
```

`--force` ignores the cron schedule and uses a per-run unique `dedupe_key`, so each invocation delivers (except `send_due_reminders`, which still skips silently when there's nothing pending — that's a feature, not a schedule skip). To send to all verified users at once: `--all-verified --force`.

---

## Phase 3 — Sleeping alerts + Manual

> **Note**: the original Phase 3 design included per-task "due reminders" (one
> message per task crossing a `due_reminder_lead_hours` threshold). That design
> was replaced by the end-of-day warning above (Phase 2.6) — the daily digest
> already gives per-task awareness, so a separate stream of per-task pings was
> noise. The remaining Phase 3 work is sleeping alerts and manual
> notifications.

### Sleeping alerts

`management/commands/send_sleeping_alerts.py`:

- For each user with `sleeping_alerts_enabled`:
- Detect projects where `last_activity` crossed **today** a threshold (7, 14, 30 days).
- `dedupe_key = f"sleeping:{project_id}:{threshold}"` → each project gets at most 3 alerts in its lifetime (one per threshold).
- Reuse `analytics.SLEEPING_THRESHOLD_DAYS`, `SLEEPING_BUCKET_MID`, `SLEEPING_BUCKET_LATE`.

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

### Manual notifications

Add to `notifications/schema.py`:

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

Promote an account to admin: `python manage.py shell` → `NotificationSettings.objects.filter(user_id="...").update(is_admin=True)`.

### Phase 3 verification

- Create a project, set `last_activity = now - timedelta(days=8)` via shell, run `send_sleeping_alerts` → message arrives with threshold=7.
- Re-run → nothing (dedupe).
- Create a task with `due_date = now + 23h`, run `send_due_reminders` → message arrives.
- `sendManualNotification` mutation with your own user_id (as admin) → arrives.

---

## Phase 4 — WhatsApp via Twilio

### Sandbox first (no approvals required)

1. Activate the [Twilio WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn) — free. Note `ACCOUNT_SID`, `AUTH_TOKEN`, sandbox number (e.g. `whatsapp:+14155238886`), and the join code (e.g. `join brave-tiger`).
2. New env vars:
   ```
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
   ```
3. `pip install twilio==9.x` and add to `requirements.txt`.
4. Create `providers/whatsapp.py`:
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
5. UI: in `NotificationSettings.tsx` add a **WhatsApp** section with a phone number input (`+5215512345678`) and a Connect button that calls `requestChannelLink(WHATSAPP)`. In sandbox, mark `verified_at = now()` directly with no webhook (UI instructions: "Send `join <code>` to +1 415 523 8886 from WhatsApp").
6. Remove the `raise NotImplementedError` for WhatsApp from `requestChannelLink`.

### Production

Twilio Console steps (1-3 business days):

1. **WhatsApp Sender** → Request Access → Twilio handles "embedded signup" with Meta.
2. Verify the business in Meta Business Manager (sole proprietorship is OK).
3. Register **HSM templates** (one per `kind`):
   - `weekly_digest` — **Utility** category (~$0.012/conversation in MX). Variables: `{{1}}` active days, `{{2}}` top projects, etc.
   - `sleeping_alert` — Utility. Variables: `{{1}}` project name, `{{2}}` days idle.
   - `due_reminder` — Utility. Variables: `{{1}}` task title, `{{2}}` due date.
4. Each approved template gets a `content_sid`. Save them in settings:
   ```python
   TWILIO_TEMPLATE_WEEKLY_DIGEST = "HX..."
   TWILIO_TEMPLATE_SLEEPING_ALERT = "HX..."
   TWILIO_TEMPLATE_DUE_REMINDER = "HX..."
   ```
5. Update `TwilioWhatsAppProvider.send` so that when `kind` maps to a template, it uses `content_sid` + `content_variables` instead of `body`:
   ```python
   if kind in TEMPLATE_MAP:
       msg = self.client.messages.create(
           from_=self.from_, to=...,
           content_sid=TEMPLATE_MAP[kind],
           content_variables=json.dumps({"1": ..., "2": ...}),
       )
   ```
   Free-form `body` only works inside the 24h window (after the user messages you).
6. The **builders** now need to return both Markdown text (for Telegram) and a variables dict (for WhatsApp). Suggested refactor: `build_weekly_digest(user_id) → BuiltMessage(text, variables)`. The button infrastructure already in place (`enqueue(buttons=...)`, `InlineButton` TypedDict) doesn't need to change — `TwilioWhatsAppProvider.send` will receive `buttons` but ignore them (free-form WhatsApp messages can't render rich keyboards; approved HSM templates with quick-reply buttons can be wired up later as a separate enhancement).

### Phase 4 verification

- **Sandbox**: connect your number → `python manage.py test_notification --user-id <uuid> --channel whatsapp` → arrives on WhatsApp.
- **Production**: after template approval, same flow with the production number → arrives as a formatted template.

---

## Phase 5 — Scaling (deferred)

**Don't do this until it hurts.** Triggers: cron takes >5 min, provider failures during peaks, perceived delay from users.

1. **`django-q2` over the same Postgres** (no Redis yet, ~$0/mo extra):
   ```python
   # In dispatcher.py:
   if settings.NOTIFICATIONS_USE_QUEUE:
       async_task("core.notifications.dispatcher._attempt_send", notif.id, link.id)
   else:
       _attempt_send(notif, link)  # current path
   ```
   Worker process on Render Starter ($7/mo) or as a second `cron` running `python manage.py qcluster`.
2. **Metrics**: per-channel success rate, p50/p95 latency, cron duration. Endpoint `/api/metrics/` (Prometheus format) or Sentry transactions.
3. **Sentry** for provider error capture.
4. **Exponential backoff** on retries via the `attempts` field: `_attempt_send` only processes if `attempts < 5` and `now > created + 2^attempts minutes`.
5. When django-q2 becomes the bottleneck → migrate to Celery + Redis. The `dispatcher.enqueue` signature stays the same.

---

## Licenses & permissions (summary)

**Telegram**: free, no licenses, no required templates. Only requirement: comply with [Telegram Bot ToS](https://telegram.org/tos/bots) (no spam). Implicit opt-in because the user has to start the conversation with the bot.

**WhatsApp**: 3 mandatory layers:

1. **WhatsApp Business Account** linked to a Meta Business (identity verification).
2. **Dedicated number** verified (cannot be one already running WhatsApp regular/Business app).
3. **HSM templates** pre-approved by Meta for proactive messages outside the 24h window. Categories: **Utility** (reminders — cheaper), **Marketing** (promotional — pricier), **Authentication** (OTPs), **Service** (replies).

Typical Twilio costs in MX (verify [current pricing](https://www.twilio.com/whatsapp/pricing)):
- Utility conversation: ~$0.012 USD/24h conversation
- Marketing: ~$0.044 USD
- Twilio adds ~$0.005 USD on top

The **Twilio sandbox is free** and enough to validate the entire system before investing in approvals — the user sends a join code and gets enabled for 72h.

---

## Patterns to respect

- **Idempotency**: never call `Notification.objects.create()` directly; always `dispatcher.enqueue()` with a meaningful `dedupe_key`. Re-running the cron must be a no-op.
- **Per-channel and per-kind templates**: never inline `body=f"Hi {name}"`. Reusable + translatable to HSM when WhatsApp lands.
- **Provider abstraction**: new platforms (email, push, SMS) are a new class in `providers/`, not a refactor.
- **Timezones**: cron runs in UTC but scheduling decisions are made in `setting.timezone`. Don't use `timezone.now().hour` to decide; convert first.
- **Markdown V2**: any dynamic content must go through `md_escape()` before reaching `body`.
- **Inline buttons live outside the persisted body**: pass them via `enqueue(buttons=[...])`, not inline `[label](url)` syntax. The body stored in the outbox stays plain, providers attach the keyboard at send-time, and WhatsApp (which can't render rich keyboards in free-form messages) degrades cleanly. When you need a CTA, append a short motivating line to `body` and let the button carry the URL.

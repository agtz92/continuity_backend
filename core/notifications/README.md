# Notifications

Push notifications (Expo) for the analytics digests, reminders and admin announcements. Push is the **only** channel: Telegram was removed in 2026-10 (migration `0016_remove_telegram` dropped `NotificationLink` and the chat-channel outbox rows) and WhatsApp never shipped. Users without the mobile app get no digests.

**Strategy**: outbox pattern + idempotent jobs, no queue. A Render Cron Job runs Django management commands hourly; the `dispatcher.enqueue` contract stays the same if a queue is ever needed.

---

## Pieces

- **Models** ([models.py](models.py)): `NotificationSettings` (one per user: toggles + schedule per digest type, plus general prefs like locale/theme/timezone), `ExpoPushToken` (one per device, `device_id` is a per-install id), `Notification` (outbox, dedupe on `(user_id, channel, kind, dedupe_key)`; `body` stores what the phone showed). `NotificationKind`: `weekly_digest`, `daily_digest`, `sleeping_alert`, `due_reminder`, `manual`.
- **Provider** ([providers/expo.py](providers/expo.py)): direct HTTP to the Expo Push API, no SDK. `build_payload(token, push, kind=...)` is pure so tests assert on it. Dead tokens (`DeviceNotRegistered`) are pruned by the dispatcher.
- **Dispatcher** ([dispatcher.py](dispatcher.py)): `enqueue(user_id, kind, dedupe_key, push)` — no devices or push off → no-op (no row); already SENT → skipped; otherwise every device gets it. `push_recipients()` is the queryset of users that can receive a push; crons filter by it so nobody without the app costs an analytics run.
- **Builders** ([builders.py](builders.py)): each returns a `PushContent` ([providers/base.py](providers/base.py)) — a title with the number that matters ("8 pendientes para hoy, 3 atrasadas"), one line naming what to do first, deep link (`/today`, weekly → `/analytics`), Android channel (`daily` / `reminders` / `weekly` / `announcements`), `quiet` (weekly, iOS `passive`), and an action `category` + `data.taskIds`.
- **Strings** ([i18n/](i18n/)): plain-text `push.*` keys, en/es, plurals via `.one` / `.other` (`builders._plural`).
- **GraphQL** ([schema.py](schema.py)): `notificationSettings`, `updateNotificationSettings`, `registerPushToken`, `unregisterPushToken`, `runNotificationAction`. `NotificationSettingsType.links` is a deprecated, always-empty list kept so app builds from before the Telegram removal can still run their query — drop it once no client asks for it.

## Crons

Defined in [backend/render.yaml](../../render.yaml) as `continuity-notifications-hourly`. Each command decides "is it the user's hour?" in the user's `setting.timezone`, so one hourly cron covers every timezone.

| Command | Fires when | Dedupe key |
|---|---|---|
| `send_weekly_digest` | `digest_day_of_week` + `digest_hour` | `weekly:{iso_year}-W{iso_week}` |
| `send_daily_digest` | `daily_digest_hour` | `daily:{YYYY-MM-DD}` |
| `send_due_reminders` | `due_reminder_hour`, **only if something is still open** (the builder returns `None` otherwise) | `due_warning:{YYYY-MM-DD}` |
| `send_announcement_push` | an active announcement the user hasn't received | `announcement:{id}` |

Flags on the digest commands: `--force` (ignore the schedule; unique per-run dedupe key so it re-sends) and `--user-id <uuid>`.

```powershell
python manage.py send_weekly_digest --force --user-id <uuid>
python manage.py send_daily_digest  --force --user-id <uuid>
python manage.py send_due_reminders --force --user-id <uuid>
python manage.py test_notification  --user-id <uuid> --title "Hola" --body "Prueba"
```

## Action buttons

The app registers the categories (`continuity-mobile/src/lib/notifications.ts`) and calls `runNotificationAction(action: COMPLETE|POSTPONE, taskIds)` ([schema.py](schema.py) → [actions.py](actions.py)):

- `task_focus` → **Marcar hecha** · **Pasar a mañana** (daily digest's focus task; due warning with exactly one task).
- `tasks_bulk` → **Pasar todas a mañana** (due warning with several tasks).
- No category when nothing can be acted on (routines only, empty day, weekly).

Both actions are idempotent: complete never un-completes; postpone moves only open tasks due today or earlier to tomorrow in the user's timezone, keeping the time of day. Buttons open the app (`opensAppToForeground`), so the action runs authenticated.

**Android channels are gated**: Android drops a push aimed at a channel the device hasn't created, and the app creates them in JS. `channelId` is only sent when `EXPO_PUSH_ANDROID_CHANNELS=True`.

Tests: [tests/test_push_redesign.py](tests/test_push_redesign.py).

## Patterns to respect

- **Idempotency**: never call `Notification.objects.create()` directly; always `dispatcher.enqueue()` with a meaningful `dedupe_key`. Re-running the cron must be a no-op.
- **Strings live in `i18n/`**: never inline `f"Hi {name}"` in a builder.
- **Short by design**: the lock screen shows about two lines. Lead with the number, name one thing to do.
- **Timezones**: the cron runs in UTC but scheduling decisions use `setting.timezone`. Convert before comparing hours.

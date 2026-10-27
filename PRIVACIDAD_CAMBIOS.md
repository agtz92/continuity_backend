# Privacidad y manejo de datos: bitácora

Registro vivo del trabajo para que el manejo de datos coincida con la política de
privacidad. Cubre backend, web (`frontend/`) y móvil (`continuity-mobile/`).
Se actualiza cada vez que se cierra o se agrega algo.

- **Proyecto en continuu.it:** "Privacidad y manejo de datos" (`3b439d48-5577-48da-9a65-7ad41aceeb0a`).
- **Última actualización:** 2026-10-27

---

## Hecho

### 2026-10-26: política de privacidad reescrita
Frontend `80300b3`.
- Reescrita en `messages/{en,es}.json` a partir de un inventario de lo que recopilan el backend, la web y el móvil.
- Nombra a cada proveedor: Google Analytics, Anthropic (Loop), el conector MCP, Google Tasks/Calendar, el feed iCal, Expo, Resend y RevenueCat (antes decía Stripe).
- Detalla las cookies y el almacenamiento local, quién tiene acceso interno, qué se conserva al borrar la cuenta y cómo ejercer cada derecho (ARCO en la versión en español).

### 2026-10-26: borrado de cuenta completo
Backend `d6de6d4`.
- `deleteAccount` dejaba datos vivos. Ahora borra en la misma transacción todo lo listado en `USER_OWNED_MODELS`, incluidos:
  - Quick Notes y sus secciones.
  - `GraveyardInsight` e `InteractionDay`.
  - Los codes, refresh tokens y eventos OAuth del conector.
  - `EmailSend` y `BugReport`.
- Lo que se conserva por facturación o auditoría queda sin vínculo a la persona:
  - `StoreWebhookEvent`: `app_user_id` vacío y payload reducido a campos contables.
  - `AdminAuditLog`: payload redactado.
  - `Announcement`: se quita el id de la audiencia. Si era el único destinatario, el anuncio se archiva.
- `test_account_deletion.py` falla si aparece un modelo con campo `*user_id*` que no esté ni borrado ni listado como retenido.

### 2026-10-26: notificaciones solo por push
Backend `1f3d211`, frontend `6597579`, móvil `bf5167e`.
- Se retiraron Telegram, WhatsApp/Twilio (nunca tuvo provider) e iCloud CalDAV (nunca tuvo la dependencia).
- Migraciones:
  - `notifications/0016` borra los vínculos y el outbox de Telegram, que guardaba digests completos.
  - `core/0038` borra `ICloudCalendarCredential`.
- `NotificationSettingsType.links` queda deprecado y siempre vacío, para no romper builds viejos de la app.
- Las env vars `TELEGRAM_*` y `TWILIO_*` ya se quitaron de Render.

### 2026-10-26: consentimiento de Google Analytics
Frontend `b6c06c2`.
- GA4 solo se carga en el sitio público y solo después de aceptar el banner (`ConsentBanner`). Usa Consent Mode v2 con todo lo de anuncios en denied.
- No se carga en la app, el admin ni `/oauth/consent` (que lleva `state` y `code_challenge` en la URL).
- El enlace "Preferencias de cookies" del footer reabre el banner. Al retirar el permiso se borran las cookies `_ga*` y la página se recarga.

### 2026-10-26: borrar cuenta desde la web
Frontend `b6c06c2`.
- La sección está en Ajustes → Perfil (`DeleteAccountSection`) y avisa que borrar la cuenta no cancela la suscripción.
- Para confirmar hay que escribir el correo de la cuenta. Después se limpia el almacenamiento de captura y se cierra la sesión.

### 2026-10-26: baja de correos de ciclo de vida
Backend `1346adf`, frontend `b6c06c2`.
- Los correos de bienvenida, inactividad y reenganche llevan:
  - Un enlace de baja firmado (`core/notifications/unsubscribe.py`).
  - Los headers `List-Unsubscribe` + `List-Unsubscribe-Post` (RFC 8058).
- El GET del enlace solo muestra una confirmación; la baja se hace con POST, porque los escáneres de correo abren los enlaces solos.
- Opt-out: el campo `NotificationSettings.lifecycle_emails_enabled` (migración `0017`) tiene su toggle en Ajustes → Notificaciones de la web.
- Los avisos de cuenta (`reclaim_warn`, `reclaim_final`) se envían siempre.

### 2026-10-26: retención y purga
Backend `1346adf`.
- Comando `purge_expired_data` (`core/services/retention.py`), en el cron horario `continuity-notifications-hourly`. Ya está agregado al Start Command en Render.

  | Dato | Plazo | Acción |
  |---|---|---|
  | `Notification.body` / `error` | 90 días | Se vacían (la fila queda para deduplicar) |
  | `EmailSend.error` / `resend_message_id` | 180 días | Se vacían |
  | `StoreWebhookEvent.payload` | 400 días | Se vacía |
  | `BugReport` archivado | 1 año desde `updated_at` | Se borra |
  | `OAuthConnectionEvent` | 1 año | Se borra |

- Los plazos también están en la sección de retención de la política.

### 2026-10-27: limpiar la captura al cerrar sesión (web)
Frontend `cba4a76`.
- `Providers` escucha `SIGNED_OUT` de Supabase y llama a `clearCaptureStorage()`, que borra `continuity:capture-draft` y `continuity:capture-queue`.
- Cubre los tres casos: el botón de cerrar sesión, una sesión expirada y un cierre de sesión en otra pestaña.

---

## Pendiente

### Lo hace el dueño (fuera del código)
- [ ] **[URGENTE]** Rotar la contraseña de Postgres de producción (expuesta en commits públicos de `continuity_backend`) y actualizarla en Render y en `.env`.
- [ ] **[URGENTE]** Confirmar que la API key vieja de Anthropic está revocada.
- [ ] **[URGENTE]** Borrar el bot de Telegram en BotFather.
- [ ] **[Bloqueante]** Definir el responsable del tratamiento (persona o empresa, con domicilio) y añadirlo a la política, como pide el aviso de privacidad de la LFPDPPP.
- [ ] Confirmar la región de Supabase y de Render, y ajustar la sección de transferencias internacionales.
- [ ] Revisar y aceptar los DPA de Supabase, Render, Vercel, Anthropic, RevenueCat, Resend y Expo.
- [ ] Llenar las App Privacy labels (App Store) y el Data safety (Google Play) de acuerdo con la política.
- [ ] Revisión legal de la política y de los Terms con un abogado.

### Código
- [ ] Actualizar los Terms: reemplazar Stripe por RevenueCat (Web Billing + App Store/Google Play).
- [ ] Minimizar lo que se guarda del payload de RevenueCat (quitar `subscriber_attributes` y campos no necesarios).
- [ ] iOS: declarar el privacy manifest (`ios.privacyManifests` en `app.json`, con la razón de UserDefaults/AsyncStorage).
- [ ] Móvil: llamar `unregisterPushToken` al cerrar sesión y al borrar la cuenta, y limpiar AsyncStorage (deviceId, prefs).
- [ ] Borrar conversaciones del asistente una por una (endpoint DELETE + UI en web y móvil).
- [ ] Permitir editar el nombre desde `settings/profile` en la web (derecho de rectificación).
- [ ] Export completo (portabilidad): incluir Quick Notes, rutinas, categorías, bloqueos y conversaciones en el JSON, en web y móvil.
- [ ] Exponer la exportación de datos en la app móvil (`useBackup` existe, pero ninguna pantalla lo usa).

### Sin verificar
- Borrar cuenta y el cierre de sesión en la web con una sesión real (solo tsc y tests).
- GA4 en `admon.continuu.it`: por el código no se carga, pero no se abrió el dominio.

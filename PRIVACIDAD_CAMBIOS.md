# Privacidad y manejo de datos: bitácora

Registro vivo del trabajo para que el manejo de datos coincida con la política de
privacidad. Cubre backend, web (`frontend/`) y móvil (`continuity-mobile/`).
Se actualiza cada vez que se cierra o se agrega algo.

- **Proyecto en continuu.it:** "Privacidad y manejo de datos" (`3b439d48-5577-48da-9a65-7ad41aceeb0a`).
- **Última actualización:** 2026-10-28 (GA mide el registro)

---

## Hecho

### 2026-10-28: GA mide el registro (`sign_up`)
Frontend `ab26859`.
- GA (con el mismo consentimiento) se carga también en `/login` (con el banner) y en `/onboarding` (sin banner: solo si ya se aceptó). Nunca en `admon.*`, el dashboard ni el admin.
- Evento `sign_up` con un solo parámetro, `method` (`email` o `google`). No lleva correo, nombre ni id de usuario.
  - Email: al enviar el formulario de registro, solo si Supabase creó la cuenta (un correo ya registrado no cuenta).
  - Google: la primera vez que una cuenta de Google creada hace menos de 30 min llega al onboarding (`SignupTracker`).
- La política (`legal.privacy` en `messages/{en,es}.json`) ya no dice que GA "nunca se carga dentro de la aplicación"; nombra estas pantallas y el evento. Fecha de actualización: 28 de octubre.

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

### 2026-10-27: pendientes de código
Backend `ffc7389`, frontend `d43f3ea`, móvil `268605f` + `67aa177` (manifest).

- **Payload de RevenueCat mínimo.** `store_webhook` guarda solo `BILLING_EVENT_FIELDS` (`minimal_payload` en `core/billing/store_webhooks.py`): nada de `subscriber_attributes`, aliases ni `app_user_id` dentro del JSON (este sigue en su columna). La migración `billing/0002` recorta las filas ya guardadas. `account_deletion` reutiliza el mismo helper.
- **Terms con RevenueCat.** "Planes, pagos y renovaciones" ya no dice Stripe a secas: Web Billing en la web (tarjetas por Stripe), App Store/Google Play en las apps. Se agregó que las compras de tienda se cancelan y reembolsan en la tienda, y que borrar la cuenta no cancela la suscripción. Fecha: 27 de octubre de 2026.
- **Editar el nombre en la web.** Campo "Nombre" en Ajustes → Perfil (`NameField`, `updateProfile(firstName)`, máx. 50). El móvil ya lo tenía; su límite bajó de 60 a 50 para coincidir con el backend.
- **Borrar conversaciones con Loop.** `DELETE /api/assistant/conversations/<id>/` (`ConversationDetailView`), sin gate de plan: quien bajó a Free puede seguir borrando. En web y móvil, la sección "Tus datos" de Perfil lista las conversaciones guardadas con su botón de borrar (antes no se veían en ningún lado: el chat solo muestra la actual).
- **Export completo.** Query `myDataExport` (`core/services/data_export.py`): perfil, preferencias, notificaciones, plan, categorías, proyectos, notas, tareas, bloqueos, rutinas y ocurrencias, ideas, Quick Notes y secciones, actividad, conversaciones con mensajes, bug reports y eventos del conector. Deja fuera credenciales, tokens push y contadores (`NOT_EXPORTED`, con motivo). `test_data_export.py` falla si un modelo nuevo de `USER_OWNED_MODELS` no está en ninguna de las dos listas. Botón "Descargar mis datos" en "Tus datos" de web (descarga) y móvil (hoja de compartir). El backup del dashboard sigue igual: es para restaurar, no para portabilidad.
- **Móvil: cerrar sesión limpio.** `src/lib/signOut.ts`: el botón da de baja el token push del dispositivo antes de cerrar sesión (después ya no hay sesión). `AuthProvider` borra en cada `SIGNED_OUT` el deviceId, las notificaciones descartadas, la última respuesta a una push y el caché de Apollo. Tema, paleta e idioma se quedan: son del dispositivo y el servidor los reaplica al entrar.
- **Token push con un solo dueño.** `registerPushToken` borra ese token de cualquier otra cuenta: si alguien cerró sesión sin darlo de baja (sesión expirada, sin red), sus avisos ya no llegan al teléfono de quien entra después.
- **Privacy manifest de iOS.** `ios.privacyManifests` en `app.json`: sin tracking; APIs con razón (UserDefaults CA92.1, FileTimestamp C617.1, SystemBootTime 35F9.1, DiskSpace E174.1); datos recopilados, todos ligados a la persona y sin tracking: correo, nombre, user ID, device ID (push), contenido, historial de compras e interacción con el producto. **Es config nativa: requiere un build nuevo, no llega por OTA.**

### 2026-10-27: claves rotadas y sin menciones a Stripe en el sitio
- El dueño rotó la contraseña de Postgres de producción y la API key de Anthropic.
- Frontend `1677966`: el sitio ya no nombra a Stripe. La política dice "RevenueCat y su procesador de tarjetas"; los Terms, solo RevenueCat Web Billing; el demo del landing cambió su decisión de ejemplo. En el admin, los textos dicen cobro/cliente y la tabla de billing muestra el id del cliente en vez del enlace al dashboard de Stripe.
- CMS revisado en producción (solo lectura): ningún blog post, recurso, categoría, página, media ni anuncio menciona a Stripe.
- Móvil `2295685`: los textos de Facturación ya no nombran a Stripe, y las queries de admin piden `billingCustomerId`/`billingTransactionId` (las `stripe*` ya no existían en el backend). Solo JS, pero antes de un OTA hay que revisar el diff de `package.json`/`app.json` contra el último build (ver `continuity-mobile/CLAUDE.md`).

---

### 2026-10-28: correo directo del admin a un usuario
- `adminSendUserEmail` manda un correo escrito a mano por Resend (proveedor ya nombrado en la política).
- Respeta la baja de correos de producto (se rechaza con `OPTED_OUT`) y lleva el pie de baja y los headers `List-Unsubscribe`.
- Asunto y cuerpo se guardan en `AdminAuditLog` (`user.send_email`, `target_type="user"`): el borrado de cuenta ya redacta ese payload. La fila de `EmailSend` se borra con la cuenta.

### 2026-10-28: export de datos con lista blanca de columnas
Backend `58e5502`. Revisando un export real salían un secreto y datos internos. Cambios en `core/services/data_export.py`:
- **Columnas por lista blanca** (`FIELDS`); lo que se deja fuera va en `OMITTED_FIELDS` con su motivo. `test_data_export.py` falla si una columna de un modelo exportado no está en ninguna de las dos, así una columna nueva ya no sale por omisión.
- **Fuera:** `calendar_feed_token` (daba acceso al feed de calendario), `is_admin`, flags de billing exento y beta, ids de sync (`google_task_id`, `calendar_event_id`, `client_token`, `parked_due_*`), estado de triaje de bug reports, `client_id` OAuth e ids secuenciales (revelaban volumen de la plataforma).
- **Conversaciones con Loop:** cada mensaje sale como `{role, text, created}`. Fuera los bloques `tool_use`/`tool_result`, el modelo, el `stop_reason` y los conteos de tokens y caché; lo que hicieron las tools ya está en `activity`.
- **Eventos del conector:** sin `token_refreshed` (uno por cada vida del token, mostraba la cadencia); quedan autorizar y revocar.
- **Correo:** `myDataExport` ahora incluye el email de la cuenta (Supabase auth, best-effort; si falla sale vacío).

### 2026-10-28: respaldo y restauración en el servidor
- **Un solo formato.** "Respaldo y restauración" de la web descarga el mismo JSON que `myDataExport`; ya no arma el archivo en el navegador con lo que tenía cargado el dashboard.
- **Restaurar es una mutation** (`restoreBackup`, `core/services/backup_restore.py`), en una transacción: o entra todo o nada. Antes eran cientos de mutations desde el navegador que chocaban con el rate limit (120/min) y en "reemplazar" podían borrar la cuenta sin restaurarla.
- **Aislamiento:** cada fila restaurada recibe un id nuevo y las referencias se remapean; un archivo no puede tocar filas de otra cuenta. Se restaura solo contenido (no ajustes, conversaciones ni datos de billing).
- Respeta los cupos del plan (si el respaldo los rebasa, no escribe nada) y acepta los respaldos viejos del cliente.
- `DATA_UPLOAD_MAX_MEMORY_SIZE` subió a 10 MB para que quepa el archivo.
- Móvil: se borró `useBackup.ts`, que no usaba ninguna pantalla y tenía la lógica vieja, y sus textos `modals.backup`.

## Pendiente

### Lo hace el dueño (fuera del código)
- [x] Borrar el bot de Telegram en BotFather (2026-10-27).
- [x] `DATABASE_URL` con la contraseña nueva en todos los servicios de Render y la IP de Render desbloqueada en Supabase (2026-10-27).
- [ ] **[Bloqueante]** Definir el responsable del tratamiento (persona o empresa, con domicilio) y añadirlo a la política, como pide el aviso de privacidad de la LFPDPPP.
- [x] GA4 no carga en `admon.continuu.it`: verificado por el dueño (2026-10-29).
- [x] Regiones confirmadas (2026-10-27): Supabase `us-east-2` (Ohio) y Render Oregon (US West). Las dos están en EE. UU., así que la sección de transferencias ("incluido Estados Unidos") ya es correcta.
- [ ] Revisar y aceptar los DPA de Supabase, Render, Vercel, Anthropic, RevenueCat, Resend y Expo.
- [ ] Llenar las App Privacy labels (App Store) y el Data safety (Google Play) de acuerdo con la política.
- [ ] Revisión legal de la política y de los Terms con un abogado.

### Código
Nada pendiente.

### Sin verificar
- Borrar cuenta y el cierre de sesión en la web con una sesión real (solo tsc y tests).
- "Tus datos" (web y móvil), el nombre en la web y el cierre de sesión del móvil: probados con tests, tsc y `expo export`, no con una sesión real ni en un dispositivo.
- El privacy manifest solo se valida al subir un build a App Store Connect.
- Las App Privacy labels de App Store Connect deben coincidir con el manifest (tarea del dueño).

# Integración con calendario

Exporta las **tareas** y **rutinas** de Continuity al calendario que el usuario ya
usa (iPhone/iCloud, Google Calendar, Outlook). Vive en el menú de plugins:
`/settings/plugins/calendar`.

## Qué SÍ está implementado

### 1. Hora opcional en tareas y rutinas
Las tareas/rutinas no tienen hora por defecto. Se añadió un selector de hora
**opcional** (componente `TimeOfDayField`, usado en `TaskModal` y `RoutineModal`):

- **Todo el día** (default) → se mantiene la filosofía sin hora; mapea a un
  evento de **día completo**.
- **Con hora** → revela **Inicio** + **Duración**; mapea a un evento con hora.

Datos: `Task.due_time` / `Task.duration_minutes` y
`Routine.time_of_day` / `Routine.duration_minutes` (migraciones `core/0029`,
`core/0030`; `notifications/0012` para la config de calendario).

### 2. Calendario externo — feed ICS suscribible (la única vía que se ofrece)
Una URL privada por usuario, servida en
`GET /api/calendar/feed/<token>.ics` (token de alta entropía, rotable desde la
UI). El usuario la **suscribe una vez** y su app de calendario la mantiene
actualizada:

- **iPhone/iPad:** Ajustes → Calendario → Cuentas → Añadir cuenta → Otra →
  Añadir calendario suscrito.
- **Google Calendar:** Otros calendarios → Desde URL.
- **Outlook:** Añadir calendario → Suscribir desde web.

Una sola implementación cubre las tres plataformas. Es **de una sola vía**
(Continuity → calendario), exactamente lo que se busca. Las tareas/rutinas sin
hora salen como eventos all-day; las rutinas salen como **un único evento
recurrente con RRULE** (el calendario expande las ocurrencias).

#### iOS — no requiere nada especial
Suscribirse en iPhone/iPad **no** necesita Apple ID ni contraseña de aplicación
(eso era solo para el CalDAV directo, que no se ofrece). Solo se añade un
calendario suscrito con la URL. Requisitos prácticos: la URL debe ser **pública
por HTTPS** (`BACKEND_PUBLIC_URL`, no localhost). iOS soporta el esquema
`webcal://`, que abre el diálogo de suscripción con un toque.

#### Limitación importante: NO es tiempo real
El `.ics` siempre refleja el estado actual **en el momento en que se pide** (se
genera al vuelo desde la BD). Pero **el cliente decide cada cuánto vuelve a
leer la URL**, y ese intervalo no lo controlamos:

- **Google Calendar:** refresca calendarios por URL cada ~8–24 h (no
  configurable).
- **iPhone/iCloud:** según el "Obtener datos" de la cuenta; típicamente de una a
  varias horas.

Es decir: si el usuario mueve, completa o borra una tarea, el cambio está en el
feed al instante, pero **puede tardar horas en verse** en su calendario. La UI
del plugin muestra una nota advirtiendo esto (`settings.plugins.calendar.latencyNote`).
El único camino a reflejo casi inmediato sería el push directo por API (ver
abajo), descartado a propósito.

Código: `core/services/calendar_export.py` (mapeo task/rutina → evento + RRULE),
`core/services/calendar_feed.py` (genera el `.ics` + token),
`core/calendar_views.py` (vista pública). Tests: `core/tests/test_calendar.py`.
Config: `BACKEND_PUBLIC_URL` (para construir la URL absoluta del feed).

## Qué NO está implementado (decisión técnica supervisada)

La **sincronización directa con Google Calendar (API)** y la **escritura directa
en iCloud (CalDAV)** **no se ofrecen en el producto**. No hay UI ni se ejecutan;
fue una decisión técnica deliberada y supervisada por el dueño del proyecto.

Razones:

- **Google `calendar.events` es un scope restringido.** Usarlo en producción
  exige pasar la *OAuth verification* de Google (y, para scopes restringidos,
  potencialmente una evaluación de seguridad CASA anual y de pago). Mucho trámite
  y costo para algo que el feed ICS ya resuelve.
- **iCloud CalDAV obliga a guardar credenciales de Apple** (Apple ID +
  app-specific password). Aunque se cifren, es superficie de seguridad, soporte y
  fragilidad innecesarios.
- **Mantenimiento:** el push directo implicaría cron, cuotas de API, manejo de
  `calendar_event_id`, borrados y reintentos. El feed es una URL que el cliente
  jala solo.
- La única ventaja perdida es la **inmediatez** (el feed refresca cuando el
  cliente decide; en iOS puede tardar horas). Para tareas/rutinas mayormente
  all-day es aceptable.

### Estado del código directo (inactivo)
Existe código base del push directo, **desconectado del producto** (sin UI, sin
cron). Si en el futuro se decide habilitarlo, está disponible como punto de
partida; hasta entonces se considera **no implementado / no soportado**:

- Backend inactivo: `core/services/google_calendar.py`,
  `core/services/icloud_calendar.py`, el modelo `ICloudCalendarCredential`, el
  comando `manage.py sync_calendars` y las mutations GraphQL
  `googleCalendarAuthUrl` / `disconnectGoogleCalendar` / `syncGoogleCalendarNow` /
  `connectIcloudCalendar` / etc. No están cableados a ninguna pantalla.
- `sync_calendars` **no** está en el cron de `render.yaml`.
- La dependencia `caldav` **no** se instala (`requirements.txt`); el módulo iCloud
  la importa de forma perezosa y reporta "no disponible" si se invocara.

## Pendientes
- Documentación de ayuda (docs/ayuda) de la nueva vista de plugins.
- Deploy a Render + verificación real de suscripción en iPhone/Google/Outlook
  (requiere `BACKEND_PUBLIC_URL` apuntando al backend público).

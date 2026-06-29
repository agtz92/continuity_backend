# EMAIL_PROPOSAL.md — Copys propuestos para el sistema de ciclo de vida beta

Borradores de **subjects + cuerpos** para todos los emails de producto del feature. Son
**propuestas** para que tú (el dueño del copy) edites y apruebes — tú controlas subjects y
cuerpos finales. Aquí dejo drafts listos para shipear con ajustes ligeros, más las convenciones
técnicas que el código necesita fijar.

> Recordatorio de stack: todos estos van por **Resend** (sender `alfredo@continuu.it`), sobre el
> outbox idempotente existente. Los emails de auth (confirmar signup, magic link, reset) **siguen
> en Supabase** y no están aquí.

---

## 0. Convenciones (esto sí lo fija el código)

| Campo | Valor propuesto |
|---|---|
| **From** | `Alfredo <alfredo@continuu.it>` (nombre "Alfredo", no "continuu no-reply") |
| **Reply-To** | `alfredo@continuu.it` — las respuestas llegan al fundador. En beta, esto **es** el canal de feedback. |
| **Formato** | HTML simple + versión texto plano. Estilo "carta personal": sin banners ni imágenes pesadas, una sola CTA. |
| **Idioma** | Español primero. Localizable vía la i18n existente (`frontend/messages`); arrancamos `es`, agregamos `en` después. |
| **Footer** | Welcome/reclaim son transaccionales. Los nudges llevan una línea de contexto + cómo parar ("responde este correo" o link a ajustes de notificación). |
| **dry_run** | Con `dry_run=true` no se envía nada; se registra en `email_sends` con `dry_run=true` y aparece en el admin para revisión. |

**Tokens de personalización disponibles:**
`{{first_name}}` · `{{app_url}}` · `{{last_project_title}}` (si existe) · `{{days_inactive}}` ·
`{{spot_cap}}`. Si un token está vacío, el copy debe leerse bien igual (fallbacks abajo).

---

## 1. Inventario de emails

| `email_id` | Trigger | Tier | Idempotencia |
|---|---|---|---|
| `welcome_beta` | Tras verificar email, si `beta_cohort=true` | beta | 1 vez por usuario |
| `welcome_regular` | Tras verificar email, si no beta | regular | 1 vez por usuario |
| `inactivity_1` | Día 3 sin actividad | Fantasma | 1 vez por usuario |
| `inactivity_2` | Día 7 sin actividad | Fantasma | 1 vez por usuario |
| `inactivity_3` | Día 14 — set `reclaim_warned_at` | Fantasma | 1 vez por usuario |
| `inactivity_4` | Día 21 — reclaim del cupo | Fantasma | 1 vez por usuario |
| `reengage_1` | Lapso temprano (estuvo activo y se apagó) | Breve / Establecido | **por episodio** |
| `reengage_2` | Lapso prolongado, antes del aviso | Breve / Establecido | **por episodio** |
| `reclaim_warn` | Antes del reclaim (~60d breve / ~180d establecido) — set `reclaim_warned_at` | Breve / Establecido | **por episodio** |
| `reclaim_final` | Reclaim ejecutado del cupo | Breve / Establecido | **por episodio** |

> `inactivity_1..4` = exactamente la secuencia original de la spec (camino fantasma). Los 4 `reengage_*`/`reclaim_*`
> son nuevos, del modelo refinado (tiers + ventana rodante). Fantasma = terminal (una vez). Activo = re-armable por episodio.

---

## 2. Welcome

### `welcome_beta`
**Subject (A):** Estás dentro 🎉
**Subject (B):** Bienvenido a la beta de continuu, {{first_name}}
**Preheader:** Tu lugar está reservado. Esto es lo que significa.

> Hola {{first_name}}:
>
> Soy Alfredo, hice continuu. Acabas de entrar a la beta — eres una de **{{spot_cap}} personas** con
> acceso temprano, y eso viene con dos cosas:
>
> 1. **Acceso de por vida, sin pagar**, mientras seas parte de la beta. Es mi forma de agradecer que construyas esto conmigo.
> 2. **Te voy a pedir feedback.** No mucho — pero cuando algo te estorbe o te encante, respóndeme este correo. Lo leo yo.
>
> ¿Por dónde empezar? Crea tu primer proyecto o suelta una idea que traigas en la cabeza. continuu está hecho para que no se te caiga nada.
>
> **[ Abrir continuu → ]({{app_url}})**
>
> Gracias por estar temprano,
> Alfredo

*Fallback sin `first_name`: "Hola:".*

### `welcome_regular`
**Subject (A):** Bienvenido a continuu
**Subject (B):** Tu cuenta de continuu está lista
**Preheader:** Empieza por tu primer proyecto.

> Hola {{first_name}}:
>
> Bienvenido a continuu. La idea es simple: un solo lugar para tus proyectos, tareas, rutinas e ideas, sin que nada se pierda en el camino.
>
> El mejor primer paso es crear un proyecto con algo que ya traigas pendiente — en dos minutos le ves el sentido.
>
> **[ Abrir continuu → ]({{app_url}})**
>
> Cualquier cosa, responde este correo.
> Alfredo

---

## 3. Camino fantasma (nunca creó nada)

Tono: servicial, nunca culposo. Asumimos fricción, no desinterés — hasta el día 14.

### `inactivity_1` — Día 3
**Subject (A):** ¿Te ayudo a arrancar?
**Subject (B):** Tu primer proyecto en continuu
**Preheader:** Tres días dentro y aún en blanco — normal, va esto.

> Hola {{first_name}}:
>
> Te registraste hace unos días pero aún no has creado nada en continuu — y eso casi siempre es porque el primer paso no quedó claro, no porque no te interese.
>
> Prueba esto: abre continuu y crea **un** proyecto con algo que ya tengas pendiente. Solo el título basta. Desde ahí todo se acomoda.
>
> **[ Crear mi primer proyecto → ]({{app_url}})**
>
> Alfredo

### `inactivity_2` — Día 7
**Subject (A):** Lo que continuu hace cuando lo dejas correr
**Subject (B):** ¿Le damos otra oportunidad?
**Preheader:** Una semana. Te muestro el por qué en 30 segundos.

> Hola {{first_name}}:
>
> Una semana dentro y continuu sigue vacío. Sin presión — pero déjame mostrarte para qué sirve, por si se perdió en el camino:
>
> - **Proyectos** que agrupan tus tareas sin volverse un caos.
> - **Rutinas** que reaparecen solas cuando toca.
> - **Ideas y notas** que capturas en segundos y no se te olvidan.
>
> Todo vive en una vista "Today" que te dice qué sigue. Empieza con un proyecto y lo demás cae por su peso.
>
> **[ Probar continuu → ]({{app_url}})**
>
> Alfredo

### `inactivity_3` — Día 14 *(set `reclaim_warned_at`)*
**Subject (A):** Tu lugar en la beta
**Subject (B):** ¿Sigues con nosotros, {{first_name}}?
**Preheader:** Los lugares de la beta son contados. Aviso honesto.

> Hola {{first_name}}:
>
> Te escribo con honestidad: la beta tiene **{{spot_cap}} lugares** y hay gente en lista de espera. Tú tienes uno reservado, pero llevas dos semanas sin usar continuu.
>
> Si continuu no es para ti ahora mismo, está perfecto — pero en ese caso voy a liberar tu lugar para alguien que lo aproveche.
>
> Si sí quieres quedarte, basta con que entres y crees algo esta semana. Con eso conservas tu acceso de por vida.
>
> **[ Conservar mi lugar → ]({{app_url}})**
>
> Alfredo

### `inactivity_4` — Día 21 *(reclaim ejecutado, `billing_exempt=false`)*
**Subject (A):** Liberé tu lugar en la beta
**Subject (B):** Tu lugar en la beta quedó libre (puedes volver)
**Preheader:** Sin drama — la puerta sigue abierta.

> Hola {{first_name}}:
>
> Como no hubo movimiento, liberé tu lugar de la beta para alguien de la lista de espera. Sin rencores — los tiempos no siempre cuadran.
>
> **Tu cuenta sigue viva.** Puedes seguir usando continuu en el plan normal cuando quieras, y tus datos están intactos.
>
> Y si más adelante quieres volver a la beta, respóndeme este correo. Te hago un lugar si hay.
>
> **[ Entrar a continuu → ]({{app_url}})**
>
> Alfredo

---

## 4. Camino activo (estuvo activo y se apagó · breve o establecido)

Tono: reconoce que ya conoce continuu. Nada de "bienvenido". Es un "¿seguimos?".
Re-armable por episodio: si vuelve y se va meses después, la secuencia corre de nuevo.

### `reengage_1` — Lapso temprano
**Subject (A):** ¿Seguimos donde lo dejaste?
**Subject (B):** continuu te está esperando, {{first_name}}
**Preheader:** Llevas {{days_inactive}} días fuera. Retomar es fácil.

> Hola {{first_name}}:
>
> Estuviste usando continuu y de repente desapareciste — {{days_inactive}} días. Pasa.
>
> Lo bueno es que retomar no cuesta: **{{last_project_title}}** sigue ahí esperándote, justo donde lo dejaste.
>
> **[ Retomar → ]({{app_url}})**
>
> Alfredo

*Fallback sin `last_project_title`: "tus proyectos siguen ahí, justo donde los dejaste."*

### `reengage_2` — Lapso prolongado
**Subject (A):** ¿continuu sigue siendo para ti?
**Subject (B):** Una última señal antes de soltar
**Preheader:** Si ya no te sirve, lo entiendo. Solo dime.

> Hola {{first_name}}:
>
> Hace rato que no entras a continuu. Quiero preguntártelo directo: ¿sigue siéndote útil?
>
> Si sí, entra y retómalo — basta con que muevas algo.
> Si no, respóndeme y dime por qué dejó de funcionarte. Ese feedback me sirve más de lo que crees.
>
> **[ Volver a continuu → ]({{app_url}})**
>
> Alfredo

### `reclaim_warn` — Antes del reclaim *(set `reclaim_warned_at`)*
**Subject (A):** Voy a liberar tu lugar en la beta
**Subject (B):** Tu lugar beta, {{first_name}} (aviso)
**Preheader:** Última llamada antes de pasárselo a otra persona.

> Hola {{first_name}}:
>
> Fuiste parte activa de la beta, así que esto no es automático de golpe — te aviso primero.
>
> Llevas mucho tiempo sin entrar y hay gente esperando un lugar. Si no vuelves en los próximos días, voy a liberar el tuyo (y con él, tu acceso de por vida).
>
> Si quieres conservarlo, solo entra y mueve algo esta semana.
>
> **[ Conservar mi lugar → ]({{app_url}})**
>
> Alfredo

### `reclaim_final` — Reclaim ejecutado *(`billing_exempt=false`)*
**Subject (A):** Liberé tu lugar en la beta
**Subject (B):** Tu lugar beta quedó libre — gracias por haber estado
**Preheader:** Tu cuenta sigue. La puerta también.

> Hola {{first_name}}:
>
> Liberé tu lugar de la beta para alguien de la lista. Gracias de verdad por el tiempo que sí estuviste — ayudó a mejorar continuu.
>
> **Tu cuenta y tus datos siguen intactos**, y puedes usar continuu en el plan normal cuando quieras. Si quieres volver a la beta más adelante, respóndeme.
>
> **[ Entrar a continuu → ]({{app_url}})**
>
> Alfredo

---

## 5. Notas para implementación

- **Subjects A/B:** dejé dos por email por si quieres A/B test más adelante; el código arranca con **A**.
- **Una sola CTA por correo** apuntando a `{{app_url}}` (deep-link al proyecto cuando aplique en `reengage_1`).
- **Texto plano:** generar versión sin formato desde el mismo cuerpo (Resend manda ambos).
- **`reclaim_warn` vs `inactivity_3`:** ambos setean `reclaim_warned_at`; el reclaim final exige que el aviso tenga ≥ los días de gracia configurados, para que nunca se reclame sin aviso previo.
- **Localización:** las claves de copy viven como `email.<email_id>.subject` / `.body` en la i18n; este doc es la fuente `es`.

**STOP.** Tú editas los copys finales. Cuando los apruebes, los muevo a plantillas en código
(`core/notifications/...`) con los tokens cableados. Siguiente deliverable técnico pendiente:
`PROPOSAL.md` (schema + migración + cron).

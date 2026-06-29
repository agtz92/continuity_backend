# Brief de copy — Emails de ciclo de vida beta (continuu.it)

Para el agente de marketing. Devuelve el copy en `.md` siguiendo **exactamente** el formato de
la sección "Formato de entrega" (al final). Necesito **10 emails × 2 idiomas (inglés + español)**.

---

## 1. Contexto

**Producto:** continuu — app de productividad personal. El usuario organiza **proyectos, tareas,
rutinas, ideas y notas**, todo en una vista llamada **"Today"** que le dice qué sigue. Hay un
asistente de IA llamado **Loop** (opcional, no central para estos emails).

**Audiencia:** usuarios en beta. La beta da **acceso de por vida sin pago** (lifetime deal) a
cambio de uso + feedback. Hay cupos limitados.

**Quién escribe:** **Alfredo**, el fundador. Voz en **primera persona**, cálida, directa,
honesta, sin corporativismo. Remitente: `alfredo@continuu.it`. Las respuestas le llegan a él
(es el canal de feedback de la beta).

**Idiomas:** inglés y español. Se elige por la preferencia del usuario (`locale`). Ambos deben
sonar **nativos**, no traducidos literalmente. El español es **neutro/latam** (tuteo: "tú").

---

## 2. Reglas globales (aplican a TODOS los emails)

- **Una sola CTA por email** (un botón). Yo la renderizo desde el campo `cta` + el link; **no la
  metas dentro del body**.
- **Tono:** carta personal de Alfredo. Frases cortas. Cero jerga de marketing. Sin emojis salvo
  donde se indique.
- **Largo:** subject ≤ 6 palabras idealmente; preheader ≤ 90 caracteres; body **3–6 párrafos
  cortos**.
- **Features que SÍ existen** (puedes mencionarlas): proyectos, tareas, rutinas, ideas, notas,
  vista "Today", el asistente "Loop". **NO inventes** features (no existe "loops" como objeto, ni
  "sunday review", ni reportes, ni equipos/colaboración).
- **Saludo:** **no escribas "Hi"/"Hola"** — el body debe empezar con el token `{{greeting}}`
  seguido de coma. Yo lo reemplazo por el saludo localizado con el nombre ("Hi Alfredo," /
  "Hola Alfredo,") y por un saludo genérico si no hay nombre.
- **Tokens disponibles** (úsalos textualmente, con dobles llaves; cada email indica cuáles aplican):
  - `{{greeting}}` — saludo localizado + nombre (siempre disponible).
  - `{{spot_cap}}` — número de cupos de la beta (ej. 50).
  - `{{days_inactive}}` — días que el usuario lleva sin actividad.
  - `{{last_project_title}}` — título del último proyecto del usuario (puede no existir; escribe el
    texto de modo que funcione si lo quitamos).
- **No incluyas** unsubscribe/footer legal — eso lo maneja el sistema.

---

## 3. Los 10 emails

> Idea/identidad de cada email. La **copy final la decides tú**; esto es la intención.

### Grupo A — Welcome (se manda 1 vez, tras verificar el correo)

**A1 · `welcome_beta`** — entró a la beta.
- Meta: darle la bienvenida, explicar qué significa estar en la beta (acceso de por vida + se le
  pedirá feedback), e invitarlo a crear su primer proyecto.
- Incluir: que es 1 de `{{spot_cap}}`; el lifetime deal; "respóndeme con feedback".
- CTA: abrir la app y empezar. Tokens: `{{greeting}}`, `{{spot_cap}}`.

**A2 · `welcome_regular`** — usuario normal (no beta).
- Meta: bienvenida simple + el primer paso (crear un proyecto). Sin mencionar la beta.
- CTA: abrir la app. Tokens: `{{greeting}}`.

### Grupo B — Camino "fantasma" (se registró pero NUNCA creó nada). Días desde el registro.

**B1 · `inactivity_1` (día 3)** — empujón amable.
- Meta: asumir fricción, no desinterés. "Aún no creaste nada; el primer paso a veces no queda
  claro." Invitar a crear UN proyecto (solo el título basta).
- Tono: servicial, cero culpa. CTA: crear primer proyecto. Tokens: `{{greeting}}`.

**B2 · `inactivity_2` (día 7)** — mostrar el valor.
- Meta: recordar para qué sirve continuu (proyectos, rutinas, ideas/notas, vista Today) en 2–3
  bullets cortos. Bajar la barrera de entrada.
- Tono: útil, sin presión. CTA: probar la app. Tokens: `{{greeting}}`.

**B3 · `inactivity_3` (día 14)** — aviso honesto del cupo.
- Meta: con honestidad, decir que la beta tiene `{{spot_cap}}` lugares y hay lista de espera; que
  lleva 2 semanas sin usarla; que si no es para él ahora, liberará su lugar; que para quedarse
  basta con entrar y crear algo.
- Tono: honesto, respetuoso, no amenazante. CTA: conservar mi lugar. Tokens: `{{greeting}}`, `{{spot_cap}}`.

**B4 · `inactivity_4` (día 21)** — se liberó el cupo.
- Meta: avisar sin drama que se liberó su lugar; que **su cuenta sigue viva** (plan normal, datos
  intactos); puerta abierta a volver si responde.
- Tono: amable, sin rencor. CTA: entrar a continuu. Tokens: `{{greeting}}`.

### Grupo C — Camino "activo" (usó la app y luego se apagó). Días desde su ÚLTIMA actividad.

> A estos NO les digas "bienvenido". Ya conocen continuu. Es un "¿seguimos?".

**C1 · `reengage_1` (lapso temprano)** — "te extrañamos".
- Meta: notar que estuvo activo y desapareció hace `{{days_inactive}}` días; que retomar es fácil
  porque `{{last_project_title}}` sigue ahí. (Escríbelo para que funcione si quitamos el título:
  ej. "…tus proyectos siguen ahí, justo donde los dejaste.")
- Tono: cercano, ligero. CTA: retomar. Tokens: `{{greeting}}`, `{{days_inactive}}`, `{{last_project_title}}`.

**C2 · `reengage_2` (lapso prolongado)** — pregunta directa.
- Meta: preguntar sin rodeos si continuu le sigue siendo útil; si sí, que vuelva; si no, que
  responda y diga por qué (feedback).
- Tono: honesto, abierto. CTA: volver a continuu. Tokens: `{{greeting}}`.

**C3 · `reclaim_warn` (antes del reclaim)** — última llamada.
- Meta: reconocer que **fue parte activa** de la beta, por eso se le avisa primero; lleva mucho sin
  entrar y hay gente esperando; si no vuelve en unos días, liberará su lugar (y el lifetime deal);
  para conservarlo, basta con mover algo esta semana.
- Tono: respetuoso, agradecido, claro. CTA: conservar mi lugar. Tokens: `{{greeting}}`.

**C4 · `reclaim_final` (reclaim ejecutado)** — se liberó, con gratitud.
- Meta: avisar que liberó su lugar; **agradecer de verdad** el tiempo que sí estuvo (ayudó a
  mejorar continuu); cuenta y datos intactos en plan normal; puerta abierta a volver.
- Tono: cálido, agradecido. CTA: entrar a continuu. Tokens: `{{greeting}}`.

---

## 4. Formato de entrega (síguelo al pie de la letra)

Un solo archivo `.md`. Un bloque por email, en este orden y con estos campos exactos. Para cada
email, **dos sub-bloques: `en` y `es`**. El `body` usa párrafos separados por **una línea en
blanco**; empieza con `{{greeting}},`. No metas la CTA en el body.

```markdown
## welcome_beta

### en
subject: You're in 🎉
preheader: Your spot is reserved — here's what it means.
cta: Open continuu
body:
{{greeting}},

First paragraph...

Second paragraph...

### es
subject: Estás dentro 🎉
preheader: Tu lugar está reservado. Esto significa.
cta: Abrir continuu
body:
{{greeting}},

Primer párrafo...

Segundo párrafo...
```

Repite ese bloque para los 10 `email_id`, **en este orden exacto**:
`welcome_beta`, `welcome_regular`, `inactivity_1`, `inactivity_2`, `inactivity_3`,
`inactivity_4`, `reengage_1`, `reengage_2`, `reclaim_warn`, `reclaim_final`.

**Checklist antes de entregar:**
- [ ] Los 10 emails, cada uno con `en` y `es`.
- [ ] Cada email: `subject`, `preheader`, `cta`, `body`.
- [ ] El body empieza con `{{greeting}},` (sin "Hi"/"Hola" propios).
- [ ] Solo se usan los tokens listados por email, escritos con `{{ }}`.
- [ ] Sin features inventadas; sin footer/unsubscribe.
- [ ] Una sola CTA (en el campo `cta`, no en el body).

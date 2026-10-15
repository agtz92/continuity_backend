# Planes de Crew: propuesta detallada (v3)

> **Estado:** propuesta. Nada está implementado ni fijado en `core/billing/catalog.py`.
> Los planes **personales** (Free · Pro $8.99 · Studio $14.99) no se tocan. Fuente de
> verdad de cobros: [`../integracion-pagos-web-y-movil.md`](../integracion-pagos-web-y-movil.md).
> Arquitectura del producto: [`PLAN.md`](PLAN.md) v3, alineado con este documento.

## Qué cambia respecto a la v2

Seis decisiones del dueño, ya tomadas:

1. **El muro deja de ser la visibilidad de Pulso.** Micro ve Pulso completo. Lo que acota a
   Micro es el tamaño, no la información.
2. **Lo que compra Duo es la Revisión del equipo**, no "proyectos ilimitados".
3. **Lo que compra Table es dejar de perseguir gente:** Pulso propio para cada miembro y la
   Revisión contestada de forma asíncrona.
4. **Dos restricciones de diseño:** Pulso habla del trabajo, nunca de la persona. El miembro
   tiene agencia desde Micro.
5. **El cementerio compartido va en Micro.**
6. **Guild lleva "Contáctanos"** como llamada a la acción. *(Revierte la decisión 6
   original, que pedía venderlo solo sin hablar con nadie.)*

Y tres hallazgos de esta revisión que cambian el contenido:

- **Apple sí tiene $9.00 y $15.00.** El conflicto de precios de la v2 §8.2 no existe (§8.2).
- **La Revisión del equipo es construcción nueva.** No cuelga de la Sunday Review, que es
  material de marca sin implementar ni planear, y esa sección del sitio no se toca (§1.6).
- **La restricción 4.1 invalida una parte del diseño ya dibujado.** La sección "Por miembro"
  de Pulso, con contadores de vencidas por persona, es exactamente el tablero de vigilancia
  que la decisión prohíbe (§1.5).

---

## 0. Cómo leer este documento

Marcas cuando no es obvio:

- **Decidido**: acordado con el dueño.
- **Propuesta**: recomendación mía, sin validar.
- **Abierto**: sin recomendación firme.

Los cuatro planes (§3 a §6) siguen la misma plantilla para poder compararlos.

---

## 1. Conceptos compartidos por todos los planes

### 1.1 Qué es un asiento *(propuesta)*

**Un asiento es una persona con membresía activa en ese crew.**

| Caso | ¿Ocupa asiento? | Por qué |
|---|---|---|
| El dueño | **Sí** | Duo es para dos personas, y el fundador es una. |
| Un lead | Sí | Lead y member cuestan lo mismo. El rol dice qué ves, no cuánto pagas. |
| Un member | Sí | |
| Una invitación pendiente | **Sí, hasta que caduca** | Si no reserva, un crew en Table puede invitar a 15 y alguien tiene que decidir a quién rechazar cuando acepten. |
| Una invitación caducada (7 días) | No | Libera el asiento sola. |
| Alguien removido | No, desde que sale | El asiento se libera después de la entrega de su trabajo (§1.4). |
| La misma persona en tres crews | Uno en cada uno | Cada crew es un producto aparte. |
| Loop o el conector de Claude | No | No son personas y no tienen membresía. |

> **Abierto:** invitados de solo lectura. No existen en v1. Si llegan, lo natural es que no
> ocupen asiento, pero eso abre la puerta a meter a medio equipo como "invitado".

### 1.2 El plan es del crew, no de la persona *(decidido)*

- Cada crew tiene una suscripción y un plan.
- El plan personal de los miembros no afecta lo que pueden hacer dentro del crew. Un
  miembro en Free personal trabaja con todo lo que pagó el dueño.
- El crew nunca concede plan personal. Estar en un crew Table no te da Pro.
- Un dueño puede tener cualquier número de crews de pago, cada uno con su plan.
- **Un crew Micro por dueño, no dos.** Es el freno contra cultivar crews gratis. Una
  persona sí puede ser *miembro* de cuantos crews Micro ajenos quiera.

### 1.3 Lo que ningún plan de crew vende *(decidido)*

**IA.** Loop viene con el plan personal. Quien quiera preguntarle a Loop por el trabajo del
equipo necesita su propio Studio. Consecuencia económica que sostiene toda la escalera: el
costo marginal de un miembro es almacenamiento, no llamadas a un modelo.

Esto incluye la **autopsia del cementerio**. Hoy la reflexión cruzada sobre proyectos muertos
está gateada a Pro o superior (`_AUTOPSY_PLANS` en `core/services/autopsy.py`) porque cuesta
dinero producirla. **El cementerio compartido de §3 es el registro, no la autopsia.** La lista
de lo que el equipo mató, con sus razones, no cuesta nada y va en Micro. La lectura de IA
sobre ese cementerio sigue viniendo del plan personal de cada quien.

### 1.4 Qué pasa al tocar un límite *(propuesta)*

Un solo patrón, copiado de cómo ya funcionan las cuotas personales en `core/quotas.py`:

- **Nunca se borra nada.**
- **Pasarse de un límite bloquea crear, no usar.** Lo existente se sigue viendo, completando y
  editando. Es la regla de `_BLOCKING_KINDS`: primero ajustas, luego vuelves a crear.
- **Los asientos cuentan como límite bloqueante.**
- **El aviso ofrece las dos salidas.** Subir de plan o ajustar. Nunca solo la de pagar.

**Cuando alguien sale:** se pregunta a quién pasar sus tareas y proyectos de ese crew,
con el dueño por defecto, y se guarda quién los tenía antes. *(decidido)*

### 1.5 Dos restricciones de diseño *(decididas)*

**Pulso habla del trabajo, nunca de la persona.** "Este proyecto lleva 14 días quieto", no
"Ana no ha tocado nada". Sin esto el producto se vuelve un tablero de vigilancia, que es lo
contrario de la marca.

> **Consecuencia sobre el diseño ya dibujado.** La pantalla de Pulso del canvas tiene una
> sección "Por miembro" con columnas de abiertas, **vencidas** y cerradas por persona. Eso es
> un marcador de desempeño y hay que quitarlo o reescribirlo. Lo que sí puede quedarse:
> - El **avatar en cada fila**, porque para preguntar hay que saber a quién.
> - La **carga**, si se dice como carga y no como falta: "Ana tiene 11 cosas abiertas" describe
>   reparto de trabajo. "Ana tiene 2 vencidas" la califica.
>
> Regla práctica para quien implemente: si la frase se puede leer en voz alta en una junta sin
> que alguien se sienta señalado, pasa.

**El miembro tiene agencia desde Micro.** Puede proponer trabajo, declarar algo atorado con su
razón, y decidir el estado de lo suyo. Si el asiento 2 siente que la app es el látigo del
jefe, no entra, y un producto de dos asientos donde uno no entra se cancela solo.

### 1.6 Qué es la Revisión del equipo *(decidido que se construye; el alcance es propuesta)*

Toda la escalera se apoya en esto, así que conviene ser exacto.

**Es una pieza nueva.** No extiende nada existente. En concreto, **no cuelga de la "Sunday
Review"**, que es material de marca sin implementar ni planear: esa sección del sitio se queda
como está y no entra en este alcance. Aquí no se modifica nada hecho, se construye.

**Qué es.** Una vez por semana, a la hora que el crew elija, se abre una Revisión. Lista
los proyectos del crew que piden decisión y cada uno sale con una: **sigue, se pausa o se
mata**. Termina con un registro de qué se decidió y por quién.

**Qué no es.** No es un correo con viñetas. El correo, el Telegram o el push son la invitación
a abrirla, nunca el contenido. Un digest semanal no sostiene a Duo.

- **En Duo** la conduce el lead y los dos ven el resultado.
- **En Table** cada miembro contesta su parte cuando quiera, y el lead abre una Revisión **ya
  contestada**. Ese es el producto: el lead deja de perseguir.

**Por qué esto y no más visibilidad.** Pulso enseña el problema. La Revisión es donde se toma
la decisión. Un equipo puede mirar el mismo tablero durante seis semanas sin cerrar nada; el
ritual es lo que convierte el dato en un cierre, que es la tesis entera del producto.

**Alcance mínimo para que merezca el nombre** *(esto responde la pregunta abierta 4)*:

Una pantalla que se abre por invitación, lista los proyectos del crew que piden decisión,
y por cada uno ofrece sigue / pausa / mata **reusando los campos de cierre que ya existen en
`Project`** (`paused_context`, `paused_next_action`, `killed_reason`, `killed_learnings`). La
Revisión no reimplementa el cierre: lo invoca. Termina con un resumen que entra al registro
del crew y al cementerio compartido.

Eso es construible y es un ritual. **Es también el trabajo más grande de toda la propuesta y
el único sin precedente en el código.** Si el presupuesto no alcanza para eso, hay que
replantear qué vende Duo antes de comprometer la escalera, no después.

Detalle técnico (modelos `Review` y `ReviewEntry`, cadencia, autorización): [`PLAN.md`](PLAN.md) §4.6.

---

## 2. La escalera en una tabla

| | **Micro** | **Duo** | **Table** | **Guild** |
|---|---|---|---|---|
| Para quién | Dos personas probando si esto les sirve | Fundador + socio, o fundador + asistente | Un equipo de 3 a 10 | Más de 10 |
| Asientos | 2 | 2 | Hasta 10 | 11 o más |
| Mensual | $0 | $9 | $15 | $15 + $3 por asiento arriba de 10 |
| Anual (10 meses) | $0 | $90 | $150 | $150 + $30 por asiento arriba de 10 |
| Proyectos compartidos | 3 | Sin tope | Sin tope | Sin tope |
| Tareas abiertas | 50 | Sin tope | Sin tope | Sin tope |
| Repartir, proponer, declarar atorado | Sí | Sí | Sí | Sí |
| Estados forzados y cementerio compartido | Sí | Sí | Sí | Sí |
| Entrega de trabajo al salir | Sí | Sí | Sí | Sí |
| **Pulso** | **Completo**, sobre 3 proyectos | Completo | Completo | Completo |
| **Revisión del equipo** | No | **Sí** | **Sí, ya contestada** | Igual que Table |
| **Pulso propio para cada miembro** | No | No | **Sí** | Sí |
| Dónde se compra | Se crea en web y app | Web y app | Web y app | Solo web |

---

## 3. Micro

### Para quién

Dos personas que ya trabajan juntas y quieren ver si Continuity les sirve, sin sacar la
tarjeta.

> **El nombre es «Micro».** *(nombre decidido)* Nombra el tamaño, que es exactamente lo que
> este plan acota: tres proyectos, cincuenta tareas. No nombra la cantidad de gente, y esa
> es la virtud: Micro y Duo tienen **los mismos dos asientos**, porque el muro es la
> Revisión, no la gente. Un nombre que contara personas contradiría la decisión 1.
>
> El literal del enum y el nombre comercial coinciden (`micro`, `duo`, `table`, `guild`).

### El trabajo que hace

**Micro no está para convertir. Está para que lo recomienden.** *(decidido)* Es la versión
completa del producto a escala chica: tres proyectos, pero con todo lo que Continuity sabe
hacer sobre esos tres.

### Incluye

- 2 asientos.
- 3 proyectos compartidos y 50 tareas abiertas. Los mismos números del plan personal Free.
- **Pulso completo.** Qué se enfrió, quién lo tiene, desde cuándo, y qué está atorado con su
  razón. Sin mutilar.
- Asignar, proponer, aceptar, rechazar y **declarar algo atorado con una razón propia**.
- **Estados forzados y cementerio compartido.** El equipo puede pausar y matar proyectos
  juntos. Matar uno pide una razón de una línea que queda en el registro.
- Tablero, tareas, calendario y registro del equipo.
- Entrega de trabajo cuando alguien sale.

### Por qué Pulso completo y no una versión recortada *(decisión 1)*

Retener un hecho sobre el trabajo del propio usuario, para cobrarle por verlo, contradice el
pilar compasivo de la guía de voz. El precedente de Loop en el plan personal Free no aplica:
ahí se retiene **una opinión del asistente**, que cuesta producir. Aquí se retendría **un dato
que el usuario generó**.

### Por qué el cementerio compartido va aquí *(decisión 5)*

Matar es una forma de terminar. Un equipo que puede matar cosas junto es la tesis completa
del producto. No cuesta nada servirlo, y es lo único de toda la tabla que ningún competidor
tiene.

### Al llegar a los límites

| Límite | Qué pasa |
|---|---|
| 4º proyecto | No se crea. Dos salidas: pasar a Duo, o cerrar uno (terminarlo, pausarlo o matarlo). |
| 51ª tarea abierta | No se crea. Completar libera espacio. |
| 3ª persona | No se puede invitar. Micro y Duo son para dos; Table llega a diez. |
| 2º crew Micro del mismo dueño | No se crea. Los de pago no tienen este límite. |

### Riesgos

- **Que Micro sea suficiente para siempre.** Dos personas con pocos proyectos no van a pagar
  nunca. Es el costo aceptado de la decisión: se prefiere que lo recomienden.
- **Que el cierre de un proyecto se sienta como un truco para liberar cupo.** El aviso del
  cuarto proyecto tiene que ofrecer cerrar como una opción legítima, no como el peaje.

---

## 4. Duo

### Para quién

Dos personas que trabajan juntas de forma estable: fundador y socio, o fundador y asistente.
El caso que dio origen al producto de equipo.

### Lo que compra *(decisión 2)*

**La Revisión del equipo.** No "proyectos ilimitados": ese argumento contradice el manifiesto,
porque el producto existe justamente porque la gente empieza demasiado. El tope desaparece,
pero eso es una línea más, no el titular.

La Revisión es algo que se hace, no un número que se desbloquea. Es el momento en que el
equipo cierra loops en vez de solo mirarlos.

### Incluye

Todo lo de Micro, más:

- **La Revisión del equipo** (§1.6): el ritual semanal de cinco preguntas, con la decisión de
  estado al final, y su registro.
- Proyectos y tareas del crew sin tope.

### Por qué los mismos dos asientos que Micro

No se paga por meter a alguien. Se paga por el ritual que cierra los loops. Si Duo diera un
asiento más, el mensaje sería "paga por gente", y el valor se desplazaría a donde Continuity
no gana.

### Al llegar a los límites

| Situación | Qué pasa |
|---|---|
| Invitar a la 3ª persona | No se puede. Table llega a diez. |

### Bajar de Duo a Micro

- Si hay más de 3 proyectos o más de 50 tareas abiertas: se bloquea crear hasta ajustar. Nada
  se borra.
- La Revisión se apaga al renovar. El historial de las revisiones pasadas se queda.

### Riesgos

- **Duo queda muy cerca de Table.** $9 contra $15 son seis dólares por cinco veces los
  asientos. Ver §11.5: es un hallazgo nuevo de esta versión.
- **Si la Revisión llega recortada, Duo se queda sin argumento.** Es la dependencia más fuerte
  de toda la escalera (§1.6).

---

## 5. Table

### Para quién

Un equipo de 3 a 10: una agencia chica, un estudio, un equipo de producto. "Table" es como un
builder llama a su equipo, no como lo llama una empresa de software. *(nombre decidido)*

### Lo que compra *(decisión 3)*

**Table no te da más gente. Te quita el trabajo de perseguirla.**

Con tres a diez personas, el trabajo del lead se convierte en andar preguntando. Eso es lo que
Table elimina, con dos mecánicas:

- **Cada miembro recibe su propio Pulso**, antes de que el lead pregunte. El que deja algo
  quieto se entera solo.
- **La Revisión se contesta de forma asíncrona.** Cada quien decide el estado de lo suyo, y el
  lead abre una revisión ya contestada.

Es el cierre forzado a escala de equipo, **con la decisión en manos de quien hace el trabajo**.
Eso último no es un detalle de reparto: es lo que evita que la mecánica se sienta como
supervisión (§1.5).

### Incluye

Todo lo de Duo, más:

- Hasta 10 asientos a precio plano. Invitar a la cuarta persona no abre una conversación de
  presupuesto.
- Pulso propio para cada miembro.
- La Revisión contestada de forma asíncrona.

### Se puede comprar Table con dos personas

Sí. Alguien en Duo que quiera que su socio reciba su propio Pulso sube a Table sin tener más
gente. Es coherente con que el muro sea de función y no de asientos.

### Al llegar a los límites

| Situación | Qué pasa |
|---|---|
| Invitar a la 11ª persona | No se puede. Guild crece de a una persona. |
| 10 miembros + 1 invitación pendiente | La invitación no sale: las pendientes reservan asiento (§1.1). |

### Bajar de Table a Duo

- **Si hay más de 2 miembros, no se puede bajar** hasta que el dueño elija quién sale, con la
  entrega de su trabajo. El sistema nunca decide a quién sacar.
- El Pulso propio de cada miembro se apaga al renovar.

### Riesgos

- **A 10 personas, Table sale en $1.50 por persona.** Muy barato frente al mercado. Postura
  tomada en §11.3.
- **El Pulso propio puede leerse como recordatorio de culpa** si el tono no es el correcto. Es
  el mismo contenido que ve el lead, dirigido a quien puede actuar sobre él, y ese es
  precisamente el argumento: se entera primero quien puede arreglarlo.

---

## 6. Guild

### Para quién

Más de diez personas: varios equipos bajo un mismo dueño, o una empresa chica. El nombre
escala sin sonar a corporativo. *(nombre decidido)*

### Lo que compra

El mismo producto que Table, a una escala donde el precio plano deja de tener sentido.
**Guild no añade funciones: añade capacidad.** Decirlo así es más honesto que inventar
diferencias.

### Incluye

Todo lo de Table, más:

- 11 asientos o más. **$15 cubre los primeros 10, y cada asiento adicional cuesta $3 al mes**
  ($30 al año).
- Cambios de asientos a mitad de ciclo: **subir aplica al momento con prorrateo; bajar aplica
  al renovar.**

| Personas | Mensual | Anual |
|---|---|---|
| 11 | $18 | $180 |
| 20 | $45 | $450 |
| 50 | $135 | $1,350 |

### Se contrata hablando *(decidido)*

La llamada a la acción es **"Contáctanos"**. A más de diez personas la venta es asistida de
todas formas, y hay dos cosas que hoy no se pueden autoservir: la factura con datos fiscales y
el cobro por número de asientos.

**Efecto secundario que conviene aprovechar:** con una venta asistida, **la duda sobre si
RevenueCat acepta cantidad variable deja de bloquear el lanzamiento**. Guild puede salir
cobrado a mano mientras se automatiza.

### Por qué solo en web

Apple y Google no manejan cantidades en una suscripción. Un precio que depende de cuántas
personas hay no se vende dentro de la app sin convertirlo en bandas fijas.

> **Verificar antes de codear:** que RevenueCat Web Billing acepte suscripciones con cantidad
> variable. Si no, Guild tendría que venderse en bandas fijas también en web.

### Lo que un comprador de más de 10 va a pedir, y no existe

| Lo que van a pedir | Estado |
|---|---|
| **Factura con datos fiscales** (en México, CFDI) | No existe. Se cobra en USD vía RevenueCat. **A confirmar** qué emite el proveedor. |
| Pago por transferencia u orden de compra | No existe. Todo es tarjeta. |
| Inicio de sesión con la cuenta de la empresa (SSO) | No existe. |
| Exportar el registro de actividad del equipo | No existe como exportación. |
| Varios dueños o administradores de facturación | No existe. Hay un solo dueño. |

### Riesgos

- **Salir a vender a empresas sin factura fiscal** cierra la puerta justo con quien más paga.
- **El precio medio por persona sube con el tamaño**, al revés de lo que hace el mercado.
  Argumento y mitigación en §11.2.

---

## 7. Moverse entre planes

| Movimiento | Cuándo aplica | Qué pasa |
|---|---|---|
| **Subir** | Al momento | Se cobra la diferencia prorrateada. Lo nuevo se enciende en el acto. |
| **Bajar** | Al renovar | Si el crew excede el plan destino, no se permite hasta ajustar. El sistema nunca elige qué quitar. |
| **Cancelar** | Al terminar el periodo pagado | Pasa a Micro. Nada se borra. Si excede los límites de Micro, se bloquea crear hasta ajustar. Los miembros siguen viendo y completando lo que existe. |
| **Pago fallido** | Periodo de gracia del proveedor | El acceso sigue mientras reintentan (el sistema ya trata la gracia como activa en `entitlements.py`). Al vencer, se comporta como cancelar. |
| **El dueño borra su cuenta** | Nunca con un crew activo | Bloqueado. Primero transfiere la propiedad o cancela y borra el crew. *(decidido)* |

---

## 8. Precios

### 8.1 Los números

| | Mensual | Anual | Anual equivale a |
|---|---|---|---|
| Duo | $9 | $90 | 10 meses |
| Table | $15 | $150 | 10 meses |
| Guild | $15 + $3 por asiento extra | $150 + $30 por asiento extra | 10 meses |

**Anual = diez meses**, la misma regla que los planes personales.

### 8.2 Apple sí tiene estos precios

La v2 advertía que la regla de paridad podía chocar con el catálogo de Apple, porque el
documento de pagos dice que "$9.00 exacto no siempre existe". **Ya no aplica.** Desde la
revisión del sistema de precios de 2023 hay 900 puntos de precio, se permiten terminaciones
en `.00`, y hay pasos de $0.50 entre $0.49 y $49.99. **$9.00 y $15.00 existen.**

Consecuencia: precios redondos, paridad intacta, y Duo y Table se venden en la app. No hace
falta caer en `.99`.

> **Confirmar al crear los productos:** que esos puntos estén disponibles en la tienda base en
> USD, y revisar la matriz de Google Play, que tiene la suya.

### 8.3 Lo que llega al banco (estimado)

Con las comisiones que el sistema ya modela en `catalog.py`: tiendas 15%; web 2.9% + $0.30 por
cargo, más 1% de RevenueCat. Estimaciones para un tablero, no contabilidad.

| | Web, mensual | App, mensual | Web, anual (÷12) | App, anual (÷12) |
|---|---|---|---|---|
| Duo ($9 / $90) | $8.35 | $7.65 | $7.18 | $6.38 |
| Table ($15 / $150) | $14.12 | $12.75 | $11.99 | $10.63 |
| Guild, 20 personas ($45) | $42.95 | no se vende | $36.01 | |
| Guild, 50 personas ($135) | $129.44 | no se vende | | |

El costo de servir un crew es almacenamiento, el cálculo de Pulso (una consulta), y las
invitaciones a la Revisión. **No hay costo de modelo**, porque el crew no vende IA
(§1.3). El margen bruto es prácticamente el neto.

---

## 9. Copy propuesto

Estructura de `landing.pricing.tiers.*`. Escrito contra `continuuit-brand-voice.md`: sin
guiones largos, sin jerga de la lista negra, y sin frases que cualquier competidor pudiera
haber escrito.

### 9.1 Encabezado de la sección

**ES**
> **Para tu equipo**
> Tu cuenta sigue siendo tuya. Un Crew es otra cosa: el lugar donde reparten trabajo y
> donde deciden juntos qué sigue vivo. Se paga aparte. No cambia tu plan.

**EN**
> **For your team**
> Your account stays yours. A Crew is a different thing: where you hand out work and
> decide together what is still alive. It bills separately. It does not change your plan.

### 9.2 Los planes

```jsonc
// es.json → landing.crewPricing.tiers
{
  "free": {
    "name": "Micro",
    "price": "Gratis",
    "priceCadence": "para siempre",
    "seats": "2 personas",
    "perks": [
      "Pulso completo: qué se enfrió, quién lo tiene y desde cuándo",
      "Maten proyectos juntos, con la razón escrita",
      "Reparte trabajo, recibe propuestas, declara lo que está atorado",
      "3 proyectos compartidos y 50 tareas abiertas",
      "Cuando alguien sale, su trabajo se queda"
    ],
    "cta": "Crear un Crew"
  },
  "duo": {
    "name": "Duo",
    "price": "$9",
    "priceCadence": "USD al mes",
    "priceAnnual": "$90",
    "priceCadenceAnnual": "USD al año",
    "annualSaving": "Dos meses libres",
    "seats": "2 personas",
    "inheritsFrom": "Todo lo de Micro, más:",
    "perks": [
      "La Revisión del equipo: cinco preguntas, una vez por semana, y cada proyecto sale con una decisión",
      "Lo que soltaron queda escrito, con quién lo decidió",
      "Sin tope de proyectos ni de tareas"
    ],
    "cta": "Empezar con Duo"
  },
  "table": {
    "name": "Table",
    "price": "$15",
    "priceCadence": "USD al mes",
    "priceAnnual": "$150",
    "priceCadenceAnnual": "USD al año",
    "annualSaving": "Dos meses libres",
    "seats": "Hasta 10 personas",
    "inheritsFrom": "Todo lo de Duo, más:",
    "perks": [
      "Cada quien recibe su propio Pulso, antes de que tengas que preguntar",
      "La Revisión llega contestada: cada quien decidió el estado de lo suyo",
      "Hasta 10 personas por el mismo precio"
    ],
    "cta": "Empezar con Table"
  },
  "guild": {
    "name": "Guild",
    "price": "$15 + $3",
    "priceCadence": "USD al mes por cada persona arriba de 10",
    "seats": "11 personas o más",
    "inheritsFrom": "Todo lo de Table, más:",
    "perks": [
      "Crece de a una persona, sin saltar de plan",
      "Se contrata desde la web"
    ],
    "cta": "Contáctanos"
  }
}
```

```jsonc
// en.json → landing.crewPricing.tiers
{
  "free": {
    "name": "Micro",
    "price": "Free",
    "priceCadence": "forever",
    "seats": "2 people",
    "perks": [
      "Full Pulse: what went cold, who has it, and since when",
      "Kill projects together, with the reason written down",
      "Hand out work, receive proposals, flag what is stuck",
      "3 shared projects and 50 open tasks",
      "When someone leaves, their work stays"
    ],
    "cta": "Create a Crew"
  },
  "duo": {
    "name": "Duo",
    "price": "$9",
    "priceCadence": "USD per month",
    "priceAnnual": "$90",
    "priceCadenceAnnual": "USD per year",
    "annualSaving": "Two months free",
    "seats": "2 people",
    "inheritsFrom": "Everything in Micro, plus:",
    "perks": [
      "The team review: five questions, once a week, and every project leaves with a decision",
      "What you let go stays written down, with who decided it",
      "No cap on projects or tasks"
    ],
    "cta": "Start with Duo"
  },
  "table": {
    "name": "Table",
    "price": "$15",
    "priceCadence": "USD per month",
    "priceAnnual": "$150",
    "priceCadenceAnnual": "USD per year",
    "annualSaving": "Two months free",
    "seats": "Up to 10 people",
    "inheritsFrom": "Everything in Duo, plus:",
    "perks": [
      "Everyone gets their own Pulse, before you have to ask",
      "The review arrives answered: each person decided the state of their own work",
      "Up to 10 people for the same price"
    ],
    "cta": "Start with Table"
  },
  "guild": {
    "name": "Guild",
    "price": "$15 + $3",
    "priceCadence": "USD per month for each person above 10",
    "seats": "11 people or more",
    "inheritsFrom": "Everything in Table, plus:",
    "perks": [
      "Grows one person at a time, with no plan to jump to",
      "Bought on the web"
    ],
    "cta": "Contact us"
  }
}
```

### 9.3 La nota sobre Loop, debajo de la tabla

**ES**
> **Loop no se vende aquí.**
> El asistente viene con tu cuenta, no con tu Crew. Si quieres preguntarle por el trabajo
> de tu equipo, eso lo trae tu Studio personal. Nadie le compra un asistente a nadie, y el
> precio del Crew no esconde un costo que sube solo.

**EN**
> **Loop is not sold here.**
> The assistant comes with your account, not with your Crew. If you want to ask it about
> your team's work, your own Studio brings that. Nobody buys an assistant for somebody else,
> and the Crew price hides no cost that creeps up on its own.

### 9.4 Los avisos al tocar un límite

Tono de sistema: corto, específico, sin culpa, siempre con dos salidas.

| Momento | ES | EN |
|---|---|---|
| 4º proyecto en Micro | Este Crew tiene 3 proyectos, el tope de Micro. Cierra uno o pasa a Duo. | This Crew has 3 projects, the Micro limit. Close one or move to Duo. |
| 3ª persona en Micro o Duo | Este Crew es para dos. Table llega a diez. | This Crew is for two. Table goes up to ten. |
| 11ª persona en Table | Table llega a diez. Guild crece de a una persona. | Table stops at ten. Guild grows one person at a time. |
| Bajar con gente de más | Para pasar a Duo, este Crew tiene que quedar en dos personas. Elige quién sale y a quién pasa su trabajo. | To move to Duo, this Crew needs to be down to two people. Choose who leaves and who takes their work. |

---

## 10. Lo que dejé fuera a propósito

| Fuera | Por qué |
|---|---|
| IA en cualquier plan de crew | §1.3. De ahí depende que el precio pueda ser plano. |
| Roles además de lead y member | Añadir un rol es una fila en un enum. Quitarlo cuando ya hay gente asignada, no. |
| Analítica del equipo | Pulso y la Revisión son la analítica que importa. |
| Ideas, rutinas y notas compartidas | Son personales por naturaleza. **El cementerio ya no está en esta lista** (decisión 5). |
| Invitados de solo lectura | No hay caso real todavía (§1.1). |
| Prueba gratis de 14 días | Micro cumple esa función sin pedir tarjeta, y ahora con el producto completo. |
| Banda intermedia de 3 a 5 personas | Rompe la simplicidad de tres nombres. |

> **Consecuencia sobre el diseño:** el cementerio compartido añade un destino a la navegación
> del crew, que hoy tiene seis. O entra como séptimo, o vive como filtro dentro de
> Proyectos. El canvas publicado todavía no lo refleja.

---

## 11. Las preguntas abiertas de la v2, resueltas

### 11.1 Puntos de precio de Apple: resuelto, van los redondos

Ver §8.2. $9.00 y $15.00 existen desde la revisión de precios de 2023. No hay que elegir entre
redondear y vender en la app.

### 11.2 El asiento 11 de Guild: se queda en $3

**La comparación de la pregunta no es la correcta.** Dentro de Table, la tarifa marginal de un
asiento es **cero**, no $1.50: del tercero al décimo no cuestan nada. $1.50 es el promedio en
el tope. Comparar $3 contra $1.50 es comparar un marginal contra un promedio.

La pregunta útil es cuánto vale el asiento 11 en absoluto, y ahí $3 es defendible:

- Sigue siendo **tres veces más barato que cualquier competidor por asiento** (el mercado
  ronda $8 a $10 por persona).
- El escalón del asiento 11 es de $15 a $18. Un 20%, no un muro.
- Bajarlo a $2 le ahorra **$10 al mes a un equipo de 20**. Ese no es el número que decide una
  compra a ese tamaño, y cuesta un tercio del ingreso marginal del segmento que más soporte
  consume.
- Table tiene precio plano para quitarle la aritmética de asientos a un equipo chico. A partir
  de 11 personas hay un proceso de compras, y contar asientos ahí es normal.

**Lo honesto que hay que aceptar:** el precio medio por persona sube con el tamaño ($1.50 a
diez, $2.25 a veinte, $2.70 a cincuenta), al revés de lo que hace el mercado. Un comprador de
50 personas lo va a notar.

**Mitigación, para cuando haga falta:** añadir bandas de volumen **arriba** (por ejemplo $2.50
desde el asiento 26) en vez de bajar la tarifa base. Regalar después es fácil; quitar, no.

### 11.3 Table a $15 contra Studio a $14.99: se toma la línea, y se planea el aumento

**Postura: usar la línea. Table a $15 está bien para lanzar y va a estar mal en el año dos.**

Por qué está bien para lanzar:

- La frase es verdadera y fuerte: **diez personas por lo que cuesta un plan personal.**
- Refuerza la arquitectura. El crew coordina; el plan personal capacita. Un Table barato
  **empuja ventas de Studio**: cada miembro que quiera preguntarle a Loop por el trabajo del
  equipo compra su propio Studio. El ingreso de IA se queda donde está el costo de IA.
- **Equivocarse por abajo es recuperable en este código en concreto.** `catalog.py` guarda una
  **lista** de ids de producto por plan y periodo, justamente para que quien compró con un
  precio retirado siga renovando con él. Subir el precio más adelante respeta a los existentes
  por construcción, no por buena voluntad.
- Equivocarse por arriba no es recuperable: nunca te enteras de si el producto de equipo
  funciona, porque nadie lo prueba.

**La tensión que hay que aceptar, no esconder:** poner la mecánica firma de la marca por
debajo de un plan personal dice que la capa de equipo vale menos que la herramienta de una
persona. Es una incoherencia de posicionamiento elegida a sabiendas para el lanzamiento.

**Señal para revisar el precio** (decidirla ahora, no después): si la mediana de los
crews en Table tiene 6 personas o más, el valor entregado superó al precio y toca subirlo en
la siguiente ventana de cambios.

### 11.4 Alcance de la Revisión del equipo: respondido en §1.6

**No es un correo semanal.** Es una pantalla que se abre por invitación, lista los proyectos
que piden decisión y los cierra uno por uno con los campos que ya existen en `Project`. Es
construcción nueva, sin relación con la Sunday Review de la marca, y es la pieza más grande de
toda la propuesta. Si no cabe en el presupuesto, hay que replantear qué vende Duo.

### 11.5 Table se come a Duo: resuelto, y es el embudo que se quiere

En la v2 el salto era $9 a $24, casi el triple. En la v3 es **$9 a $15: seis dólares por cinco
veces los asientos**, más el Pulso propio de cada miembro.

**No es un problema, es el diseño.** *(decidido)* Duo es el ancla y Table es el destino: se
prefiere que la gente suba a $15 y sienta que su dinero rinde más, a que se quede en $9
sintiendo que compró lo mínimo.

Consecuencias para el copy y para el orden de la tabla:

- Table es el plan que se presenta como la opción natural, no como el escalón caro.
- Duo no se escribe como "la versión chica". Se escribe como el caso exacto de dos personas.
- La comparación entre los dos tiene que dejar ver el salto de valor de un vistazo, porque es
  justo lo que se quiere que pase.

**Qué vigilar:** la proporción de compras Duo contra Table los primeros meses. Si Duo no vende
nada, la escalera son tres nombres y no cuatro.

---

## 12. Antes de que esto llegue al código

- Importes en `settings` como `PRICE_CREW_{DUO,TABLE}_{MONTHLY,ANNUAL}_AMOUNT_CENTS` e
  ids de producto en `STORE_PRODUCT_CREW_*`, con el patrón de `core/billing/catalog.py`,
  **incluida la lista de ids** para honrar precios retirados (de eso depende §11.3).
- La suscripción del crew vive en **su propia fila** (`CrewSubscription`), y
  `apply_entitlement` enruta por `product_id`. Si escribe en `AccountProfile`, la capa de
  titularidad la rechaza como cobro duplicado contra el plan personal del dueño.
- **Verificar antes de codear Guild:** que RevenueCat Web Billing acepte cantidad variable.
- **Confirmar al crear los productos:** los puntos de precio $9.00 y $15.00 en la tienda base
  en USD, y la matriz de Google Play.
- **La Revisión del equipo necesita su propio plan técnico**, y es la pieza de la que depende
  Duo. No está en `PLAN.md`, y **la versión individual tampoco está implementada ni planeada**:
  hoy solo existe una rutina sembrada y la promesa del landing (§1.6). Es el trabajo más
  grande de toda la propuesta y el que hay que dimensionar antes de comprometer la escalera.
- La tabla de paridad del documento de pagos, §1, crece con estos planes el día que se fijen.

# Onboarding — cómo agregarle pasos y cómo reutilizarlo

Cómo agregar pasos a los onboardings que ya existen, y cómo reutilizar la
maquinaria cuando llegue un dashboard nuevo — Teams, en concreto.

Documento cross-repo: toca `frontend`, `continuity-mobile` y `backend`.

> **Dónde vive y por qué.** Está en `backend/docs/` porque es donde ya viven los
> otros documentos que mandan sobre los tres repos
> ([teams/PLAN.md](teams/PLAN.md),
> [integracion-pagos-web-y-movil.md](integracion-pagos-web-y-movil.md)), y porque
> la carpeta que contiene a los tres **no es un repo git**: un documento que se
> va a consultar dentro de seis meses tiene que estar versionado en alguno.
>
> **Las rutas de este documento salen de esa carpeta contenedora**, la que tiene
> `frontend/`, `continuity-mobile/` y `backend/` dentro. Desde aquí, `frontend/x`
> es `../../frontend/x`.

---

## 0. Hay dos onboardings, y no se parecen en nada

Confundirlos es el primer error. Uno pide datos, el otro enseña el producto.

| | **Flujo de alta** | **Tour del dashboard** |
|---|---|---|
| Qué es | 5 pasos en pantalla propia | 10 pasos encima del producto |
| Pide | **tema + paleta** · nombre · avatar · plan · personalizar Today | nada |
| Escribe | perfil, tema, paleta, layout | nada del usuario |
| Estado servidor | `OnboardingProgress.status` + `current_step` | `OnboardingProgress.tour_status` |
| Valores | `pending · in_progress · completed · skipped` | `pending · seen · skipped` |
| Arquitectura | **máquina de estados a mano** | **guiada por datos** |
| Agregar un paso cuesta | ~6 sitios en 3 repos | **1 línea + 2 claves** |

Esa última fila es todo lo que hay que recordar. El tour se hizo adecuable a
propósito; el flujo de alta es de antes y sigue cableado a mano.

### Dónde vive cada cosa

**Tour**
```
frontend/src/components/dashboard/tour/
  steps.ts          ← el guion. Lo único que se edita
  DashboardTour.tsx ← el motor
  TourCard.tsx      ← la ficha
continuity-mobile/src/components/onboarding/tour/
  steps.ts          ← el guion. Gemelo del de web
  DashboardTour.tsx ← el motor
  TourCard.tsx      ← la ficha
  Spotlight.tsx     ← el recorte (cuatro velos)
  anchors.ts        ← registro de sitios señalables + useTourScroller
  TourAnchor.tsx    ← el envoltorio medible
continuity-mobile/docs/onboarding-tour.md   ← la receta corta
```

**Flujo de alta** — los cinco pasos son: **1** modo de tema **y paleta** (las
cinco gamas: ocre · salvia · óxido · hielo · ciruela; el onboarding arranca en
`hielo`, no en el `ocre` por defecto del resto de la app) · **2** nombre · **3**
avatar · **4** plan · **5** personalizar Today.

El tema va primero desde el 2026-09-14 y **lleva la bienvenida en su
encabezado** ("Bienvenido, builder. Esto toma 90 segundos. Empecemos por cómo se
ve."): se elige cómo se ve antes de dar ningún dato, y la elección se
previsualiza en toda la app en vivo.

Los componentes y las claves i18n **no llevan número** —`StepTheme`,
`onboarding.theme.*`— precisamente para que reordenar no obligue a renombrar
nada. Si añades uno, mantén esa propiedad: nombra por lo que hace, no por dónde
está.

```
frontend/src/app/(app)/onboarding/OnboardingFlow.tsx  + steps/Step{Theme,Name,Avatar,Plan,Customize}
continuity-mobile/src/app/onboarding.tsx              + components/onboarding/Step{...}
backend/core/services/onboarding.py                   ← TOTAL_STEPS, set_step, complete
backend/core/schema_mutations.py                      ← setOnboardingStep, completeOnboarding, markTour
backend/core/models.py                                ← OnboardingProgress, OnboardingStatus, TourStatus
```

---

## 1. Agregar un paso al tour

Tres archivos como mucho, y dos de ellos son JSON de textos.

### Caso A — la sección ya está en la navegación (lo normal)

No hay que tocar ninguna pantalla. Toda entrada de la barra lateral de web
lleva `data-tour={item.view}`, y en móvil las filas del menú "Más" se envuelven
**en bloque**, así que cualquiera es señalable por su propio `key`.

**1. Una entrada en `steps.ts`, en los dos repos.**

Web (`frontend/src/components/dashboard/tour/steps.ts`):
```ts
{ key: "team", view: "team", anchor: "team" },
```

Móvil (`continuity-mobile/src/components/onboarding/tour/steps.ts`):
```ts
{ key: "team", route: "/more", anchor: "more.team" },
```

El `anchor` de móvil es `"more." + el key del item` en `more.tsx`. El de web es
el `DashboardView`.

**2. Dos claves por idioma**, en `frontend/messages/{en,es}.json` y
`continuity-mobile/src/messages/{en,es}.json`:
```json
"team": {
  "title": "Equipo: el trabajo de los demás",
  "body": "…"
}
```

El texto se resuelve **por convención** desde `onboarding.tour.<key>.title` y
`.body`. No hay mapa intermedio: si falta un texto, se ve en la primera pasada.

**3. No hay paso 3.** Los puntos de progreso, el numeral de la ficha y el botón
final salen de `TOUR_STEPS.length`.

### Caso B — apuntas a algo que no es navegación

Márcalo y ya:

```tsx
// web
<div data-tour="team-board">…</div>

// móvil
import { TourAnchor } from "@/components/onboarding/tour/TourAnchor";
<TourAnchor id="team.board">…</TourAnchor>
```

`TourAnchor` es una `View` transparente que no cambia el layout; solo existe
para poder medirse. Si el sitio puede quedar bajo el pliegue, el `ScrollView`
que lo contiene necesita una línea más y el tour lo trae a la vista solo:

```tsx
const scroller = useTourScroller();   // de "@/components/onboarding/tour/anchors"
<ScrollView {...scroller}>
```

### Caso C — paso sin ancla

Sin `anchor`, el velo cubre todo y la ficha va centrada. Es lo que hacen
`welcome` y `close`.

### Reglas de oro del guion

- **Los dos `steps.ts` llevan las mismas claves en el mismo orden.** Los textos
  son los mismos; si añades una sección aquí, añádela allá.
- **El orden del tramo de secciones es el orden visual de la lista** que las
  contiene. Contarlas en otro orden obliga al recorte a saltar arriba y abajo
  por la misma pantalla, y eso se lee como un error, no como un recorrido.
- **Si un ancla no existe en el DOM**, el paso cae a pantalla completa solo. No
  hace falta condicionarlo a mano (web lo hacía y por eso la mitad del tour
  viejo desaparecía en móvil-web sin avisar).

### Lo que NO se toca nunca al agregar un paso

`DashboardTour.tsx` · `TourCard.tsx` · `Spotlight.tsx` · `anchors.ts` ·
`TourAnchor.tsx`. Si te ves editando uno de estos para añadir contenido, algo se
diseñó mal — para y arréglalo ahí.

---

## 2. Agregar un paso al flujo de alta (esto sí cuesta)

Aquí no hay registro: es un `switch` de `step === N` duplicado en dos repos, con
el total cableado en tres. Para añadir un paso 6 hay que tocar **seis sitios**:

1. `backend/core/services/onboarding.py` → `TOTAL_STEPS = 5` (valida el rango de
   `set_step`; si no lo subes, el paso 6 devuelve `BAD_INPUT`).
2. `frontend/.../OnboardingFlow.tsx` → `TOTAL_STEPS` + una rama `{step === 6 && …}`.
3. `frontend/.../onboarding/steps/StepLoQueSea.tsx` → el componente.
4. `continuity-mobile/src/app/onboarding.tsx` → `TOTAL_STEPS` + su rama.
5. `continuity-mobile/src/components/onboarding/StepLoQueSea.tsx` → el componente.
6. `messages` de los dos repos → los textos, bajo una clave con el mismo nombre
   semántico que el componente.

**Reordenar es más barato que añadir**, y se hizo una vez (tema al 1): son las
dos ramas del `switch`, los `goToStep` que apuntan a ellas, el botón "Atrás" —que
en web vive dentro de cada paso, no en el contenedor— y la copia que se mude. El
backend no se entera. Móvil no tiene ese problema: su "Atrás" es global
(`{step > 1 && …}`).

Y hay dos trampas que no se ven:

- **`writeStoredStep` / `STEP_STORAGE_KEY`** (web) guarda el paso en
  `sessionStorage` para sobrevivir a un remount. Está acotado a `[1, TOTAL_STEPS]`:
  si subes el total solo en el backend, el resume te devuelve al paso 1.
- **`set_step` solo persiste hacia adelante** (`if step > progress.current_step`).
  Un paso nuevo insertado **en medio** no rebobina a nadie que ya iba más lejos —
  que es lo correcto, pero significa que los usuarios existentes no lo verán.
  Si el paso nuevo es obligatorio, necesita su propia condición, no el contador.

**Recomendación honesta:** si vas a añadir **más de un** paso al flujo de alta,
conviértelo antes a registro, igual que el tour. Son unas dos horas y se paga en
el segundo paso. La forma es la misma: un `STEPS: {key, Component}[]`, el total
derivado de `STEPS.length`, y el backend validando contra un número que le manda
el cliente o simplemente contra un techo generoso.

---

## 3. Reutilizar el tour en un dashboard nuevo — el caso Teams

El plan de Teams (`backend/docs/teams/PLAN.md` §7) dice que **ver el board del
equipo es una vista del dashboard**, no una sección de ajustes. Eso cambia mucho
lo que cuesta su onboarding.

### 3.1 Si el board de equipo es una vista más del dashboard actual

Entonces ya está casi hecho, y esto es el camino que recomiendo:

1. `frontend/src/lib/dashboardViews.ts` → añade `"team"` a `DashboardView`.
2. `frontend/src/components/layout/Sidebar.tsx` → una entrada en `GROUPS`.
   **El `data-tour` sale solo**: la barra lateral ya marca todas sus entradas.
3. Móvil → una entrada en el array del menú "Más" (`more.tsx`). **El ancla sale
   sola**: las filas se envuelven en bloque por su `key`.
4. Un `{ key: "team", … }` en los dos `steps.ts` + los textos.

Coste real: **dos líneas de guion y cuatro strings.** Eso era el objetivo del
rediseño del tour, y Teams es justo el caso que lo va a probar.

Una decisión de producto que sí tendrás que tomar: **el paso de Teams no le
sirve a quien no tiene equipo.** Un tour que enseña una sección vacía y de pago
es peor que no enseñarla. Dos salidas razonables:

- **Filtrar el guion**: `TOUR_STEPS.filter(s => s.key !== "team" || hasTeam)`.
  Barato, pero el motor pasa a recibir la lista por parámetro (ver 3.2).
- **Un tour propio de Teams**, que arranca al entrar por primera vez al board.
  Es lo que de verdad quieres si el board tiene su propio vocabulario (jefe,
  asistente, proponer vs asignar) — que lo tiene.

### 3.2 Si Teams merece su propio tour

Hoy el motor es **de un solo tour**. Lo genérico y lo acoplado:

| Pieza | ¿Reutilizable tal cual? |
|---|---|
| `Spotlight.tsx` (cuatro velos) | **Sí.** Recibe un rect y lo pinta. No sabe de pasos. |
| `TourCard.tsx` | **Sí.** Recibe número, textos y tres callbacks. |
| `anchors.ts` / `TourAnchor.tsx` | **Sí.** Registro por id, sin semántica. |
| `DashboardTour.tsx` | **No del todo.** Tres acoplamientos. |
| `steps.ts` | No: es una constante de módulo. |

Los tres acoplamientos de `DashboardTour`, y cómo se sueltan:

```tsx
// Hoy
import { TOUR_STEPS } from "./steps";
const tourStatus = data?.onboardingState?.tourStatus;
title={t(`onboarding.tour.${step.key}.title`)}

// Para dos o más tours
export function Tour({ steps, ns, state, onFinish, onSkip }: {
  steps: TourStep[];      // el guion, por parámetro
  ns: string;             // "onboarding.tour" | "onboarding.teamTour"
  state: "pending" | "seen" | "skipped" | undefined;
  onFinish: () => void;   // quién persiste, y dónde, lo decide el llamador
  onSkip: () => void;
}) { … }
```

Y el `DashboardTour` de hoy pasa a ser una línea:

```tsx
<Tour steps={TOUR_STEPS} ns="onboarding.tour" state={tourStatus}
      onFinish={() => markTour({ variables: { seen: true } })}
      onSkip={() => markTour({ variables: { seen: false } })} />
```

Es un refactor de media hora **y no lo hagas antes de necesitarlo**. Hacerlo
ahora, con un solo tour, sería generalizar sobre un caso — que es la forma más
fiable de generalizar mal. El momento correcto es cuando el segundo tour exista.

### 3.3 Si Teams es un dashboard aparte, con su propia navegación

Mismo refactor de 3.2, más una cosa: el motor de móvil navega con
`router.navigate(step.route)` y el de web con `onNavigate(view)`. Si tu
dashboard nuevo navega de otra forma, esa es la cuarta prop:

```tsx
onGoTo?: (step: TourStep) => void   // por defecto, lo de hoy
```

El recorte y la ficha no cambian: son los que ya funcionan en dos plataformas.

---

## 4. El estado en el servidor

Hoy hay **un solo interruptor** para un solo tour:

```python
# backend/core/models.py
class TourStatus(models.TextChoices):
    PENDING = "pending"; SEEN = "seen"; SKIPPED = "skipped"

class OnboardingProgress(models.Model):
    user_id      = models.UUIDField(primary_key=True)
    status       = ...   # el flujo de alta
    current_step = ...
    tour_status  = ...   # el tour del dashboard
```

Y una mutación: `markTour(seen: Boolean!)`.

**Para un segundo tour, no añadas una columna.** `team_tour_status` funciona una
vez y te obliga a volver aquí, a la migración y al schema en cada feature nueva
— exactamente la trampa de la que salimos al borrar la lista `TOUR_ANCHORS`.
Lo que escala es un mapa:

```python
# Un campo, N tours. `seen_tours = {"dashboard": "seen", "teams": "pending"}`
seen_tours = models.JSONField(default=dict, blank=True)
```

```graphql
markTour(tour: String! = "dashboard", seen: Boolean!): OnboardingState
```

Con `tour_status` conservado como lectura derivada de `seen_tours["dashboard"]`
durante una release, para no romper las versiones de la app que ya están en las
tiendas. **Eso último no es opcional:** una app móvil publicada no se actualiza
cuando tú despliegas.

Un tour nuevo son entonces: una clave en el JSON, una entrada en `steps.ts` por
repo y sus textos. Ninguna migración.

---

## 5. Reglas que ya nos costaron caro

No son estilo. Cada una viene de algo que se rompió.

1. **El texto se resuelve por convención**, nunca con un `switch` por sección.
   Un mapa `key → texto` es un sitio más que ampliar por feature.
2. **No inventes colores.** El velo es el token `scrim` (existe en los dos
   repos, y `npm run check-parity` en móvil falla si divergen). Las sombras son
   `lift("float")` / `shadow-hard-lg`. Ver `AGENTS.md`.
3. **La espina del `Spine` codifica estado de proyecto.** La ficha del tour
   dibuja su barra a mano justamente por eso: toma el lenguaje visual, no el
   contrato. Si tu componente nuevo no tiene un estado honesto que dar, no uses
   el primitivo.
4. **React Native: no mezcles `LayoutAnimation` con animaciones de Reanimated.**
   En la New Architecture corrompe el árbol de vistas nativo **en silencio** —
   pantalla en blanco, cero errores en el log de Metro. Nos costó dos días.
5. **NativeWind: un `className` que alterna entre `undefined` y string crashea.**
   Cadenas siempre concatenadas, o valores dinámicos por `style` inline.
6. **i18n es ICU de llave simple**: `{count}`, nunca `{{count}}`.
7. **El tour no escribe datos del usuario.** El handoff original quería que el
   paso 1 creara un proyecto de verdad. Free tiene cupo de 3: gastarlo en el
   tour convierte un "ver el tour otra vez" en un error de cuota.
8. **No prometas cifras que no existen.** El paso de analíticas admite el vacío
   y dice cuándo deja de estarlo. Enseñarle "14 empezados, 5 cerrados" a alguien
   que lleva dos minutos es enseñarle la app de otra persona.
9. **Los textos se escriben contra el modelo, no contra el diseño.** El handoff
   enseñaba estados `Completed` que no existen; el cierre con éxito se llama
   `launched`. Antes de escribir el copy de una sección, lee su enum.

---

## 6. Checklist: "quiero onboarding de Teams"

Cuando llegue el momento, en este orden:

- [ ] ¿El board de equipo es una vista del dashboard o una app aparte? Decide
      esto **antes**; cambia todo lo demás. (El plan v2 dice: vista.)
- [ ] Si es vista: añade el `DashboardView` + entrada de barra lateral + fila en
      el menú "Más" de móvil. Verifica que el `data-tour` / el ancla salen solos.
- [ ] ¿El paso sirve a quien no tiene equipo? Si no, decide entre filtrar el
      guion o un tour propio (§3.1).
- [ ] Si es tour propio: el refactor de `Tour({steps, ns, state, …})` (§3.2) y
      el `seen_tours` JSON del backend (§4), con `tour_status` derivado durante
      una release.
- [ ] Escribe los textos leyendo el enum de roles (`lead` / `member`), no el
      mockup. Y en los dos idiomas de una vez: el tour viejo se quedó años en
      spanglish porque se tradujo "después".
- [ ] `npm run check-parity` en móvil y `npx tsc --noEmit` en los dos repos.
- [ ] Pruébalo en device. El recorte depende de medición en vivo: la TabBar
      cambia de alto con el safe-area y eso no se ve en un simulador de escritorio.

---

## 7. Diagnóstico rápido

**El velo cubre la pantalla entera y la ficha sale centrada** — no encontró el
ancla. Tres causas, en orden de frecuencia:

1. El id de `steps.ts` y el del `data-tour` / `TourAnchor` no son la misma
   cadena. En móvil, las filas del menú son `"more." + key`.
2. La pantalla no estaba montada. El motor reintenta (móvil ~14 veces, web ~20
   frames), pero si `route` / `view` apunta a otro sitio del que muestra el
   ancla, no hay reintento que valga.
3. Android fundió la vista. `TourAnchor` ya pone `collapsable={false}`; si
   envolviste a mano, te falta eso.

**El tour se dispara solo cuando no debería** — `tour_status` volvió a
`pending`. Ojo: `completeOnboarding(mode:"skipped")` marca el tour como
`skipped` a propósito, para no emboscar a quien se saltó la intro.

**Quiero verlo otra vez** — web: `/dashboard?tour=1`. Móvil: Más → Apariencia →
"Ver el tour otra vez".

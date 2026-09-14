# Auditoría de Código — Modularidad y Legibilidad (re-auditoría 3)

> **Pagos, precios y suscripciones — fuente de verdad:** [Integración de pagos web y móvil](docs/integracion-pagos-web-y-movil.md).
> Lo que este documento diga sobre Stripe, cobros, planes de pago o tiendas es
> contexto; ante cualquier diferencia, manda ese.

**Proyecto:** Continuity — `frontend/` (Next.js + Apollo), `backend/` (Django + Strawberry), `continuity-mobile/` (Expo / React Native)
**Fecha:** 2026-09-14 · **Pasada:** cuarta (re-medición completa contra disco)
**Alcance:** todo el código fuente salvo dependencias, build, generado, migraciones y tests.
**Naturaleza:** solo lectura. Este reporte no modifica código.

> ⚠️ **Corrección estructural respecto de pasadas anteriores:** esto **no es un monorepo**.
> Son **tres repositorios git independientes** (`continuity_frontend`, `continuity_backend`,
> `continuity-mobile`) que conviven en una misma carpeta local. Es el dato que explica el
> hallazgo dominante de esta pasada (§C-1) y el que limita las recomendaciones posibles.

---

## Paso 1 — Inventario

| Repo | Archivos fuente | Líneas (sin tests ni generados) |
|------|----------------:|--------------------------------:|
| `backend/` (Python) | 186 | 26 858 |
| `frontend/src/` (TS/TSX) | 363 | 51 297 |
| `continuity-mobile/src/` (TS/TSX) | 201 | 28 344 |
| **Total** | **750** | **106 499** |

Tests: backend 50 archivos / 10 434 líneas · frontend 28 archivos · **móvil 0** (ver §C-2).

Excluidos: `node_modules`, `.next`, `.expo`, `.venv`, `__pycache__`, `dist`, `build`,
`coverage`, `public/`, lockfiles, migraciones y los generados listados en §D.

---

## Paso 2 — Estado respecto de la auditoría anterior

### Sigue cerrado ✅

| Ítem | Verificado hoy |
|------|----------------|
| `core/assistant/tools/write.py` (1415) → paquete | ✅ `tools/write/{projects 235, tasks 277, routines 255, notes 214, quick_notes 209, ideas 138, categories 116}.py` + `__init__` 36 |
| `lib/graphql.ts` (2127 web / 1853 móvil) → carpeta | ✅ 20 módulos por dominio, barrel intacto |
| `core/schema.py` 2015 → 348 | ✅ sin regresión; **2** referencias ORM en todo el archivo |
| `core/cms/schema_admin.py` 1052 → 323 | ✅ lógica en `cms/services.py` (560) |
| `admin/page.tsx` 683 → 432 | ✅ |
| `RichEditor.tsx` 726 → 440 | ✅ |
| Tipado | ✅ **cero `: any`** en frontend y móvil; cero `Any` sin anotar en backend |
| Layering GraphQL | ✅ `schema_mutations.py` tiene **1** sola línea de ORM en 58 resolvers |

### Regresiones por crecimiento 🔴

Archivos que el refactor dejó bien y que **volvieron a crecer**:

| Archivo | Auditoría 2 | Hoy | Δ |
|---------|------------:|----:|---:|
| `frontend/src/components/Dashboard.tsx` | 718 | **841** | **+123** |
| `frontend/src/components/views/ProjectsView.tsx` | 480 | **601** | **+121** |
| `backend/core/schema_types.py` | 937 | **1011** | **+74** |
| `backend/core/schema_mutations.py` | 783 | **844** | **+61** |
| `frontend/src/components/views/TodayView.tsx` | 608 | 635 | +27 |
| `continuity-mobile/.../analytics/panels.tsx` | 923 | **925** | +2 (nunca se atendió) |

---

## Paso 3-A — Tabla priorizada

Leyenda: 🔴 urgente · 🟡 mejorar · ✅ aceptable

### Transversal (los dos repos de UI)

| Archivo / zona | Líneas | Estado | Problema principal | Recomendación concreta | Prioridad |
|---|---:|:--:|---|---|:--:|
| 56 pares `lib/`, `hooks/`, `lib/graphql/` con el mismo nombre en web y móvil | **12 732** | 🔴 | Lógica de negocio copiada entre dos repos, ya **derivando en silencio** (`graphql/admin.ts` 65 % similar, `integrations.ts` 49 %, `billing.ts` 10 %) | Publicar `@continuity/core` (npm privado o git submodule) empezando por los **15 archivos ≥95 % idénticos** (2 065 líneas): `recurrence.ts` y `date.ts` son **byte-idénticos**, `quickParse/quickDate` difieren en 3-7 líneas. Entre tanto: `scripts/check-shared-drift.mjs` en CI de ambos repos que falle si el hash de esos 15 archivos difiere | **P0** |
| `continuity-mobile/src/**` (tests) | 0 | 🔴 | Móvil corre ~6 000 líneas de lógica copiada **sin un solo test**; web sí testea `quickParse`, `quickDate`, `routineHistory`, `graveyard` | Copiar los 10 `*.test.ts` de `frontend/src/lib/` junto con los archivos que prueban. Es el paso que hace segura cualquier extracción a paquete compartido | **P0** |
| `components/markdown/parse.ts` (web 192 / móvil 199) | 391 | 🔴 | Parser puro **98 % idéntico** viviendo bajo `components/` en ambos — ni es componente ni es compartido | Mover a `lib/markdown/parse.ts` en ambos e incluirlo en el lote de `@continuity/core` | P1 |

### Frontend (`frontend/src/`)

| Archivo | Líneas | Estado | Problema principal | Recomendación concreta | Prioridad |
|---|---:|:--:|---|---|:--:|
| `components/Dashboard.tsx` | **841** | 🔴 | Un solo componente de 764 líneas con **59 imports**: 307 de hooks/handlers + **455 de JSX** que son dos cosas distintas — ruteo de 11 vistas (L438-610) y pila de 12 modales (L613-841) | Cortar en tres: `DashboardViewRouter.tsx` (el bloque `view === …`, ~175), `DashboardModals.tsx` (los 12 `<*Modal>`, ~230) y dejar `Dashboard.tsx` como shell (~290). Corte mecánico: el estado ya está en `useDashboardModals`/`useDashboardData` | **P0** |
| `components/ui/CommandPalette.tsx` | **705** | 🔴 | Componente de 622 líneas que mezcla 9 `useState`, parsing, búsqueda/goto, atajos de teclado, borrador persistido y render | `useCommandPalette.ts` (estado + borrador + guardado), `commandPaletteResults.ts` (`results`/`gotoDetail`, hoy 264 líneas puras y **testeables**), `CommandPaletteList.tsx`. Queda ~200 de UI | **P0** |
| `components/views/ProjectRow.tsx` | 497 | 🔴 | **Un componente de 425 líneas sin un solo hook**: es JSX condicional puro con 5+ estados visuales (bloqueado, pausado, muerto, lanzado, activo) | Un subcomponente por estado en `views/projectRow/` + `ProjectRow` como despachador de ~60 líneas. Sin estado que mover, es el refactor de menor riesgo del repo | P1 |
| `app/(app)/admin/billing/page.tsx` | 613 | 🟡 | Página de 478 líneas: 4 tipos locales, 3 formateadores, tabla + detalle + acciones | Tipos y `format*` → `admin/billing/types.ts`; tabla → `SubscribersTable.tsx`. Patrón replicable a las otras 20 páginas admin | P1 |
| `components/views/ProjectsView.tsx` | **601** | 🟡 | Regresión: se partió a 480 y volvió a 601 pese a existir ya `ProjectsFilters` (263) y `ProjectsListParts` (198) | El crecimiento es agrupación+orden: mover a `lib/projectGrouping.ts` (puro, testeable) | P1 |
| `components/today/sections.tsx` | 511 | 🟡 | **Mismo anti-patrón que `panels.tsx`**: 18 componentes en un archivo; el refactor de `TodayView` los volcó aquí | `today/sections/<nombre>.tsx` + barrel `index.ts`. Hacerlo a la vez que el de móvil (§B-1), que es su gemelo | P1 |
| `components/views/TodayView.tsx` | 636 | 🟡 | 516 líneas con 12 hooks; ya delega secciones | Mover el cálculo de visibilidad/orden de secciones a `lib/todaySections.ts` (ya existe, 73) | P2 |
| `components/tasks/TaskModal.tsx` | 624 | 🟡 | Contiene `BlockerTaskCombobox` (191) que no tiene nada que ver con el modal | Extraer `tasks/BlockerTaskCombobox.tsx` — corte limpio, 1 archivo | P2 |
| `components/views/RoutinesView.tsx` | 486 | 🟡 | 428 líneas / 13 hooks; materialización de ocurrencias dentro de la vista | `lib/routineOccurrences.ts` con `HORIZON_DAYS`/`BACKLOG_DAYS`/`LATER_LOOKAHEAD` (hoy duplicados literal en móvil) | P2 |
| `app/(app)/login/page.tsx` | 467 | 🟡 | 424 líneas: 3 vistas (signin/signup/forgot) en un componente | Un componente por `Mode` bajo `login/` | P2 |
| `app/(app)/admin/**` (21 páginas) | ~7 000 | 🟡 | 138 literales de copy en español embebidos; solo **3 de 21** usan `useTranslations` | Si el admin es monolingüe **a propósito**, documentarlo en `docs/admin-panel.md` y cerrar el tema. Si no, es deuda creciente | P2 |
| `lib/graphql/*` (20 archivos) | 2 312 | ✅ | Split sostenido, barrel intacto | Sin acción | — |
| `lib/` puro (`quickParse`, `quickDate`, `recurrence`, `graveyard`…) | ~2 000 | ✅ | Funciones puras, tipadas y **con tests** | Sin acción salvo compartirlas (§C-1) | — |

### Backend (`backend/core/`)

| Archivo | Líneas | Estado | Problema principal | Recomendación concreta | Prioridad |
|---|---:|:--:|---|---|:--:|
| `assistant/views.py` | **766** | 🔴 | **Hallazgo nuevo.** `ChatView.post` (85) anida `_run_stream` (36) que anida `_persist` (91): **3 niveles de función** y `Message.objects.create()` ejecutándose dentro de la vista. Además 9 clases `View` en un archivo | Sacar el streaming a `assistant/streaming.py` (`stream_turn(conv, …) -> Iterable[bytes]`) y la persistencia a `assistant/services/conversations.py::append_message()`. Luego partir por área: `views/{chat,actions,conversations,usage,health}.py` | **P0** |
| `admin_api/schema.py` | 647 | 🔴 | `admin_set_user_plan` / `_is_admin` / `_is_billing_exempt` son **tres bloques de 43 líneas que difieren en 5**; `admin_user` (123 líneas) consulta 5 modelos con ORM directo | `_set_profile_flag(uid, field, value, actor, action)` elimina ~86 líneas de copia; `admin_user` → `admin_api/services/user_detail.py` | **P0** |
| `core/schema_types.py` | **1011** | 🟡 | 42 `@strawberry.type` + inputs; creció +74 desde la pasada anterior sin límite declarado | `schema/types/<dominio>.py` (project, task, routine, integrations, analytics) con su `from_model`, ensamblado por barrel. Es cohesivo hoy, pero es el archivo que más crece del backend | P1 |
| `core/schema_mutations.py` | **844** | 🟡 | 58 métodos en **una** clase `Mutation` (+61). Layering ✅: 1 sola línea de ORM | Una `*Mutation` por dominio + `merge_types` — el patrón que ya funciona en `admin_api/` y `cms/` | P1 |
| `core/analytics.py` | 766 | 🟡 | 35 funciones + 20 dataclasses; servicio puro (8 usos de ORM, todos en `compute_analytics`) | `analytics/{types,cadence,backlog,ideas,effort,loop}.py`. El layering ya está bien, es solo tamaño | P2 |
| `assistant/prompts.py` (568) · `assistant/canned.py` (541) | 1 109 | ✅ | Son datos/plantillas, no lógica ramificada | Sin acción | — |
| `assistant/tools/read.py` (622) · `tools/write/` | 2 102 | ✅ | Tools delgadas que delegan a `core.services.*` | Sin acción | — |
| `core/models.py` (631) · `cms/services.py` (560) · `services/routines.py` (436) | 1 627 | ✅ | Capas correctas | Opcional: enums de `models.py` → `enums.py` | — |

### Móvil (`continuity-mobile/src/`)

| Archivo | Líneas | Estado | Problema principal | Recomendación concreta | Prioridad |
|---|---:|:--:|---|---|:--:|
| `components/analytics/panels.tsx` | **926** | 🔴 | **Tercera auditoría consecutiva sin atender.** 14 componentes exportados en un archivo; `LoopPanel` solo son 203 líneas. Lo consume **un** archivo (`analytics.tsx`, 198) | `analytics/panels/<panel>.tsx` + `index.ts` barrel. `LoopPanel` sale a su propio archivo con sus subcomponentes. El consumidor único hace que el import no cambie | **P0** |
| `app/(dashboard)/today.tsx` | 696 | 🟡 | Componente de 544 líneas pese a existir `today/sections.tsx` | Espejo del corte de web (§B-3): mismo nombre de sección, mismo archivo destino | P1 |
| `app/project/[id].tsx` | 542 | 🟡 | 459 líneas: detalle + edición de estado + notas + tareas en una pantalla | `project/[id]/sections/{Header,Notes,Tasks,StatusPicker}.tsx` | P1 |
| `app/(dashboard)/projects.tsx` | 499 | 🟡 | 455 líneas en **un** componente con `renderCard` inline de 285 | `renderCard` → `components/projects/ProjectCard.tsx` (ya existe `ProjectCardCompact`, 220: revisar si se fusionan) | P1 |
| `components/calendar/DayGrid.tsx` | 405 | 🟡 | 372 líneas; el gemelo web son 296 y **solo coinciden 53 %** — la lógica de layout de bloques divergió | Extraer el cálculo de posiciones a `lib/dayGridLayout.ts` **en ambos repos** y compartirlo; la divergencia aquí es un bug esperando | P1 |
| `app/(dashboard)/tasks.tsx` (461) · `routines.tsx` (408) | 869 | 🟡 | Mismos números mágicos que web (`HORIZON_DAYS`, `BACKLOG_DAYS`, `LATER_LOOKAHEAD`) redeclarados | Se resuelven solos al compartir `lib/routineOccurrences.ts` | P2 |
| `components/today/sections.tsx` | 544 | 🟡 | 18 componentes en un archivo (gemelo del de web) | Ver §B-3 | P1 |

---

## Paso 3-B — Top 10 urgentes: cómo partir cada uno

**1. `continuity-mobile/src/components/analytics/panels.tsx` (926)** — el más viejo sin atender.
```
analytics/panels/
  PanelCard.tsx      (81-110)     StatusBar.tsx        (503-530)
  StatTile.tsx       (111-144)    StatusBreakdown.tsx  (531-628)
  CadencePanel.tsx   (145-164)    BacklogPanel.tsx     (629-672)
  ActivityChart.tsx  (165-299)    WeekdayHeatmap.tsx   (673-705)
  LoopPanel.tsx      (300-502)    Delta.tsx            (706-732)
  TopProjects.tsx    (733-774)    SleepingStale.tsx    (775-860)
  IdeaFunnel.tsx     (861-889)    EffortPanel.tsx      (890-925)
  index.ts  ← barrel: el import de analytics.tsx no cambia
```
Movimiento verbatim, un solo consumidor, cero riesgo de comportamiento.

**2. `frontend/src/components/Dashboard.tsx` (841)** — cortar por las dos fronteras que ya existen en el JSX:
`DashboardViewRouter.tsx` ← L438-610 (los 11 `view === …`) · `DashboardModals.tsx` ← L613-841 (los 12 modales, que ya reciben todo de `useDashboardModals`) · shell final ~290.

**3. `today/sections.tsx` — los dos a la vez** (web 511 / móvil 544). Mismos 7 nombres de sección en ambos. Un archivo por sección bajo `today/sections/` + barrel, **con los mismos nombres de archivo en los dos repos**, para que la divergencia futura sea visible en el diff.

**4. `backend/core/assistant/views.py` (766)** — deshacer las closures anidadas: `_persist` → `assistant/services/conversations.py::append_message()`; `_run_stream`/`event_stream` → `assistant/streaming.py`; luego un archivo por grupo de vistas.

**5. `frontend/src/components/ui/CommandPalette.tsx` (705)** — `commandPaletteResults.ts` primero (264 líneas puras, se pueden testear el mismo día), después `useCommandPalette.ts`, y el componente baja a ~200.

**6. `backend/core/admin_api/schema.py` (647)** — el helper `_set_profile_flag` borra ~86 líneas de copia antes de tocar nada más; después `admin_user` → servicio.

**7. `frontend/src/components/views/ProjectRow.tsx` (497)** — sin hooks, sin estado: un archivo por estado visual. El refactor más barato del repo.

**8. `backend/core/schema_types.py` (1011)** — `schema/types/<dominio>.py`. Ponerle un techo (p. ej. `wc -l` en CI) o volverá a crecer, como ya hizo.

**9. `continuity-mobile/src/app/(dashboard)/today.tsx` (696)** y **10. `app/project/[id].tsx` (542)** — misma receta que §B-3, sección por archivo.

---

## Paso 3-C — Patrones sistémicos

**C-1 · Dos repos, un solo dominio, copiado a mano (🔴 el hallazgo de esta pasada).**
56 archivos comparten nombre entre `frontend/src` y `continuity-mobile/src`: **12 732 líneas**.

| Similitud | Archivos | Líneas (lado móvil) | Lectura |
|---|---:|---:|---|
| ≥95 % | 15 | 2 065 | copias literales (`recurrence.ts` y `date.ts` **idénticos**) |
| ≥85 % | 30 | 4 216 | copias con retoques |
| ≥70 % | 41 | 5 114 | — |
| <70 % | 15 | ~980 | **ya divergieron**: `graphql/admin.ts` 65 %, `integrations.ts` 49 %, `billing.ts` 10 % |

Lo grave no es la copia, es el **tramo de abajo**: documentos GraphQL que apuntan al mismo
esquema y ya no coinciden. Y como son tres repos git separados, no hay workspace que lo
detecte. Mínimo viable si extraer un paquete es caro ahora: un script de drift en CI sobre
los 15 archivos ≥95 %.

**C-2 · El móvil no tiene red.** 0 tests para 28 344 líneas, incluyendo los ~6 000 copiados.
`quickParse.ts` (372) y `quickDate.ts` (274) tienen tests **en web** y corren a ciegas en móvil.
Copiar esos 10 `*.test.ts` es barato y es precondición de C-1.

**C-3 · El refactor mueve el bulto, no lo divide.** `analytics.tsx` 1090 → 197 creando
`panels.tsx` de 926. `TodayView` 1231 → 635 creando `sections.tsx` de 511. `today.tsx` móvil
1450 → 696 creando `sections.tsx` de 544. Extraer a **un** archivo por zona cambia dónde está
el problema, no lo resuelve. Regla para la próxima ronda: **un componente exportado por
archivo + barrel**; el barrel mantiene los imports y el archivo deja de crecer.

**C-4 · Lo extraído vuelve a crecer.** `Dashboard` +123, `ProjectsView` +121, `schema_types` +74,
`schema_mutations` +61 desde la pasada anterior. Sin un techo automatizado (un `wc -l` en CI
sobre una lista corta de archivos ya refactorizados) la ronda 4 va a medir lo mismo que la 3.

**C-5 · Componentes que son 80 % JSX condicional.** `ProjectRow` 425 líneas / 0 hooks,
`projects.tsx` móvil con `renderCard` de 285, `DayGrid` 372. No es lógica enredada: es
ramificación visual sin nombre. Un subcomponente por estado los vuelve legibles sin tocar datos.

**C-6 · Lo que está bien y conviene no romper.** Layering GraphQL→servicios sólido
(`schema_mutations.py`: 1 línea de ORM en 58 resolvers; `schema.py`: 2). Cero `: any` en 79 000
líneas de TS. `lib/graphql/` partido y estable. Backend con 10 434 líneas de test.
Comentarios explicando el *porqué*, no el *qué* (`CommandPalette`, `ChatView`). La excepción
al buen layering es `assistant/views.py`, y es precisamente el 🔴 nuevo.

---

## Paso 3-D — Archivos posiblemente generados (excluidos)

No evaluados por ser salida de herramienta:

| Archivo | Genera |
|---|---|
| `frontend/src/design/tokens.rn.generated.ts` (401) · `themePreview.generated.ts` · `src/app/tokens.generated.css` | `frontend/scripts/generate-tokens.mjs` |
| `continuity-mobile/src/theme/tokens.generated.ts` (406) | mismo pipeline; validado por `scripts/check-tokens.mjs` |
| `continuity-mobile/.expo/types/router.d.ts` | Expo Router (typed routes) |
| `frontend/next-env.d.ts` · `continuity-mobile/{expo,nativewind}-env.d.ts` | frameworks |
| `frontend/tsconfig.tsbuildinfo` · `frontend/build.log` | build |

Dudosos que **sí** se revisaron por contener decisiones a mano: `frontend/src/lib/types.ts` (401)
y `continuity-mobile/src/lib/types.ts` (374) — escritos a mano y **divergentes al 89 %**, no son
salida de codegen. Entran en el lote de C-1.

Sin evaluar por estar fuera de alcance: `frontend/scripts/refactor-*.ps1` (4 scripts de refactor
puntuales ya ejecutados) — candidatos a borrar si la migración de color/tema está cerrada.

---

## Resumen

**Lo que mejoró:** los 🔴 de las rondas 1-2 siguen cerrados. El split de `write.py`,
`lib/graphql.ts`, `schema.py` y `cms/schema_admin.py` aguantó. Layering backend y tipado TS
están en muy buen estado.

**Lo que empeoró:** cuatro archivos ya refactorizados volvieron a crecer (+379 líneas entre
`Dashboard`, `ProjectsView`, `schema_types` y `schema_mutations`), y `panels.tsx` (926) lleva
tres auditorías sin tocarse.

**Lo nuevo y lo más caro:** la duplicación web↔móvil — 12 732 líneas en 56 archivos, con el
tramo ya divergente afectando documentos GraphQL del mismo esquema — agravada porque el móvil
no tiene un solo test. Esto no se arregla partiendo archivos; necesita una decisión sobre
código compartido entre los tres repos.

**Si solo se hace una cosa:** copiar los 10 `*.test.ts` de `frontend/src/lib/` a móvil. Es
media hora, cubre las 838 líneas de lógica pura más crítica, y es lo que hace seguro todo lo
demás de §C-1.

**Orden sugerido:** C-2 (tests móvil) → panels.tsx → Dashboard → assistant/views.py →
admin_api helper → el resto por prioridad. Nada de esto cambia comportamiento.

No se modificó ningún archivo de código. Quedo a tu revisión.

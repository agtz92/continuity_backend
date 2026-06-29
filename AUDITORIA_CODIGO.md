# Auditoría de Código — Modularidad y Legibilidad (re-auditoría 2)

**Proyecto:** Continuity (monorepo: `frontend/` Next.js+Apollo, `backend/` Django+Strawberry, `mobile/` Expo/React Native)
**Alcance:** Todo el código fuente excepto dependencias, build, código generado, migraciones y tests.
**Naturaleza:** Solo lectura. Este reporte no modifica código.
**Contexto:** Tercera pasada. Las dos primeras dispararon una ronda de refactor que **sí se ejecutó** (confirmado contra el disco). El reporte anterior tenía el resumen a medio actualizar (citaba tamaños pre-refactor); esta pasada re-mide todo y deja números **coherentes**.

---

## Ya resuelto (rondas de refactor previas — verificado en disco)

| Antes | Ahora | Cómo |
|-------|-------|------|
| `lib/graphql.ts` web 2127 / mobile 1853 | carpetas `lib/graphql/{dominio,fragments,index}.ts` (50–360 c/u) | barrel mantiene el import `@/lib/graphql` ✅ |
| `core/schema.py` 2015 | **358** + `schema_types.py` 937 + `schema_mutations.py` 783 + `schema_helpers.py` | `merge_types`; ORM ya estaba en servicios ✅ |
| `core/admin_api/schema.py` 1522 | **647** + `types.py` 327 + `schema_billing.py` 261 + `schema_system.py` 393 | partido por área con `merge_types` ✅ |
| `core/cms/schema_admin.py` 1052 | **323** + `cms/types.py` 313 + `cms/services.py` 560 | ORM/validación/render/auditoría → servicio ✅ |
| `TodayView.tsx` 1231 | **608** + `today/*` | 10 secciones + lógica extraídas ✅ |
| `ProjectsView.tsx` 1180 | **480** + `ProjectsFilters` 231 + `ProjectsListParts` 149 | ✅ |
| `RichEditor.tsx` 726 | **440** + Toolbar/SlashMenu | ✅ |
| `admin/page.tsx` 683 | **432** + `adminHomeData.ts` + `AdminHomeCards.tsx` | ✅ |
| `Dashboard.tsx` 808 | **718** + `useDashboardModals` | estado extraído; JSX inline a propósito 🟡 |
| mobile `analytics.tsx` 1090 | **197** | paneles → `analytics/panels.tsx` ⚠️ (ver abajo: se volvió god-file) |
| mobile `today.tsx` 1450 | **691** + `today/*` | secciones extraídas 🟡 |

> Todos los **🔴 originales están cerrados**. Esta pasada detecta **2 regresiones/efectos colaterales** del refactor y reconfirma los 🟡 que quedaron por ROI.

---

## Resumen ejecutivo (estado ACTUAL, medido)

| Área | Archivo más grande hoy | Líneas | Veredicto |
|------|------------------------|-------:|-----------|
| Mobile | `components/analytics/panels.tsx` | **923** | 🔴 **nuevo** — el refactor de `analytics` volcó todos los paneles aquí |
| Frontend | `components/Dashboard.tsx` | **718** | 🟡 estado ya extraído; resto es JSX inline (decisión consciente) |
| Backend | `core/schema_types.py` | **937** | 🟡 definiciones cohesivas (post-refactor); `write.py` ✅ partido en paquete `tools/write/` |

> **Actualización:** `core/assistant/tools/write.py` (1415) **ya se partió** en el paquete `tools/write/` (ver A·Backend y B·1). Quedaba como único 🔴 de backend; ahora el mayor es `schema_types.py` (937, definiciones cohesivas).

---

## A) Tabla priorizada

Leyenda: 🔴 urgente · 🟡 mejorar · ✅ aceptable

### Backend

| Archivo | Líneas | Estado | Problema principal | Recomendación concreta |
|---------|-------:|:------:|--------------------|------------------------|
| `core/assistant/tools/write.py` | ~~1415~~ → **paquete** | ✅ | (resuelto) Era god-file de 32 funciones `_verbo_entidad`. | **Hecho:** partido en `tools/write/{projects 235, tasks 277, routines 255, notes 214, ideas 138, categories 116, quick_notes 209}.py` + `__init__.py` que importa cada submódulo (dispara el registro `@tool`). Movimiento verbatim de los cuerpos; registro idéntico (44 tools, mismos `plan_required`/`mutates`). 25 tests assistant + 71 mcp verdes. **Pendiente (2ª fase, aparte):** mover el "merge de updates" a los servicios de dominio |
| `core/schema_types.py` | 937 | 🟡 | Producto del refactor: 42 `@strawberry.type` + inputs en un archivo (cohesivo, solo definiciones) | Opcional (ROI medio): `schema/types/<dominio>.py` con su `from_model`. Cohesivo hoy, no bloquea |
| `core/schema_mutations.py` | 783 | 🟡 | Producto del refactor: todas las mutations en una clase | Opcional: una `*Mutation` por dominio + `merge_types` (patrón ya usado en admin/cms) |
| `core/analytics.py` | 766 | 🟡 | Servicio puro pero creció a ~35 funciones (Loop analytics) | Partir por familia: `analytics/{cadence,backlog,ideas,effort,loop}.py`. Buen layering ya |
| `core/admin_api/schema.py` | 647 | ✅ | Post-refactor (users + ensamblaje) | Sin acción |
| `core/assistant/tools/read.py` | 622 | ✅ | Tools delgadas que delegan | Sin acción |
| `core/models.py` | 621 | ✅ | Modelos (datos) | Opcional: enums → `enums.py` |
| `core/cms/services.py` | 560 | ✅ | Capa de servicio cohesiva | Sin acción |

### Frontend

| Archivo | Líneas | Estado | Problema principal | Recomendación concreta |
|---------|-------:|:------:|--------------------|------------------------|
| `components/Dashboard.tsx` | 718 | 🟡 | Estado ya en `useDashboardModals`; queda JSX de vistas + ~14 modales inline | Partir solo si crece más: `DashboardViewRouter`/`DashboardModals` mueven líneas pero piden ~35 props c/u (net-negativo hoy) |
| `components/views/TodayView.tsx` | 608 | 🟡 | Orquesta 10 secciones + cola stalled + modo personalizar | Aceptable post-refactor; opcional mover el modo personalizar a hook |
| `components/tasks/TaskModal.tsx` | 601 | 🟡 | **Creció (era 544)** por feature de bloqueos: `BlockerTaskCombobox` (~180 líneas, portal+posicionamiento) anidado + 4 helpers de fecha | Extraer `BlockerTaskCombobox.tsx` y `lib/dateConversion.ts` (addDays/upcomingFridayISO/iso↔input) |
| `app/(app)/admin/billing/page.tsx` | 595 | 🟡 | 4 tablas con paginación/orden copy-paste | `tables/*Table.tsx` + hook `useTableSort` |
| `components/projects/ProjectDetailModal.tsx` | 553 | 🟡 | Selects + secciones anidadas (ya usa `ProjectTaskRow`) | Extraer `detail/*` + `selects/*` |
| `app/(app)/settings/billing/page.tsx` | 532 | 🟡 | Plan + tabla de precios + modales en un page | `billing/{CurrentPlan,PricingTable,DowngradeModal}.tsx` |
| `components/today/sections.tsx` | 491 | 🟡 | Las 8 secciones extraídas de TodayView en un archivo | Aceptable; opcional partir por sección |
| `components/views/ProjectsView.tsx` | 480 | ✅ | Filtros + lista/DND ya extraídos | Sin acción |
| `components/views/ProjectRow.tsx` | 425 | 🟡 | Fila + detalle expandido | Opcional: separar header / detalle |

### Mobile

| Archivo | Líneas | Estado | Problema principal | Recomendación concreta |
|---------|-------:|:------:|--------------------|------------------------|
| `components/analytics/panels.tsx` | 923 | 🔴 | **Efecto colateral del refactor:** `analytics.tsx` bajó a 197 pero TODOS los paneles + `PanelCard`/`StatTile`/`ActivityChart`/`StatusBar`/`Delta` + 10 constantes de color quedaron en 1 archivo. `LoopPanel` solo es ~200 líneas | Aplicar lo que pedía la rec original: `analytics/PanelCard.tsx` + `ActivityChart.tsx` + `analytics/colors.ts` + un `*Panel.tsx` por gráfico (Cadence/StatusBreakdown/Backlog/Weekday/TopProjects/IdeaFunnel/Effort/Loop/Sleeping) |
| `app/(dashboard)/today.tsx` | 691 | 🟡 | 10 secciones ya extraídas; queda modo personalizar + cola stalled | Aceptable; opcional hook para personalizar |
| `components/today/sections.tsx` | 554 | 🟡 | Secciones chicas en un archivo (espejo de web) | Aceptable; opcional partir |
| `app/project/[id].tsx` | 510 | 🟡 | `statusActions` con ifs; `relativeTime` duplicado; labels en inglés | `StatusActionBuilder.ts`, `lib/textUtils.ts`, i18n |
| `app/(dashboard)/tasks.tsx` | 449 | 🟡 | `buckets` filter+sort; búsqueda duplicada con projects | `hooks/useTaskBuckets.ts`, `SearchBar` compartido |
| `app/(dashboard)/projects.tsx` | 444 | 🟡 | Comparador + 3 rutas de render; búsqueda duplicada | `hooks/useProjectSort.ts`, `SearchBar` compartido |
| `app/(dashboard)/routines.tsx` | 406 | 🟡 | `useMemo` de bucketing grande | `hooks/useRoutineBuckets.ts` |
| `app/(dashboard)/(more)/log.tsx` | 391 | 🟡 | `describe()` switch por ActivityKind | `lib/activityPresentation.ts` |
| `app/(dashboard)/(more)/notifications.tsx` | 380 | 🟡 | useQuery+mutations + cache write inline | `components/settings/*` |

---

## B) Top archivos urgentes — cómo dividir cada uno

### 1. `backend/core/assistant/tools/write.py` (1415) — ✅ HECHO
Era un dispatcher con 32 funciones `_verbo_entidad`. Partido en paquete `tools/write/`:
- Un módulo por dominio: `projects.py` (235), `tasks.py` (277, incluye task blockers), `routines.py` (255), `notes.py` (214, project notes + project updates), `ideas.py` (138), `categories.py` (116), `quick_notes.py` (209, + note sections).
- `tools/write/__init__.py` conserva el docstring de la tier Pro e **importa cada submódulo** para disparar el registro vía `@tool` (mismo mecanismo que el `tools/__init__.py` padre, que sigue haciendo `from . import write` → ahora el paquete).
- Cuerpos movidos **verbatim**; constantes de dominio (`_STATUS`/`_PRIORITY` → projects; `_ROUTINE_RULE_PROPS` → routines) viven con su dominio; los parsers se importan de `..datetime_utils`.
- **Verificado:** registro idéntico (44 tools, mismos nombres/`plan_required`/`mutates`), 25 tests assistant + 71 mcp verdes.
- **2ª fase pendiente (mayor riesgo, aparte):** el "merge parcial de updates" se repite en cada `_update_*`; subirlo a los servicios de dominio (`services/{projects,tasks,...}.py`) y dejar la tool como parse→servicio→formato.

### 2. `mobile/src/components/analytics/panels.tsx` (923) — regresión del refactor
El refactor adelgazó la pantalla pero creó este god-file. Es exactamente la división que la auditoría anterior recomendó y que **no se aplicó**:
- `analytics/colors.ts` (las 10 constantes `AMBER`…`BLUE`).
- `analytics/PanelCard.tsx` (+ `StatTile`, `StatusBar`, `Delta` — piezas compartidas).
- `analytics/ActivityChart.tsx` (el SVG a mano, ~124 líneas).
- Un archivo por panel: `CadencePanel`, `StatusBreakdownPanel`, `BacklogPanel`, `WeekdayHeatmap`, `TopProjectsPanel`, `IdeaFunnelPanel`, `EffortPanel`, `SleepingStalePanel`, y **`LoopPanel`** (el más grande, ~200 líneas — prioritario).

### 3. `frontend/src/components/tasks/TaskModal.tsx` (601) — creció por feature
- `BlockerTaskCombobox.tsx`: el combobox portalizado con su `updatePosition`/listeners/`groups` (~180 líneas) sale completo.
- `lib/dateConversion.ts`: `addDays`, `upcomingFridayISO`, `isoToInputDate`, `inputDateToIso` (hoy locales y candidatos a duplicarse en otros modales).
- `DateChip` puede ir a `tasks/DateChip.tsx` si se reusa.

### 4. `backend/core/analytics.py` (766)
- Servicio sano pero creció. Partir por familia de métrica en `analytics/{cadence,backlog,ideas,effort,loop}.py` + `__init__.py`. Sin cambio de contrato.

### 5–6. `schema_types.py` (937) / `schema_mutations.py` (783) — opcionales
- Productos del refactor anterior: cohesivos (solo definiciones). Si se quiere bajar más, ir a `schema/types/<dominio>.py` y `*Mutation` por dominio con `merge_types`. ROI medio; no urgente.

### 7. `frontend/admin/billing/page.tsx` (595)
- 4 tablas casi idénticas con orden/paginación → `tables/{Invoices,Subscriptions,...}Table.tsx` sobre un hook `useTableSort`.

---

## C) Patrones sistémicos (estado actual)

1. **El refactor puede mover el bloat, no eliminarlo.** `analytics.tsx`→`panels.tsx` y `schema.py`→`schema_types.py`/`schema_mutations.py` redujeron el archivo "cara" pero concentraron el volumen en el destino. La métrica a vigilar no es "tamaño de la pantalla/entrypoint" sino "tamaño del archivo más grande del subárbol". → cerrar `panels.tsx`.
2. **Dispatchers que crecen con el dominio (backend).** `write.py` (tools) y los `schema_*.py` escalan con #entidades. El patrón sano del repo (paquete por dominio + barrel / `merge_types`) ya existe; falta aplicarlo en estos.
3. **Vistas/pantallas grandes con UI-state + ruteo inline.** Dashboard, modales de tareas/proyectos, pantallas mobile. Fix probado: secciones/paneles a componentes + hooks de estado.
4. **Duplicación web↔mobile no compartible** (buckets/orden/búsqueda reimplementados por plataforma). Inevitable entre repos, pero **dentro** de mobile hay duplicación extraíble: `SearchBar`, `useTaskBuckets`/`useProjectSort`, `relativeTime`/`textUtils`.
5. **Helpers de fecha dispersos.** Backend: parsers en `write.py` (ya hay `datetime_utils.py`, falta migrar el resto). Frontend: conversiones iso↔input en `TaskModal`. Mobile: `relativeTime` duplicado. Candidatos a un util por plataforma.

---

## D) Archivos posiblemente generados (excluidos por duda)

- **Migraciones** (`*/migrations/`), `*.d.ts`, `mobile/.expo/`, `.next/`, locks — excluidos.
- **`lib/graphql/` (web y mobile):** escritos a mano (no codegen) — evaluados como fuente; sanos (~50–360 líneas c/u).
- **`lib/types.ts` (web 372 / mobile 367):** a mano; sanos.
- No se hallaron marcadores `@generated` en el árbol fuente.

---

## Resumen final

- **El refactor anterior cumplió su objetivo de capas** (ORM fuera de resolvers, `graphql.ts` partidos, schema backend con `merge_types`, vistas web descompuestas). El reporte previo solo había quedado con el texto del resumen desactualizado; esta pasada lo corrige con números medidos.
- **Frentes 🔴:**
  1. ✅ `backend/core/assistant/tools/write.py` (1415) — **hecho**: partido en paquete `tools/write/` por dominio (registro idéntico, tests verdes).
  2. ⏳ `mobile/.../analytics/panels.tsx` (923) — **regresión** introducida por el propio refactor; pendiente aplicar la división por panel que ya estaba recomendada.
- **🟡 reconfirmados:** `TaskModal.tsx` (creció a 601 por bloqueos), `analytics.py` (766), `schema_types/mutations` (opcionales, cohesivos), y las pantallas mobile de paridad.
- **Decisiones conscientes que se mantienen:** no partir el JSX inline de `Dashboard.tsx` (los `DashboardViewRouter`/`DashboardModals` exigirían ~35 props y añadirían indirección sin reducir complejidad real).

Quedo a la espera de tu revisión.

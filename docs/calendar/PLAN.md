# Calendar — vista de calendario in-app (Día / Semana / Mes)

> Plan de implementación **Fase 1**. Estado: diseño cerrado, listo para construir.
> Hermano de la feature de **integración** (exportar a Google/iCloud) y del trabajo de
> **horas** (`due_time` en Task, `time_of_day` en Routine) que corre en paralelo —
> esta vista **consume** esos campos, no los define.

## Estado: Fase 1 construida (2026-06-24)

Implementado y `tsc --noEmit` + `next build` en verde. **Cambio de arquitectura vs.
el plan original: NO se añadió query/servicio de backend.** La query `dashboard` ya
devuelve projects/tasks/routines/occurrences (con `dueTime`/`timeOfDay`/`durationMinutes`/
`effortHours`), así que la vista reúsa esa data ya cargada y expande ocurrencias de rutina
en cliente con `computeDueDates()` (`src/lib/recurrence.ts`). Cero round-trips nuevos.

Archivos: `src/lib/calendar.ts` (lógica pura), `src/components/calendar/{parts,WeekGrid,
MonthGrid,DayGrid}.tsx`, `src/components/views/CalendarView.tsx`; nav en `TabBar.tsx`/
`MoreSheet.tsx`/`Dashboard.tsx`; i18n `tabs.calendar` + `views.calendar.*` (en/es).
El **espejo en `continuity-mobile`** ya está construido (`src/app/(dashboard)/(more)/calendar.tsx`,
`src/components/calendar/`, `src/lib/calendar.ts`). Pendiente: drag-to-reschedule (Fase 1.5).

## 1. Objetivo

Dar visibilidad de **cómo se reparte el trabajo en el tiempo, a nivel proyecto**, antes
de que los deadlines lleguen encima. No es un task-manager con fechas: es un lente sobre
proyectos + rutinas, con la carga (horas) del día visible de un vistazo.

### Modelo mental (decidido con el usuario)
- **Capa base, siempre visible: Proyectos + Rutinas.** NO tasks sueltas.
- **Default = nivel proyecto.** Un proyecto aparece en un día como **un chip con contador**
  (`Continuity · 2` = 2 tasks suyas caen ese día). El día de un proyecto se deriva de las
  fechas de **sus tasks** (rollup), no de `Project.due_date` (que casi no se usa). Un
  proyecto sin tasks fechadas esa semana simplemente no aparece.
- **"Ver tasks" es un toggle** (off por default): expande cada chip de proyecto en sus tasks.
- **Solo 2 complicaciones:** `Ver tasks` y `Carga`. Nada de color×categoría, completadas,
  notas, rail de atrasados. Simple e intuitivo.

## 2. Ubicación en navegación

Tab nuevo **entre `routines` e `ideas`**.

- `src/components/dashboard/TabBar.tsx`:
  - Añadir `"calendar"` al union `DashboardView` entre `"routines"` y `"ideas"`.
  - Añadir `{ id: "calendar", icon: Calendar }` al array `TABS` en esa misma posición
    (`Calendar` de `lucide-react`).
  - `data-tour`: opcional; si se quiere paso de tour, sumar `"calendar"` a la condición y a
    `DashboardTour.tsx` (condicional a `findVisible("calendar")`, igual que `notes`).
- `src/components/dashboard/MoreSheet.tsx` (mobile-web): añadir la entrada `calendar` en el
  mismo orden.
- `src/components/Dashboard.tsx`: importar `CalendarView` y renderizar cuando `view === "calendar"`.
- i18n: clave `tabs.calendar` en `messages/{en,es}.json` ("Calendar" / "Calendario").

## 3. Backend (Django + Strawberry, app `core`)

### 3.1 Lo que ya existe (reusar, no reescribir)
- `routinesDue(from_date, to_date)` → `core/schema.py` (~L894), apoyado en
  `routines_svc.list_due_in_range()` y la función pura `compute_due_dates()`
  (`core/services/routines.py`). Maneja los 4 tipos de recurrencia. **El motor de
  ocurrencias on-the-fly ya está hecho.**

### 3.2 Lo que falta
No hay query por **rango de fechas** para Tasks ni Projects (hoy el dashboard los trae
en bloque). Añadir **una** query combinada para un solo round-trip:

```graphql
calendar(fromDate: Date!, toDate: Date!): CalendarPayload!

type CalendarPayload {
  routineItems: [RoutineDueItem!]!   # reusa list_due_in_range
  tasks: [Task!]!                    # tasks con due_date en rango
  projects: [Project!]!             # projects con due_date en rango (capa deadline, off por default)
}
```

- Servicio nuevo `core/services/calendar.py` → `get_calendar(user_id, from_date, to_date)`:
  - `routine_items = routines.list_due_in_range(user_id, from_date, to_date)`
  - `tasks = Task.objects.filter(project__user_id=user_id, done=False, due_date__date__gte=from-1, due_date__date__lte=to+1)` (incluye `effort_hours`, `due_time`, `project_id`).
  - `projects = Project.objects.filter(user_id=user_id, due_date__date__gte=from-1, due_date__date__lte=to+1)`.
- **Timezone:** se filtra con **±1 día de colchón** en el backend y el **bucketing fino por
  día se hace en el frontend** con `toLocalISO` (hora local del dispositivo, como ya hace
  `date.ts`). Así evitamos bugs de TZ en el server.
- **Dependencia de la sesión de horas:** los tipos GraphQL `Task` y `Routine`/`RoutineDueItem`
  deben exponer `due_time` y `time_of_day`. Los **agrega esa sesión**; aquí solo se consumen.
  Si aún no existen al construir, la query funciona igual y los ítems caen como "todo el día".
- Tests: `pytest` desde el `.venv` de la raíz — rango + colchón + que un task fuera de rango
  no aparezca; rutina recurrente que cae dentro sí.

## 4. Frontend (Next.js 15 App Router, Apollo, Tailwind)

### 4.1 Datos
- `src/lib/graphql.ts`: `CALENDAR_QUERY` (campos arriba; incluir `dueTime`, `timeOfDay`,
  `effortHours`, `projectId`, `done`, `completed`).
- `src/hooks/useCalendarData.ts`: `useLazyQuery(CALENDAR_QUERY)`, `fetchPolicy: "cache-and-network"`,
  parametrizado por `{ from, to }` según vista; refetch al cambiar de rango.
- `src/lib/types.ts`: extender `Task` con `dueTime: string | null` y `Routine`/`RoutineDueItem`
  con `timeOfDay: string | null` (aditivo; coordinar con la sesión de horas).

### 4.2 Lógica pura — `src/lib/calendar.ts`
Construida sobre `src/lib/date.ts` (`toLocalISO`, `weekStartISO`, etc.). Sin estado, testeable:
- `weekDays(ref): string[]` (7 ISO, lunes-ancla vía `weekStartISO`).
- `monthMatrix(ref): string[][]` (semanas × 7, lunes-ancla, con relleno mes anterior/siguiente).
- `bucketByDay(items): Map<isoDay, Item[]>` usando `toLocalISO`.
- `rollupByProject(tasksOfDay): ProjectCell[]` → `{ project, tasks, count, effortSum }`.
- `dayLoadHours(tasksOfDay, routinesOfDay): { hours, hasUnestimated }` (suma `effort_hours`,
  excluye `null`, marca cuántos quedaron "sin estimar").
- `loadLevel(hours): "calm" | "busy" | "over"` con umbral `OVERLOAD_HOURS = 8` (constante única).
- `hoursRange(itemsOfDay): { start, end }` para la vista Día (default 7–21, se expande a ítems).

### 4.3 Componentes — `src/components/views/CalendarView.tsx` + `src/components/calendar/*`
- `CalendarView.tsx`: contenedor. Estado en `localStorage`:
  - `cont.calendar.view` = `"day" | "week" | "month"` (default `"week"`).
  - `cont.calendar.showTasks` (bool, default `false`).
  - `cont.calendar.showLoad` (bool, default `true`).
  - `cont.calendar.layers.projectDeadlines` (default `false`).
- `CalendarToolbar.tsx`: switcher Día/Semana/Mes, nav `‹ ›` + "Hoy", y los toggles
  `Ver tasks` / `Carga`. (El selector de capa "Proyectos (deadline)" vive aquí, off por default.)
- `MonthGrid.tsx`: matriz 5–6 semanas; por celda hasta 3 chips (proyecto/rutina) + `+N más`;
  mini-indicador de carga. Click en día → cambia a vista Día.
- `WeekGrid.tsx`: 7 columnas; barra de carga por día (header); chips de proyecto (rollup) +
  rutinas. **Vista por defecto.**
- `DayGrid.tsx`: **por horas.** Gutter de horas, fila **"todo el día"** para ítems sin
  `due_time`/`time_of_day`, bloques posicionados por hora con **altura ∝ `effort_hours`**,
  línea de "ahora", chip de carga del día.
- `ProjectChip.tsx` / `EventChip.tsx`: chip de proyecto (nombre + badge contador) y de rutina;
  con `Ver tasks` on, el de proyecto se reemplaza por chips de task.
- `LoadBar.tsx`: barra/segmento de carga según `loadLevel`.

### 4.4 Drag-to-reschedule (Fase 1.5, opcional)
Reusar `@dnd-kit` (ya instalado). Soltar un chip en otro día → mutación `updateTask` con nuevo
`due_date`; en vista Día, soltar en una hora → set `due_time`. Gateado a Pro (igual que el resto
de escrituras). Marcado como stretch, no bloquea Fase 1.

## 5. Integración con el sistema de diseño (sin hardcodear nada)

**Regla dura: cero hex de tema, cero `font-family`. Todo sale de los tokens.**

- **Colores de tema** vía clases sólidas: `bg-bg`, `bg-surface`, `bg-border`, `text-text`,
  `text-text-muted`, `bg-accent`, `text-accent`, `accent-2`. Respetan palette y tema del usuario.
- **Opacidad sobre color de tema** → NUNCA `bg-accent/15`. Usar `color-mix()` arbitrario:
  `bg-[color-mix(in_srgb,var(--accent)_15%,transparent)]` (ver CLAUDE.md del frontend).
- **Color por tipo de ítem (sin inventar hex):**
  - Rutina → `accent`.
  - Proyecto → color de **su categoría** vía `categoryColorClass(category.color)` (ya existe en
    `types.ts`); si el proyecto no tiene categoría, `accent-2`.
- **Colores semánticos fijos** (sí permiten `/opacity` porque son de la paleta Tailwind, no del
  tema): carga sobre umbral → `bg-red-500/20 text-red-400`; advertencia → `amber-500`. Solo para
  semántica fija (sobrecarga/atraso), no para estados que deban seguir la palette.
- **Tipografía:** heredada del sistema; ningún `font-family` ni tamaño hardcodeado fuera de las
  utilidades Tailwind ya usadas en otras vistas.
- **Iconos:** `lucide-react` (`Calendar`, etc.), tamaño 14 como el resto de tabs.
- **i18n:** todo el texto en `views.calendar.*` y `tabs.calendar` (`messages/{en,es}.json`).
  Nada de strings sueltos en el componente.
- **Estados:** loading (skeleton con `bg-surface`), vacío ("nada agendado esta semana"), error.
- **Render dinámico:** vive bajo `(app)` → ya es dinámico; no toca el root layout ni cookies.

## 6. i18n

- `tabs.calendar`: "Calendar" / "Calendario".
- `views.calendar.*`: títulos de vista (day/week/month), "Hoy", "Ver tasks", "Carga",
  "todo el día", "+N más", "≈ {h} h", "sin estimar", "nada agendado", "ahora".
- en **y** es. Espejo en el repo móvil (`continuity-mobile`).

## 7. Espejo móvil

Replicar tab, vista y lógica en `continuity-mobile` (misma convención que Quick Notes / estados).
La lógica pura de `src/lib/calendar.ts` debería poder portarse casi 1:1.

## 8. Decisiones cerradas (sin preguntas abiertas)

| Tema | Decisión |
|---|---|
| Vista default | **Semana** (mejor para "repartir"); se recuerda la última usada |
| Granularidad proyecto/task | **Proyecto** por default; `Ver tasks` la expande |
| Complicaciones | **Solo 2**: Ver tasks, Carga |
| Capa "Proyectos (deadline)" | Existe, **off** por default (hoy casi no hay `due_date` de proyecto) |
| Umbral de sobrecarga | `OVERLOAD_HOURS = 8` (constante única, fácil de ajustar) |
| Timezone | Filtro backend con ±1 día; **bucketing local en frontend** (`toLocalISO`) |
| Color de proyecto | Color de su categoría; si no tiene, `accent-2` |
| Hora opcional | Sin `due_time`/`time_of_day` → fila "todo el día" en vista Día |
| Drag-to-reschedule | Fase 1.5 opcional, gateado a Pro |

## 9. Orden de implementación

1. **E1 — Backend:** `core/services/calendar.py` + query `calendar(from,to)` + tests pytest.
2. **E2 — Nav:** tab en `TabBar`/`MoreSheet`/`Dashboard` + i18n `tabs.calendar`.
3. **E3 — Datos FE:** `CALENDAR_QUERY`, `useCalendarData`, tipos.
4. **E4 — Lógica pura:** `src/lib/calendar.ts` (+ tests si aplica).
5. **E5 — Semana** (default) con rollup por proyecto + barra de carga + toggles.
6. **E6 — Mes.**
7. **E7 — Día por horas** (consume `due_time`/`time_of_day`).
8. **E8 — i18n completa + espejo móvil.**
9. **E9 (opcional) — Drag-to-reschedule.**

Dependencia cruzada: **E7** necesita que la sesión de horas haya expuesto `due_time`/`time_of_day`
en los tipos GraphQL. E1–E6 no dependen de ella (caen como "todo el día" mientras tanto).

## 10. Verificación

- Backend: `pytest` desde el `.venv` de la raíz.
- Frontend: typecheck con `/opt/homebrew/bin/node node_modules/typescript/bin/tsc --noEmit`
  (node/pnpm no están en el PATH del sandbox).

# Project State Closure System — referencia técnica (as-built)

> **⚑ ESTADO (actualizado 2026-06-28): IMPLEMENTADO — este es el documento canónico** de la
> feature de cierre de estados, verificado contra el código. El estado vive en producción
> (estado `killed`, stalled a 14 días vía `detect_stalled_projects`, notas de cierre, graveyard +
> `GraveyardInsight`, autopsia IA en `core/services/autopsy.py`), web y móvil. El brief de diseño
> original se archivó en [`_archive/state-closure/STATE_CLOSURE_FINAL.md`](_archive/state-closure/STATE_CLOSURE_FINAL.md);
> donde ese brief y el código discrepen, **prevalece el código** (y este documento, que recoge las
> correcciones). Las "Decisiones abiertas" (§14) siguen siendo el pendiente real de producto.

> Nació como addendum correctivo del brief archivado. **No cambia ninguna decisión de producto** (estado `killed`, notas obligatorias en paused/killed, stalled a 14 días, filtrado de vistas diarias, tier cap status quo). Solo reemplaza los snippets y supuestos técnicos del brief que **no coinciden con el código real** y que, implementados literalmente, romperían el build o features existentes. Incluye explícitamente la cobertura para **web + móvil** y para **Loop (IA in-app) + conector de Claude**.
>
> Cada sección dice: *Lo que dice el brief* → *La realidad del código* → *Cómo hacerlo bien*. Todo verificado contra el código a fecha de este documento.

---

## 0. Resumen de cambios respecto al brief

| # | Tema | Severidad | Qué corrige |
|---|---|---|---|
| 1 | Log de `Activity` (sin `metadata`/FK) | 🔴 Bloqueante | Usar `log_event`, no `Activity.objects.create(metadata=…)` |
| 2 | Doble registro de cambio de estado | 🔴 Bloqueante | Extender el log existente, no añadir uno nuevo |
| 3 | Firma real de `update_project` | 🔴 Bloqueante | Conservar `(user_id, project_id, *, name, …)` |
| 4 | Tareas sin proyecto en los filtros | 🔴 Bloqueante | `Q(project__isnull=True) | Q(project__status__in=…)` |
| 5 | Today web/móvil NO usa `list_tasks` | 🟠 Importante | Filtrado en `useTodayFocus` (cliente); `list_tasks` solo afecta IA |
| 6 | Excluir `launched` rompe "Launched with tasks" | 🟠 Importante | Decisión de producto a confirmar |
| 7 | Radio real de "borrar sleeping" | 🟠 Importante | +`read.py`, `DashboardSummary`, digest semanal, `prompts.py` |
| 8 | Loop + conector (tool real, enums, policy, prompt) | 🟠 Importante | El tool es `update_project`, no `set_project_status` |
| 9 | GraphQL: tipo/input/resolver reales | 🟠 Importante | `ProjectInput` es compartido create/update |
| 10 | Convención de columnas de texto | 🟡 Menor | `default=""` en vez de `null=True` |
| 11 | Notificación al estancar (Decisión 4 vs TODO) | 🟡 Menor | Descope o builder+provider nuevos |

Lo demás del brief (modales, copy verbatim, orden de fases, fix de `last_activity` en `update_task`/`delete_task`, índice de stalled, migración aditiva) **es correcto y se mantiene**.

---

## 1. 🔴 El modelo `Activity` no tiene `metadata` ni FK `project`

**Brief (líneas 363-368, 489-499):**
```python
Activity.objects.create(user_id=..., project=project, kind=..., metadata={...})
```

**Realidad** — `core/models.py:370-388`: el modelo tiene `project_id` (UUIDField, **no** FK), `entity_id`, `entity_title`, `target_project_id`, y tres campos de **texto** (`previous_value`, `new_value`, `note`). No existe `metadata` (JSON). Y las actividades se crean con el helper `log_event(...)` (`core/services/activities.py:25`), nunca con `Activity.objects.create` directo:

```python
def log_event(user_id, *, kind, entity_id=None, entity_title="",
              project_id=None, target_project_id=None,
              previous_value="", new_value="", note=""):
```

**Cómo hacerlo bien:**
- La **fuente de verdad** de las closure notes son las columnas nuevas del `Project` (eso del brief está bien). El `Activity` es solo rastro.
- Para el rastro, usar `log_event` y meter el resumen en `note` (texto). Ejemplo de payload:
  ```python
  log_event(
      user_id,
      kind=ActivityKind.PROJECT_STATUS_CHANGED,
      entity_id=project.id,
      entity_title=project.name,
      project_id=project.id,
      previous_value=old_status,
      new_value=project.status,
      note=closure_summary,  # p.ej. "context: …\nnext: …\nblocker: …"  (texto plano)
  )
  ```
- Si se quiere estructura real en el log (no solo texto), eso **sí** requiere una migración para añadir un campo JSON a `Activity` — el brief lo asumía existente y no lo es. Recomendación: **no** añadir JSON; basta `note` + las columnas del Project.

---

## 2. 🔴 Doble logging del cambio de estado

`update_project` **ya** emite `PROJECT_STATUS_CHANGED` cuando cambia el status (`core/services/projects.py:129-138`). El `_log_status_change_activity` que propone el brief (línea 341) crearía una **segunda** entrada por cada transición.

**Cómo hacerlo bien:** extender el bloque de log que ya existe dentro de `update_project` (añadir el `note=` con las closure notes), **no** crear una función/llamada nueva. Una sola entrada por transición.

---

## 3. 🔴 Conservar la firma real de `update_project`

**Brief (líneas 227-242):** invierte el orden a `(project_id, user_id)`, hace `name` opcional y omite `why/next_step/priority/category_id`.

**Realidad** — `core/services/projects.py:95-108`:
```python
def update_project(user_id, project_id, *, name, description="", why="", next_step="",
                   status=None, priority=None, category_id=None,
                   clear_category=False, due_date=None) -> Project:
```
Llamadores que se romperían si se cambia la firma:
- `core/schema.py:993` (resolver `updateProject`)
- `core/assistant/tools/write.py:209` (tool `update_project` de Loop/conector)
- `core/assistant/tools/write.py:264` (`set_project_priority`)

**Cómo hacerlo bien:** mantener orden y `name` requerido; **añadir solo** los kwargs de closure notes al final:
```python
def update_project(user_id, project_id, *, name, description="", why="", next_step="",
                   status=None, priority=None, category_id=None,
                   clear_category=False, due_date=None,
                   # NUEVO — closure notes
                   paused_context=None, paused_next_action=None, paused_blocker=None,
                   killed_reason=None, killed_learnings=None, killed_would_restart=None) -> Project:
```
La lógica de validación/aplicación (`_validate_and_apply_status_transition`) del brief es correcta en concepto; solo debe operar sobre esta firma y guardar en las columnas del Project antes de `project.save()`.

---

## 4. 🔴 Las tareas sin proyecto desaparecerían de Today y de las notificaciones

`Task.project` es **nullable** (`core/models.py:71-73`); las tareas sueltas son un caso soportado (`create_task(project_id=None)`). Un filtro `project__status__in=[...]` hace **INNER JOIN** y las excluye en silencio. En cliente, `t.project.status` (brief línea 853) revienta cuando la tarea no tiene proyecto.

**Cómo hacerlo bien (backend, p.ej. `list_tasks` / builders):**
```python
from django.db.models import Q

qs = qs.filter(Q(project__isnull=True) | Q(project__status__in=DAILY_VIEW_PROJECT_STATUSES))
```

**Cliente (web y móvil):** resolver el proyecto de forma defensiva y **incluir** las tareas sin proyecto:
```ts
const isDailyVisible = (t: Task) => {
  if (!t.projectId) return true; // tarea suelta: siempre visible
  const p = projects.find((x) => x.id === t.projectId);
  return !p || DAILY_VIEW_PROJECT_STATUSES.includes(p.status);
};
```
> Decisión a confirmar: ¿las tareas sin proyecto deben verse siempre en Today? Por defecto **sí** (no pertenecen a ningún estado cerrado). Si la respuesta fuese "no", invertir el primer `return`.

---

## 5. 🟠 El Today de web y móvil NO pasa por `list_tasks`

Esto es central para tu requisito de "web y móvil".

- El Today de ambos clientes consume la query monolítica **`dashboard`** (`core/schema.py:765-797`), que devuelve **todos** los proyectos y tareas sin filtrar, y filtra en cliente (`useTodayFocus.ts`).
- `list_tasks` (`core/services/tasks.py:18`) **solo** lo usa el tool de IA (`core/assistant/tools/read.py:149` y `:228`).

**Implicación:** el cambio `list_tasks(daily_view=True)` del brief **no toca** el Today real — solo afecta a **Loop y al conector** (lo cual igual queremos, ver §8). El filtrado de las vistas diarias de los clientes debe vivir en los dos `useTodayFocus` (el brief sí lo incluye en la sección frontend, líneas 851-857) y replicarse en móvil.

**Plan correcto de filtrado diario:**
1. **Backend (canal IA):** `list_tasks` gana el filtro con el fix de tareas-sin-proyecto de §4. Sirve a Loop y al conector.
2. **Web:** filtrar en `frontend/src/hooks/useTodayFocus.ts` (focus list + `todayTaskCounts` + `todayEffortHours`).
3. **Móvil:** mismo filtro en `mobile/src/hooks/useTodayFocus.ts`.
4. **Notificaciones:** filtro en `core/notifications/builders.py` (ver §7 para la ruta correcta del archivo).
5. Definir la constante una sola vez en backend y **espejarla** en un `frontend/src/lib/projectStatus.ts` y `mobile/src/lib/projectStatus.ts` (no hay codegen de tipos; hoy las uniones se mantienen a mano).

> Nota: el brief apunta el filtro de notificaciones a `core/services/builders.py` (línea 421). Ese archivo no existe — es **`core/notifications/builders.py`** (la línea 201 del snippet sí corresponde a este archivo).

---

## 6. 🟠 Excluir `launched` de las vistas diarias elimina una feature existente

Hoy Today tiene una sección **"Launched with tasks"** (`useTodayFocus`, sección `launched-with-tasks`). El brief (DoD #5 línea 1019; checklist línea 902) excluye `launched` de las vistas diarias → esa sección dejaría de poblarse.

**Acción:** decisión de producto explícita. Dos opciones limpias:
- (a) `DAILY_VIEW_PROJECT_STATUSES = [active, idea]` y **eliminar** la sección "Launched with tasks" (coherente con el brief).
- (b) Mantener `launched` visible solo en su sección dedicada pero **no** en el focus de tareas overdue/today. Requiere que el filtro distinga "focus de tareas" de "secciones de proyecto".

El brief no reconoce este choque; hay que elegir antes de implementar.

---

## 7. 🟠 "Borrar sleeping": inventario real (es más que 4 sitios)

Además de `summary.py`, `analytics.py` y los 2 hooks que lista el brief, "sleeping" vive en:

| Lugar | Referencia | Qué pasa si no se toca |
|---|---|---|
| Dataclass `DashboardSummary` | `core/services/summary.py:15-27` (campo `sleeping_projects`) | Campo huérfano / consumidores rotos |
| Tool IA `_get_dashboard_summary` | `core/assistant/tools/read.py` (devuelve `sleeping_projects`) | Cambia el contrato del **conector/Loop** |
| Digest semanal | `core/notifications/builders.py:87-91` + `_sleeping_projects` en `core/analytics.py:465` | El email semanal sigue hablando de "sleeping" |
| Prompt del assistant | `core/assistant/prompts.py:44`, `:87`, `:209` (`days_idle`) | Loop sigue mencionando "sleeping" |

**Cómo hacerlo bien:** al persistir `stalled`, renombrar el contrato a `stalled_projects` de forma **consistente** en summary dataclass + read tool + digest + prompts, no solo en summary/analytics. Mantener `days_idle` (sigue siendo útil para el modal y para Loop) aunque ya no derive el estado.

---

## 8. 🟠 Loop (IA in-app) + conector de Claude — cobertura real

**Hecho clave:** Loop y el conector **comparten los mismos tools** (`core/assistant/tools/{read,write}.py`). Tocar ahí cubre ambos canales. Pero el brief asume un `set_project_status` que **no existe**.

### 8.1 El tool real es `update_project`
`core/assistant/tools/write.py:165-228`, con `input_schema` JSON y enum `_STATUS` (`write.py:40`). Para que Loop/conector puedan pausar/matar con notas:
1. Añadir `"killed"` a `_STATUS` (`write.py:40`).
2. Añadir al `input_schema` del tool las 6 propiedades de closure notes (`paused_context`, `paused_next_action`, `paused_blocker`, `killed_reason`, `killed_learnings`, `killed_would_restart`) como `{"type": "string"}`.
3. En `_update_project`, pasarlas a `projects_svc.update_project(...)` (respetando el patrón de preservación de campos existente).

### 8.2 Segundo enum de status que el brief omite
`core/assistant/tools/read.py:87` (`list_projects`) tiene su **propio** enum inline `["idea","active","stalled","paused","launched","archived"]`. Hay que añadir `"killed"` ahí también.

### 8.3 Exponer las closure notes en lectura (para que el conector las "vea")
Hoy `_list_projects`/`_get_project` (`read.py`) devuelven `status`, `days_idle`, etc. Añadir al output de lectura (al menos en `get_project`): `paused_context`, `paused_next_action`, `paused_blocker`, `killed_reason`, `killed_learnings`, `killed_would_restart`, `paused_at`, `killed_at`, `stalled_at`. Sin esto, el "AI Resume Context" no tiene de dónde leer por el conector.

### 8.4 Surface del error de validación al modelo
`_update_project` hoy solo captura `NotFoundError` y devuelve `{"error": …}`; cualquier otra excepción se propaga. La `ValidationError` de "faltan closure notes" debe convertirse en un `{"error": "Pausing requires paused_context y paused_next_action …"}` para que Loop **pida los datos al usuario** en vez de fallar. Capturarla explícitamente en el tool.

### 8.5 Doble capa de permisos (no romper el conector)
Existen **dos** gates independientes:
- `plan_required` en el decorador del tool (`update_project` es `plan_required="pro"`).
- `core/mcp/policy.py` (`MCP_TOOL_POLICY`): el conector solo permite writes en `pro/studio/admin`; `free/basic` solo `set_project_priority`.

No hay que cambiar `policy.py`, pero **sí reconocer** que pausar/matar por el conector es **pro+**. El `set_project_priority` (narrow tool) no cambia status, así que no entra en este flujo.

### 8.6 System prompt
El texto que el brief manda actualizar (líneas 603-613) vive en `core/assistant/prompts.py` — el **mismo** archivo del punto §7. En un solo PR de prompt: (a) añadir las reglas de pausar/matar con notas, y (b) reconciliar "stalled vs sleeping".

---

## 9. 🟠 GraphQL: tipos, input y resolver reales

**Tipo `Project`** — `core/schema.py:110-138`: es una clase Strawberry con método `from_model`. Hay que añadir los campos nuevos **y** mapearlos en `from_model` (el brief solo muestra los campos):
```python
# en class Project:
paused_context: Optional[str] = None
paused_next_action: Optional[str] = None
paused_blocker: Optional[str] = None
paused_at: Optional[dt.datetime] = None
killed_reason: Optional[str] = None
killed_learnings: Optional[str] = None
killed_would_restart: Optional[str] = None
killed_at: Optional[dt.datetime] = None
stalled_at: Optional[dt.datetime] = None
# y en from_model(...): paused_context=m.paused_context, … (mapear todos)
```

**Input** — `core/schema.py:443` define un **único** `ProjectInput` **compartido** por create y update. Si se le añaden las closure notes, también las acepta `createProject` (inofensivo, se ignoran). Alternativa: crear un `ProjectUpdateInput` separado. Recomendación: reutilizar `ProjectInput` (menos superficie) y validar en el servicio.

**Resolver `updateProject`** — `core/schema.py:993-1012`: ojo con el quirk existente `clear_category=data.category_id is None` (hoy borra la categoría si no se manda). Al pasar las closure notes, mantener ese comportamiento tal cual y solo añadir los nuevos kwargs.

**Código de error GraphQL:** el brief pide un `CLOSURE_NOTES_REQUIRED` (línea 662). Hoy el resolver usa `_not_found(...)` para 404. Hay que añadir un mapeo equivalente: capturar la `ValidationError` del servicio y re-lanzar como error Strawberry con `extensions={"code": "CLOSURE_NOTES_REQUIRED"}`, siguiendo el patrón de `QUOTA_EXCEEDED` que ya existe para `EntityQuotaExceeded`.

---

## 10. 🟡 Convención de columnas de texto

El brief usa `models.TextField(blank=True, null=True, max_length=…)`. La convención del codebase para texto es `TextField(blank=True, default="")` (ver todos los TextField en `core/models.py`, p.ej. `description`, `why`, `next_step`). Mezclar `null=True` crea estados "NULL vs ''" inconsistentes.

**Recomendación:**
- Texto: `models.TextField(blank=True, default="")` (sin `null=True`). Para distinguir "nunca pausado" usar el timestamp `paused_at IS NULL`, no el texto.
- Si se quiere límite duro de longitud, el codebase usa `CharField(max_length=…)` para campos acotados; `max_length` en `TextField` no se valida a nivel BD. Para 200/300 chars, `CharField` es más fiel a la convención.
- Timestamps (`paused_at`, `killed_at`, `stalled_at`): `DateTimeField(null=True, blank=True)` ✅ (ahí sí null es correcto).

---

## 11. 🟡 Notificación al pasar a `stalled` (Decisión 4 vs. código)

La Decisión 4 (línea 61) dice que el usuario "es notificado (Telegram)" al estancarse, pero el código del brief deja la notificación como `TODO` (líneas 501-502). El sistema actual (`core/notifications/`) está construido para **digests/recordatorios** con dedupe por `NotificationStatus` (`dispatcher.py`), no para eventos ad-hoc.

**Dos caminos (elegir):**
- (a) **Descope a in-app:** el aviso de estancado es el `StalledProjectModal` en el dashboard (ya en el brief). Telegram queda fuera de esta entrega. Más simple y coherente con lo que existe.
- (b) **Implementar push de evento:** nuevo builder + llamada a provider (`core/notifications/providers/`) + entrada de dedupe. Es trabajo extra real, no un TODO trivial.

Recomendación: (a) para esta entrega; (b) como ticket separado.

---

## 12. Confirmaciones que el brief acierta (no cambiar)

- **Migración del enum es segura:** no hay `CHECK` constraint en BD (el status es varchar con `choices`), así que añadir `killed` no necesita SQL de datos. El caveat de la línea 93 es inocuo aquí.
- **Fix de `last_activity`** en `update_task`/`delete_task` (líneas 191-205): correcto, coincide con el gap del audit (`core/services/tasks.py:82-116` hoy no hace touch). Mantener.
- **Índice** `['user_id','status','last_activity']`: útil. (Para el barrido global del cron sin `user_id`, un índice `['status','last_activity']` sería marginalmente mejor, pero no es crítico.)
- **Modales, copy verbatim, brand voice, orden de fases:** sin cambios.

---

## 13. Checklist de archivos corregido (lo que el brief no enumera bien)

**Backend**
- `core/models.py` — enum `KILLED` + columnas closure + timestamps (texto con `default=""`).
- `core/migrations/00XX_*` — aditiva (campos + índice). Sin SQL de enum.
- `core/services/projects.py` — `update_project` (firma real + validación + `log_event` extendido, sin doble log).
- `core/services/tasks.py` — filtro daily con tareas-sin-proyecto (canal IA) + `last_activity` en update/delete.
- `core/services/stalled.py` (nuevo) + `core/management/commands/detect_stalled_projects.py` — usar `log_event`, no `Activity.objects.create`.
- `core/services/summary.py` — `DashboardSummary.sleeping_projects` → `stalled_projects`.
- `core/analytics.py` — quitar derivación sleeping; usar `status=stalled`.
- `core/notifications/builders.py` — filtro daily (ruta real; **no** `core/services/builders.py`) + sección semanal.
- `core/assistant/tools/write.py` — `_STATUS` += killed; `input_schema` de `update_project` += closure notes; surface de error.
- `core/assistant/tools/read.py` — enum `list_projects` (`:87`) += killed; output de closure notes; `_get_dashboard_summary` sleeping→stalled.
- `core/assistant/prompts.py` — reglas pausar/matar + reconciliar stalled/sleeping.
- `core/schema.py` — tipo `Project` (+`from_model`), `ProjectInput`, resolver `updateProject`, error `CLOSURE_NOTES_REQUIRED`.
- `core/mcp/policy.py` — **sin cambios** (solo verificar: pausar/matar = pro+).
- `render.yaml` — append `&& python manage.py detect_stalled_projects` al cron horario (`render.yaml:55`).

**Web** (`frontend/`)
- `src/lib/types.ts` — union += `killed`.
- `src/lib/status.ts` — entrada `killed`; usar como única fuente; selector += killed/stalled.
- `src/components/dashboard/analytics/StatusBreakdownPanel.tsx` — borrar mapa de color duplicado.
- `src/hooks/useTodayFocus.ts` — quitar sleeping derivado; filtro daily (con tareas-sin-proyecto).
- Modales nuevos: `PauseProjectModal`, `KillProjectModal`, `StalledProjectModal`, `WelcomeBackCard`, `ProjectClosureNotes`.
- `src/lib/projectStatus.ts` (nuevo) — espejo de `DAILY_VIEW_PROJECT_STATUSES`.

**Móvil** (`mobile/`)
- `src/lib/types.ts` — union += `killed`.
- `src/lib/status.ts` — **conectar a render real** (hoy es dead code); += killed.
- `src/app/project/[id].tsx:185-189` — badge real desde `status.ts`.
- `src/hooks/useTodayFocus.ts` — quitar sleeping; filtro daily (con tareas-sin-proyecto).
- `src/app/(modals)/project-form.tsx` — selector += killed (y stalled si aplica).
- Mismos 4 modales + `WelcomeBackCard` (copy idéntico al de web).
- `src/lib/projectStatus.ts` (nuevo) — espejo.

---

## 14. Decisiones abiertas (necesitan tu confirmación)

1. **`launched` en Today:** ¿se elimina la sección "Launched with tasks" (opción a) o se mantiene la sección pero se saca del focus de tareas (opción b)? — §6.
2. **Tareas sin proyecto en Today:** ¿siempre visibles (default propuesto) o también se ocultan? — §4.
3. **Notificación de estancado:** ¿in-app only en esta entrega (recomendado) o push de Telegram desde ya? — §11.
4. **Log estructurado:** ¿basta con `note` (texto) en `Activity` o quieres un campo JSON nuevo (migración extra)? — §1.
5. **`killed` y el tier cap:** la Decisión 3 hace que `killed` cuente contra el tope Free (3). ¿Intencional que un proyecto "muerto" siga ocupando slot salvo que además se archive? — coherente con el código (`quotas.py:131` excluye solo `archived`), pero conviene confirmarlo.
6. **`idea` ociosa:** no se auto-estanca (Decisión 4 solo estanca `active`) pero entra en las vistas diarias → puede flotar indefinidamente. ¿Aceptable o las ideas ociosas también deberían salir de Today?

---

*Fin del addendum. No se modificó código; solo se corrigieron los supuestos técnicos del brief y se añadió la cobertura de web/móvil y de Loop + conector.*

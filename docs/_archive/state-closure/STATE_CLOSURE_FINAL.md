# Project State Closure System — Brief definitivo

> **🗄️ ARCHIVADO (2026-06-28).** Documento de diseño histórico. La feature está implementada
> y la referencia técnica vigente (verificada contra el código) es
> [`docs/state-closure.md`](../../state-closure.md). Este brief se
> conserva solo como registro del diseño original; su tono prescriptivo ("por construir") **no**
> refleja el estado actual. Donde el texto diga "no implementado", prevalece el código.

> **⚑ ESTADO (actualizado 2026-06-26): IMPLEMENTADO.** Esta feature ya está en el código,
> no solo diseñada. En backend: estados `killed`/`stalled` en `ProjectStatus`
> (`core/models.py`), notas de cierre en `Project`, servicios `core/services/projects.py`,
> `core/services/stalled.py` y la **autopsia IA** `core/services/autopsy.py`, modelo
> `GraveyardInsight` + query `graveyardInsight` (`core/schema.py`), y el cron
> `core/management/commands/detect_stalled_projects.py`. Está presente en web y móvil. Este
> documento se conserva como el **registro de diseño original**; donde el texto diga "no
> implementado / por construir", prevalece el código.

> Documento único y final. Consolida: el audit (`AUDIT.md`), el addendum correctivo (`STATE_CLOSURE_BRIEF_ADDENDUM.md`), el brief final de Downloads, y todas las decisiones tomadas en revisión (graveyard, revive, autopsia cacheada, killed fuera del cap). **Todos los snippets están alineados con las firmas/modelos reales del código.** Cubre web + móvil + Loop (IA in-app) + conector de Claude.
>
> Filosofía: "Paused with intention. Killed with intention. Never drifting."

---

## 0. Estado y fuentes

- Backend: Django + Strawberry GraphQL (`backend/`). Auth Supabase JWT.
- Clientes: web Next.js (`frontend/`), móvil Expo/React Native (`mobile/`). **No hay codegen de tipos** — las uniones TS se mantienen a mano.
- Loop (IA in-app, `core/assistant`) y el conector MCP (`core/mcp`) **comparten** los tools en `core/assistant/tools/`. Doble gating: `plan_required` (assistant) + `core/mcp/policy.py` (conector).
- La vista Today de los clientes se nutre de la query monolítica `dashboard` (`core/schema.py:765`) y **filtra en cliente**; `list_tasks` (servicio) solo lo usa la IA.

---

## 0.1 Garantías de seguridad de datos (usuarios existentes en producción)

Contexto: la BD es **Postgres de Supabase compartida** por todos los usuarios; el despliegue es **sin downtime**. Esta feature **no debe alterar, perder ni invalidar** datos ya cargados. Reglas vinculantes:

1. **Migración additive-only y reversible.** Solo `AddField` / `AddIndex` / `CreateModel`. Prohibido `RunPython` destructivo, `RemoveField` y cualquier `AlterField` que reescriba datos. El `AlterField` del enum (añadir `killed`) es **cosmético** en Postgres (los `choices` no se enforce en BD). La migración debe tener `reverse` limpio.
2. **Backfill nulo — no se tocan filas viejas.** Columnas nuevas con `default=""` (texto) o `null=True` (timestamps): Postgres las añade con default **sin reescribir filas** (no hay `UPDATE` masivo). Las filas existentes quedan válidas: `status` sin cambios, notas vacías, timestamps en `NULL`.
3. **Ningún proyecto existente cambia de estado por la migración.** La migración no toca `status`. La única transición automática es el cron de stalled, **hacia adelante**, solo sobre `active` con >14d — comportamiento de producto deseado, no efecto de la migración.
4. **Cero downtime — orden de despliegue estricto:**
   - (a) Migración (columnas/tablas/índices): compatible hacia atrás, el backend viejo las ignora.
   - (b) Backend que **lee** las columnas de forma opcional y expone los alias nuevos **manteniendo los `sleeping*` deprecated** (Fase A expand, §6).
   - (c) Recién entonces, clientes que usan lo nuevo.
   - (d) Contract (eliminar deprecated) solo en un release posterior con telemetría de versiones (§6.4 / §15).
5. **Clientes desplegados no se rompen.** Apps móviles ya instaladas siguen pidiendo `sleepingProjects` / `sleepingAlertsEnabled` → se mantienen como alias durante Fase A/B; nada se elimina hasta Fase C.
6. **Preferencias guardadas intactas.** `today_layout` (JSON por usuario) tolera ids desconocidos → quitar `"sleeping"` no corrompe; `sleepingAlertsEnabled` migra con alias preservando el valor del usuario.
7. **Las notas de cierre nunca se borran.** Al volver a active/idea (resume/revive) se limpian **solo timestamps**; `reason`/`learnings`/`context`/`blocker`/`would_restart` y el log de `Activity` se conservan.
8. **Aislamiento por usuario.** Todo query filtra por `user_id` (patrón existente). El cron itera filas pero cada `save` respeta su `user_id`; no hay operación cross-tenant. La autopsia es per-user (`GraveyardInsight` pk=`user_id`).
9. **Rollback por fase:**
   - Migración: reversible (drop de columnas/tabla). Al ser aditiva y sin dependientes aún, el rollback solo perdería notas creadas entre deploy y rollback (aceptable).
   - Backend: revertir al binario anterior es seguro — las columnas extra quedan sin uso.
   - Clientes: degradan bien si el backend revierte (los alias siguen vivos).
   - El cron de stalled es el único con efecto de datos hacia adelante: el rollback no "des-estanca" solo; tener listo un command de reversa opcional.
10. **Pruebas obligatorias antes de producción** (no saltar): correr la migración contra una **branch de la BD de Supabase con datos reales** (MCP `create_branch`); verificar que el **conteo por `status` es idéntico antes/después** y que **ninguna fila cambió de `status`**; smoke test de la query `analytics` con la forma vieja del cliente (alias `sleepingProjects`).

> ⚠️ **Riesgo de "avalancha de stalled" en el primer run del cron.** Hoy `last_activity` no siempre se bumpea (audit §6), así que muchos proyectos `active` históricos tienen `last_activity` > 14d. El primer run marcaría a **todos** como stalled de golpe → avalancha de modales el día 1. **Decidir antes de activar el cron** una de dos mitigaciones: (a) **grace period** — en el deploy, `UPDATE` único de `last_activity = now()` para proyectos `active` (les da 14 días limpios), o (b) **fecha de corte** en el cron durante las primeras 2 semanas. Esto es lo único de esta entrega que tocaría datos existentes a propósito; debe ser una decisión consciente. (Pregunta abierta en §16.)

---

## 1. Decisiones finales (consolidadas)

| # | Decisión | Detalle |
|---|---|---|
| D1 | Nuevo estado `killed` | Distinto de `archived`. killed = "decidí que está muerto, aprende"; archived = neutral/guardado. |
| D2 | Notas de cierre obligatorias | `paused`: context + next_action (blocker opcional). `killed`: reason + learnings (would_restart opcional). `launched`/`archived`: opcionales. `active`/`idea`: N/A. |
| D3 | Cap del plan | Excluir **killed Y archived**. Cuentan: idea/active/stalled/paused/launched. (paused sigue contando: pausa = compromiso vivo). |
| D4 | Stalled real a 14 días | Cron horario marca `active → stalled` con `last_activity` > 14d. **Solo active** (idea no se auto-estanca, D9). Aviso in-app (modal), sin push de Telegram en esta entrega. |
| D5 | Today incluye launched | `DAILY_VIEW_PROJECT_STATUSES = [active, idea, launched]`. Conserva "Launched with tasks". |
| D6 | Tareas sin proyecto siempre visibles | `Task.project` es nullable; nunca filtrarlas por estado. |
| D7 | Consolidar sleeping → stalled | Borrar el derivado "sleeping" en todos los sitios (ver §6, ~14 sitios + 2 contratos persistidos). |
| D8 | Activity vía `log_event` | El modelo `Activity` **no** tiene JSON; usar el campo de texto `note`. Una sola entrada por transición. |
| D9 | Ideas no se auto-estancan | Compromisos ligeros. Mantener badge "idle (N días)" suave en ProjectsView para active+idea (pista visual, **sin** estado). |
| D10 | Graveyard | Vista read-only de `killed` con notas. Solo killed (no archived). |
| D11 | Revive | `killed → active` o `idea` (idea = re-validar). Pasa por el cap. Limpia `killed_at`, conserva notas en historial. |
| D12 | Autopsia IA: computar al escribir | Capa A (reflexión por proyecto): 1 llamada al matar, guardada, best-effort (nunca bloquea el kill). Capa B (patrón): se recomputa solo al morir otro proyecto, umbral **3 muertes**, cacheada por usuario. Única llamada on-demand: "Ask Loop to go deeper". Probablemente Pro+. |

---

## 2. Modelo de estados + iconografía

Siete estados. Color = significado (1 ramp por estado). Iconos: la web/móvil usan **lucide-react / lucide-react-native** (es lo que ya hay en `frontend/src/lib/status.ts`); el wireframe usó **Tabler** equivalentes. Documento ambos.

| Estado | Significado | Cuenta cap | Color (ramp 50 fill / 800 text) | Icono lucide | Icono Tabler (wireframe) |
|---|---|---|---|---|---|
| `idea` | Captura ligera | ✅ | purple `#EEEDFE` / `#3C3489` | `Lightbulb` | `ti-bulb` |
| `active` | En curso | ✅ | green `#EAF3DE` / `#27500A` | `Zap` | `ti-bolt` |
| `stalled` | Estancado (auto 14d) | ✅ | amber `#FAEEDA` / `#633806` | `AlertCircle` | `ti-alert-triangle` |
| `paused` | En pausa intencional | ✅ | gray `#F1EFE8` / `#444441` | `Pause` | `ti-player-pause` |
| `launched` | Lanzado/enviado | ✅ | blue `#E6F1FB` / `#0C447C` | `Rocket` | `ti-rocket` |
| `killed` | Muerto con intención | ❌ | red `#FCEBEB` / `#791F1F` | `Skull` | `ti-skull` |
| `archived` | Guardado, neutral | ❌ | gray `#F1EFE8` / `#5F5E5A` | `Archive` | `ti-archive` |

Iconos de acción / UI (para los nuevos componentes):

| Uso | lucide | Tabler |
|---|---|---|
| Revive (resucitar) | `HeartPulse` (o `RotateCcw`) | `ti-heartbeat` |
| Acceso a Graveyard (nav) | `Skull` | `ti-grave-2` |
| Autopsia IA / insight de Loop | `Sparkles` | `ti-sparkles` |
| "Would restart" badge | `RefreshCw` | `ti-refresh` |
| Tarea sin proyecto (standalone) | `Flag` | `ti-flag` |
| Cuenta contra el cap / no cuenta | `Coins` / `CircleSlash` | `ti-coin` / `ti-coin-off` |
| Transición (A → B) | `ArrowRight` | `ti-arrow-right` |
| Welcome back | `Undo2` (o `ArrowBigLeft`) | `ti-arrow-back-up` |
| Éxito | `Check` | `ti-check` |
| Error de validación | `AlertCircle` | `ti-alert-circle` |
| Visible / oculto en Today | `Eye` / `EyeOff` | `ti-eye` / `ti-eye-off` |
| Reactivar / keep active | `Zap` | `ti-bolt` |

Regla de color de texto: sobre fill de color, usar el stop 800/900 de la **misma** ramp (nunca negro/gris genérico). Modo oscuro: fill 800 + texto 100. Web ya tiene esto en `status.ts`; **eliminar** el mapa divergente de `StatusBreakdownPanel.tsx:18-25` y usar `status.ts` como única fuente.

---

## 3. Cambios de base de datos

Convención del repo: texto = `TextField(blank=True, default="")` (NO `null=True`); para longitud dura usar `CharField`; timestamps nullable = `DateTimeField(null=True, blank=True)`.

### 3.1 `core/models.py` — enum + columnas

```python
class ProjectStatus(models.TextChoices):
    IDEA = "idea", "Idea"
    ACTIVE = "active", "Active"
    STALLED = "stalled", "Stalled"
    PAUSED = "paused", "Paused"
    LAUNCHED = "launched", "Launched"
    KILLED = "killed", "Killed"        # NUEVO
    ARCHIVED = "archived", "Archived"


class Project(TimestampedModel):
    # ... campos existentes ...

    # Cierre — paused
    paused_context = models.CharField(blank=True, default="", max_length=200)
    paused_next_action = models.CharField(blank=True, default="", max_length=200)
    paused_blocker = models.CharField(blank=True, default="", max_length=300)
    paused_at = models.DateTimeField(null=True, blank=True)

    # Cierre — killed
    killed_reason = models.CharField(blank=True, default="", max_length=300)
    killed_learnings = models.CharField(blank=True, default="", max_length=300)
    killed_would_restart = models.CharField(blank=True, default="", max_length=200)
    killed_at = models.DateTimeField(null=True, blank=True)
    killed_ai_reflection = models.TextField(blank=True, default="")  # Capa A (D12)

    # Stalled auto (D4)
    stalled_at = models.DateTimeField(null=True, blank=True)
```

Singleton por usuario para el patrón del graveyard (Capa B, D12) — patrón consistente con `BackupMeta`/`Profile`:

```python
class GraveyardInsight(models.Model):
    user_id = models.UUIDField(primary_key=True)
    body = models.TextField(blank=True, default="")
    deaths_count = models.PositiveIntegerField(default=0)
    computed_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)   # revive lo marca stale
    updated_at = models.DateTimeField(auto_now=True)
```

### 3.2 Migración (aditiva)

- AddField de las 9 columnas nuevas en `Project` + crear tabla `GraveyardInsight`.
- Índices:
  - `Index(fields=["user_id", "status", "last_activity"], name="idx_project_status_activity")` (filtro daily / listas).
  - `Index(fields=["status", "last_activity"], name="idx_project_stalled_sweep")` (cron global sin user_id).
- **Enum seguro:** no hay CHECK en la BD (`status` es varchar con `choices`), añadir `killed` no requiere SQL de datos (audit §1). Django generará un `AlterField` cosmético.

---

## 4. Backend — capa de servicios

### 4.1 `core/services/projects.py` — `update_project` (firma real preservada)

Firma real hoy (`projects.py:95`): `update_project(user_id, project_id, *, name, description="", why="", next_step="", status=None, priority=None, category_id=None, clear_category=False, due_date=None)`. **Añadir kwargs al final, no reordenar.**

```python
from django.core.exceptions import ValidationError
from django.utils import timezone
from ..models import ActivityKind, Category, Project, ProjectStatus  # ActivityKind vive en ..models
from ..quotas import check_entity_quota
from .activities import iso, log_event

# Estados que aparecen en vistas diarias y notificaciones (D5)
DAILY_VIEW_PROJECT_STATUSES = [
    ProjectStatus.ACTIVE, ProjectStatus.IDEA, ProjectStatus.LAUNCHED,
]
# Estados que cuentan contra el cap (D3)
COUNTING_STATUSES = [
    ProjectStatus.IDEA, ProjectStatus.ACTIVE, ProjectStatus.STALLED,
    ProjectStatus.PAUSED, ProjectStatus.LAUNCHED,
]
NONCOUNTING_STATUSES = [ProjectStatus.KILLED, ProjectStatus.ARCHIVED]


def update_project(user_id, project_id, *, name, description="", why="", next_step="",
                   status=None, priority=None, category_id=None, clear_category=False,
                   due_date=None,
                   # NUEVO (aditivo) — notas de cierre
                   paused_context=None, paused_next_action=None, paused_blocker=None,
                   killed_reason=None, killed_learnings=None, killed_would_restart=None):
    project = get_project(user_id, project_id)   # NOTA: get_project(user_id, project_id), NO get_project_or_raise
    old_status = project.status

    if status and status != old_status:
        _apply_status_transition(
            user_id, project, status,
            paused_context, paused_next_action, paused_blocker,
            killed_reason, killed_learnings, killed_would_restart,
        )

    # ... resto de updates existentes (name/description/why/next_step/priority/category) ...
    # PRESERVAR el quirk: clear_category / category_id, y due_date
    project.last_activity = timezone.now()
    project.save()

    # REEMPLAZA el bloque de log existente (projects.py:129-138) por ESTE (una sola entrada)
    if status and status != old_status:
        log_event(
            user_id, kind=ActivityKind.PROJECT_STATUS_CHANGED,
            entity_id=project.id, entity_title=project.name, project_id=project.id,
            previous_value=old_status, new_value=project.status,
            note=_closure_note_summary(project),
        )
    # ... log de due_date existente se mantiene ...
    return project


def _apply_status_transition(user_id, project, new_status,
                             p_ctx, p_next, p_block, k_reason, k_learn, k_restart):
    # Cap: entrar a un estado que cuenta desde uno que no (killed/archived → vivo) revalida cuota (D11)
    if project.status in NONCOUNTING_STATUSES and new_status in COUNTING_STATUSES:
        check_entity_quota(user_id, "projects")  # lanza EntityQuotaExceeded

    if new_status == ProjectStatus.PAUSED:
        if not (p_ctx or "").strip():
            raise ValidationError("Pausing requires 'paused_context'. Tell future you where you're stopping.")
        if not (p_next or "").strip():
            raise ValidationError("Pausing requires 'paused_next_action'. What's the very next action when you return?")
        project.paused_context = p_ctx.strip()
        project.paused_next_action = p_next.strip()
        project.paused_blocker = (p_block or "").strip()
        project.paused_at = timezone.now()

    elif new_status == ProjectStatus.KILLED:
        if not (k_reason or "").strip():
            raise ValidationError("Killing requires 'killed_reason'. Killing is a form of finishing. It deserves a why.")
        if not (k_learn or "").strip():
            raise ValidationError("Killing requires 'killed_learnings'. What did this project teach you?")
        project.killed_reason = k_reason.strip()
        project.killed_learnings = k_learn.strip()
        project.killed_would_restart = (k_restart or "").strip()
        project.killed_at = timezone.now()

    elif new_status == ProjectStatus.STALLED:
        project.stalled_at = timezone.now()

    elif new_status in (ProjectStatus.ACTIVE, ProjectStatus.IDEA):
        # Resumir / revivir: limpiar timestamps que gatean modales, conservar notas (historial)
        project.paused_at = None
        project.stalled_at = None
        project.killed_at = None  # revive: sale del graveyard

    project.status = new_status


def _closure_note_summary(project) -> str:
    if project.status == ProjectStatus.PAUSED:
        parts = [f"context: {project.paused_context}", f"next: {project.paused_next_action}"]
        if project.paused_blocker:
            parts.append(f"blocker: {project.paused_blocker}")
        return "\n".join(parts)
    if project.status == ProjectStatus.KILLED:
        parts = [f"reason: {project.killed_reason}", f"learnings: {project.killed_learnings}"]
        if project.killed_would_restart:
            parts.append(f"would_restart: {project.killed_would_restart}")
        return "\n".join(parts)
    return ""
```

> **Importante:** la cola de IA (Capa A) NO va aquí en línea. El kill no debe bloquearse por una llamada al modelo (D12). Disparar la reflexión después del commit (señal post-save / tarea), best-effort. Ver §5.

### 4.2 `core/services/tasks.py`

- `list_tasks` (firma real: `list_tasks(user_id, *, project_id=None, done=None, due_within_days=None, limit=50)`) — añadir `daily_view: bool = False` y, cuando sea True, filtrar conservando tareas sueltas:
  ```python
  from django.db.models import Q
  from .projects import DAILY_VIEW_PROJECT_STATUSES
  if daily_view:
      qs = qs.filter(Q(project__isnull=True) | Q(project__status__in=DAILY_VIEW_PROJECT_STATUSES))
  ```
  (Este filtro solo afecta a Loop/conector; el Today de los clientes se filtra en `useTodayFocus`, §9–10.)
- Audit gap: `update_task` y `delete_task` deben llamar `touch_last_activity(user_id, project_id)` (guardando contra `project_id is None`). Hoy solo `create_task`/`toggle_task` lo hacen.

### 4.3 `core/notifications/builders.py` (ruta correcta — NO `core/services/builders.py`)

- En `_daily_context` (≈línea 201) añadir el mismo filtro `Q(project__isnull=True) | Q(project__status__in=DAILY_VIEW_PROJECT_STATUSES)` a la query de `open_tasks`. Aplicar también a digest diario y due reminders.
- Digest semanal (sección sleeping): pasar a `Project.objects.filter(user_id=user_id, status=ProjectStatus.STALLED).order_by("-stalled_at")`.

### 4.4 Stalled detection — `core/services/stalled.py` (nuevo)

```python
from datetime import timedelta
from django.utils import timezone
from ..models import ActivityKind, Project, ProjectStatus
from .activities import log_event

STALLED_THRESHOLD_DAYS = 14  # D4

def detect_and_mark_stalled(user_id=None):
    cutoff = timezone.now() - timedelta(days=STALLED_THRESHOLD_DAYS)
    qs = Project.objects.filter(status=ProjectStatus.ACTIVE, last_activity__lt=cutoff)
    if user_id:
        qs = qs.filter(user_id=user_id)
    changed = list(qs)
    for p in changed:
        prev = p.status
        p.status = ProjectStatus.STALLED
        p.stalled_at = timezone.now()
        p.save(update_fields=["status", "stalled_at"])
        log_event(p.user_id, kind=ActivityKind.PROJECT_STATUS_CHANGED,
                  entity_id=p.id, entity_title=p.name, project_id=p.id,
                  previous_value=prev, new_value=ProjectStatus.STALLED,
                  note=f"auto-detected after {STALLED_THRESHOLD_DAYS} days idle")
    return changed
```

Management command `core/management/commands/detect_stalled_projects.py` que llama `detect_and_mark_stalled()`. Cron: añadir `&& python manage.py detect_stalled_projects` a la cadena horaria de `render.yaml:55`.

---

## 5. Graveyard + Revive + Autopsia IA

### 5.1 Graveyard (vista)
- Datos: `Project.objects.filter(user_id, status=killed).order_by("-killed_at")`. Cada tarjeta muestra: nombre, vida (created→killed_at), `killed_reason`, `killed_learnings`, badge `would_restart` si lo hay, y `killed_ai_reflection` (Capa A) con etiqueta `AI` (icono `Sparkles`). Solo `killed` (no archived, D10).
- Métrica sin culpa: "would restart N of M".
- Acceso: ítem de navegación con icono `Skull` (`ti-grave-2`).

### 5.2 Revive (D11)
- Transición `killed → active | idea` vía `update_project(status=...)`. La cuota se revalida en `_apply_status_transition` (killed→counting); si excede, `QUOTA_EXCEEDED` → el cliente muestra upsell.
- Limpia `killed_at` (sale del graveyard); conserva `killed_reason/learnings/would_restart` (historial + Activity).
- Marca `GraveyardInsight.is_stale = True` (el patrón se recomputa en la próxima muerte o con refresh).
- UI: modal con el `would_restart` surfaced, línea de cap ("2/3 active"), y dos botones: `Active` (icono `Zap`) / `Idea (re-validate)` (icono `Lightbulb`).

### 5.3 Autopsia IA — computar al escribir (D12)
- **Capa A (por proyecto):** al confirmarse el kill (post-commit, best-effort), 1 llamada al modelo con `reason+learnings+would_restart+historial` → guardar en `Project.killed_ai_reflection`. Si falla, el kill sigue válido; regenerable luego. Reverla = leer BD (0 llamadas).
- **Capa B (patrón):** solo si `count(killed) >= 3`. Se recomputa **al morir un proyecto nuevo** (puede ir en la misma llamada que A para abaratar) → sobrescribe `GraveyardInsight` (body, deaths_count, computed_at, is_stale=False). Verla = leer caché.
- **On-demand:** único botón "Ask Loop to go deeper" → `sendPrompt(...)` (chat de Loop, cargado a la quota normal del assistant). El conector también puede hacerlo por chat porque `read.py` expone las notas (§8).
- **Gating:** Capa A+B probablemente Pro+. Free ve sus notas escritas y la lista, sin reflexión IA.

---

## 6. Limpieza de "sleeping" + compatibilidad (§5-bis)

"Sleeping" derivado vive en ~14 sitios + 2 contratos persistidos + ids de preferencias. **No big-bang.**

### 6.1 Contratos persistidos (cuidado: apps móviles desplegadas)
1. GraphQL `sleepingProjects` + `SleepingProjectRow`: backend `schema.py:665,722-729` + `analytics.py:177,223,239,465`; clientes `frontend/src/lib/graphql.ts:1585`, `mobile/src/lib/graphql.ts:1482`.
2. `sleepingAlertsEnabled` (NotificationSettings, toggle guardado): `frontend graphql.ts:286,1484,1510`, `mobile graphql.ts:183,1381,1407`.

### 6.2 Ids de sección Today (en `UserPreferences.today_layout` JSON)
`"sleeping"` y `"stalled-alert"` en `todaySections.ts` (web+móvil) y `preferences.py:28,33`. El modelo **ignora ids desconocidos** (`models.py` docstring), así que quitar `"sleeping"` no corrompe datos.

### 6.3 Lógica derivada (reemplazar por estado persistido `status=stalled`)
- `core/services/summary.py` (`SLEEPING_DAYS`, dataclass `sleeping_projects`→`stalled_projects`).
- `core/analytics.py` (`SLEEPING_THRESHOLD_DAYS`, `_sleeping_projects`).
- `core/assistant/tools/read.py` (`_get_dashboard_summary` key `sleeping_projects`→`stalled_projects`).
- `core/assistant/prompts.py:44,87,209` ("sleeping"→"stalled"; conservar `days_idle` como métrica).
- `frontend useTodayFocus.ts` + `mobile useTodayFocus.ts` (derivado → `status==='stalled'` + filtro daily).
- `frontend useProductivityStats.ts:114` + `mobile useProductivityStats.ts:112`.
- `frontend ProjectsView.tsx` (chip stalled + idleBadge, líneas 136-137,201-202,451-452,508-509,574-576,633) y `mobile projects.tsx:52-53,78-79,90-91`: chip "stalled" = `status==='stalled'`; mantener badge "idle (N días)" separado para active+idea (D9).
- Componentes/i18n: `SleepingStalePanel.tsx`, `AnalyticsView.tsx`/`analytics.tsx`, `QuickActionChips.tsx` (web+móvil), `mobile messages/en.json`+`es.json`, catálogos next-intl (web).

### 6.4 Estrategia expand → migrate → contract
- **Fase A (expand):** añadir `stalledProjects` / `stalledAlertsEnabled` como alias que devuelven el estado real; mantener `sleeping*` deprecated devolviendo lo mismo. Cero roturas.
- **Fase B (migrate):** web+móvil pasan a los nombres nuevos; i18n "Sleeping"→"Stalled"; ProjectsView/projects.tsx usan estado real.
- **Fase C (contract):** tras 1 release y con telemetría de versiones móviles, eliminar `sleeping*` y el código derivado. Verificación: `grep -ri "sleeping" backend frontend mobile` = 0 referencias funcionales.

---

## 7. GraphQL (`core/schema.py`)

- **Tipo `Project`** (110-138): añadir `paused_context/next_action/blocker/paused_at`, `killed_reason/learnings/would_restart/killed_at/killed_ai_reflection`, `stalled_at` (todos `Optional`) y **mapearlos en `from_model`**.
- **`ProjectInput`** (443, compartido create/update): añadir los 6 inputs de notas (`Optional[str] = None`). `createProject` los ignora.
- **Resolver real** `def update_project(self, info, id: strawberry.ID, data: ProjectInput) -> Project` (993): preservar `clear_category=data.category_id is None`; pasar los 6 kwargs nuevos; capturar `ValidationError` y `EntityQuotaExceeded`:
  ```python
  except NotFoundError:
      raise _not_found("Project")
  except EntityQuotaExceeded as e:
      raise _quota_error(e)                  # patrón existente (schema.py:79)
  except ValidationError as e:
      raise _closure_error(e)                # NUEVO helper, mismo patrón
  ```
- Helper nuevo junto a `_quota_error`:
  ```python
  def _closure_error(e):
      return GraphQLError(str(e), extensions={"code": "CLOSURE_NOTES_REQUIRED"})
  ```
- Analytics: ver §6 (renombrar `sleeping_projects`/`SleepingProjectRow` con la estrategia expand→migrate→contract).
- Graveyard: query nueva `graveyard` (o `projects(status: KILLED)`); exponer `GraveyardInsight` como tipo + query `graveyardInsight`.

---

## 8. Tools de IA (Loop + conector) — `core/assistant/tools/`

El tool real es `update_project` (NO `set_project_status`). Las funciones reciben `(user_id, args: dict)`.

### 8.1 `write.py`
- `_STATUS` (línea 40): añadir `"killed"`.
- `input_schema` del tool `update_project` (165-190): añadir propiedades `paused_context/next_action/blocker`, `killed_reason/learnings/would_restart` (`{"type":"string"}`).
- `_update_project` (192): forward de los nuevos args con el patrón de preservación; capturar `ValidationError` y devolver `{"error": str(e)}` para que el modelo pida los datos (hoy solo captura `NotFoundError`).
- Revive: reutiliza `update_project(status="active"|"idea")`. (Opcional: tool estrecho `revive_project` análogo a `set_project_priority`.)

### 8.2 `read.py`
- Enum inline de status en `list_projects` (≈línea 87): añadir `"killed"`.
- Output de `_list_projects` (99) y `_get_project_detail` (142): incluir `paused_*`, `killed_*` (incl. `killed_ai_reflection`), `stalled_at` para que el conector lea el "Resume Context" y la autopsia por chat.
- `_get_dashboard_summary`: `sleeping_projects` → `stalled_projects` (§6).

### 8.3 `prompts.py`
- Añadir reglas: al pausar pedir context+next_action; al matar pedir reason+learnings; no llamar `update_project` con `paused/killed` sin esas; si faltan, preguntar primero.
- "A project untouched for 14 days is auto-marked `stalled` (real state, not derived). Reference 'stalled', never 'sleeping'."

### 8.4 `core/mcp/policy.py` — **no cambiar**, solo verificar
- `update_project` es `plan_required="pro"` → pausar/matar/revivir por conector es Pro+. `MCP_TOOL_POLICY` permite writes solo pro/studio/admin; free/basic solo `set_project_priority`.

---

## 9. Frontend web (`frontend/`)

### 9.1 Tipos y constantes
- `src/lib/types.ts`: union `ProjectStatus` += `'killed'`; añadir campos nuevos al type `Project`.
- `src/lib/projectStatus.ts` (nuevo): `export const DAILY_VIEW_PROJECT_STATUSES = ['active','idea','launched'] as const;` (espejo manual del backend).
- `src/lib/status.ts`: añadir entrada `killed` (color red, icono lucide `Skull`); **eliminar** el mapa de `StatusBreakdownPanel.tsx:18-25`.

### 9.2 Componentes nuevos (`src/components/projects/`)
`PauseProjectModal.tsx`, `KillProjectModal.tsx`, `StalledProjectModal.tsx`, `WelcomeBackCard.tsx`, `ProjectClosureNotes.tsx` (read-only), `GraveyardView.tsx`, `ReviveProjectModal.tsx`, `GraveyardAutopsy.tsx` (insight cacheado + botón "go deeper").

### 9.3 Selectores e hilos
- Selector de estado (detail modal + create/edit form): incluir `killed`. `stalled` se mantiene auto (mostrar con helper "auto-detected at 14 days idle" si se expone).
- `useTodayFocus.ts`: quitar derivado sleeping; filtrar con `DAILY_VIEW_PROJECT_STATUSES` conservando tareas sueltas (`if (!t.projectId) return true;`).
- Manejar el error `CLOSURE_NOTES_REQUIRED` y `QUOTA_EXCEEDED` (revive) con CTA correcta.

### 9.4 Copy verbatim (NO parafrasear; brand voice: sin em-dash, sin jerga, sin AI tells)

PauseProjectModal:
```
Title:    Pausing "[Project Name]"
Subtitle: Before you pause this, write something for the version of you who will come back to it. Three quick prompts. Two minutes total.
F1 label: Where exactly are you stopping?
F1 ph:    e.g., "Finished hero section. Stuck on pricing logic."
F2 label: What's the very next action when you return?
F2 ph:    e.g., "Write the pricing comparison table copy."
F3 label: What's blocking you right now? (optional)
F3 ph:    e.g., "Need to talk to 2 users before deciding on pricing strategy."
Footer:   Why we ask: Future you will not remember this. Past you owes future you a note.
Button:   Pause project
Cancel:   ESC/click outside reverts to previous status (no partial save).
Toast:    Paused. Future you will thank you.
```
KillProjectModal:
```
Title:    Killing "[Project Name]"
Subtitle: Killing is a form of finishing. It deserves a closing ritual.
F1 label: Why are you killing this?
F1 ph:    e.g., "The scope kept growing and I never validated the core assumption."
F2 label: What did you learn from it?
F2 ph:    e.g., "I should have shipped a 1-week MVP before building 5 months of infrastructure."
F3 label: Would you start it again with what you know now? (optional)
F3 ph:    e.g., "Yes, but with a much smaller scope and 2 user interviews first."
Footer:   We save this in your Project Graveyard. Not a tombstone, a library of what didn't work so you don't repeat it.
Button:   Kill with intention
Toast:    Killed with intention. Lesson saved.
```
StalledProjectModal:
```
Title:    You haven't touched "[Project Name]" in [N] days.
Subtitle: What do you want to do with it?
Options:  ○ I'm still working on it (keep Active)
          ○ I need to pause it
          ○ It's dead. Kill it.
Footer:   No drifting. Make the call.
Button:   Make the call
Behavior: keep Active → last_activity=now + status=active; Pause → PauseModal; Kill → KillModal;
          no dismiss sin elegir; uno por proyecto, en cola.
```
WelcomeBackCard:
```
Title:    Welcome back to "[Project Name]"
Subtitle: You paused this [N] days ago.
S1:       Where you stopped:  [paused_context]
S2:       Your next action was:  → [paused_next_action]
S3 (if):  What was blocking you:  [paused_blocker]
CTA:      Ready to pick this back up?
          Btn1: Reactivate project (status → active)
          Btn2: Keep paused (close, read-only)
```
ReviveProjectModal:
```
Title:    Revive "[Project Name]"?
Subtitle: You killed this once, on purpose. Bringing it back is fine. Just go in with what you learned.
Surface:  You said you'd restart it like this: [killed_would_restart]   (si existe)
Cap line: Counts against your plan again — [used] / [cap] active
Choice:   Bring it back as:  [Active]   [Idea (re-validate)]
Tertiary: Leave it dead
```

---

## 10. Frontend móvil (`mobile/`)

Espejo de web, mismo copy verbatim. Notas específicas:
- `src/lib/status.ts` está **muerto** (nunca se importa); activarlo y usarlo en el badge de `src/app/project/[id].tsx:185-189` (hoy pill neutro). Añadir `killed`.
- `src/lib/types.ts`: union += `'killed'` + campos nuevos.
- `src/lib/projectStatus.ts` (nuevo): espejo de `DAILY_VIEW_PROJECT_STATUSES`.
- `src/hooks/useTodayFocus.ts`: misma lógica que web (quitar sleeping, filtro daily, tareas sueltas).
- `src/app/(modals)/project-form.tsx`: selector += `killed`.
- Construir los modales + WelcomeBackCard + Graveyard + Revive (RN). Iconos lucide-react-native equivalentes (§2).
- i18n: actualizar `messages/en.json` y `messages/es.json` (sleeping→stalled; nuevas strings de modales si se localizan — pero D del brief: el copy de modales va en inglés en esta entrega).

---

## 11. Compatibilidad de preferencias e i18n
- `today_layout` (JSON por usuario): quitar `"sleeping"` es seguro (ids desconocidos se ignoran). Decidir si el riel pasa a `"stalled-alert"` existente o un id nuevo; si nuevo, los usuarios lo verán con visibilidad por defecto.
- `sleepingAlertsEnabled`: migrar con alias (Fase A), no romper apps viejas.
- Copy de modales: inglés (no localizar en esta entrega). Sí actualizar labels existentes "Sleeping"→"Stalled" en ambos idiomas.

---

## 12. Testing checklist

Backend:
- [ ] Migración corre limpia; proyectos existentes conservan estado.
- [ ] `update_project` lanza `ValidationError` al ir a paused sin context/next_action; a killed sin reason/learnings.
- [ ] launched/archived sin notas: OK.
- [ ] Timestamps correctos (paused_at/killed_at/stalled_at); al volver a active/idea se limpian (incl. killed_at en revive).
- [ ] Una sola `Activity` por transición (sin doble log); notas en `note`.
- [ ] Callers existentes siguen funcionando: `schema.py:993`, `write.py` `_update_project`, `set_project_priority`.
- [ ] `last_activity` se bumpea en update_task y delete_task (incl. tareas sin proyecto).
- [ ] Cap excluye killed y archived; revive killed→active revalida cuota (QUOTA_EXCEEDED si excede).

Daily/notifs:
- [ ] Today y digest excluyen paused/stalled/killed/archived; incluyen active/idea/launched y tareas sueltas; sin TypeError por tarea sin proyecto.
- [ ] Digest semanal usa `status=stalled`; no menciona "sleeping".

Stalled:
- [ ] Solo active se auto-estanca; idea nunca; umbral 14d; `stalled_at`=now; Activity con nota auto.
- [ ] StalledModal aparece al cargar dashboard; keep-active limpia stalled_at + last_activity.

Graveyard/Revive/IA:
- [ ] Graveyard lista solo killed con notas + reflexión.
- [ ] Reflexión (Capa A) se genera una vez al matar; si la llamada falla, el kill igual queda; reverla no llama API.
- [ ] Patrón (Capa B) solo con ≥3 muertes; se recomputa al morir otro; revive marca stale.
- [ ] Revive → active/idea; conserva notas en historial.

IA tools (Loop + conector):
- [ ] Loop pausa/mata con notas; sin notas devuelve error legible y pide datos.
- [ ] Conector: pausar/matar/revivir solo Pro+; free/basic bloqueado por policy.
- [ ] `list_projects` acepta filtro `killed`; `get_project_detail` expone notas; `_get_dashboard_summary` devuelve `stalled_projects`.

UI:
- [ ] Modales no envían con requeridos vacíos; cancel revierte sin guardar parciales.
- [ ] Badges usan `status.ts` (web y móvil); móvil ya no es pill neutro.
- [ ] No aparece "Sleeping" en UI; `grep -ri sleeping` limpio (tras Fase C).

---

## 13. Orden de implementación (fases)

1. **DB + tipos** — migración (columnas + GraveyardInsight + índices), `models.py`, GraphQL type/input/from_model, tipos TS (web+móvil), `projectStatus.ts`.
2. **Servicios backend** — `update_project` (aditivo + validación + cap en transición + log único), `DAILY_VIEW_*`, `list_tasks(daily_view)`, fix `last_activity`, builders (daily + semanal), resolver + `_closure_error`.
3. **Stalled + cron** — `stalled.py`, command, `render.yaml`.
4. **Sleeping cleanup (Fase A expand)** — alias `stalledProjects`/`stalledAlertsEnabled`, mantener deprecated.
5. **IA tools** — `write.py` (_STATUS + schema + forward + error), `read.py` (enum + output + summary rename), `prompts.py`; verificar `policy.py`.
6. **Graveyard + Revive + Autopsia** — queries, vista, revive modal, Capa A/B (post-commit, cacheada), gating Pro+.
7. **Web frontend** — modales + WelcomeBack + Graveyard + Revive, status.ts (+killed), selectores, useTodayFocus, manejo de errores.
8. **Móvil frontend** — espejo; activar status.ts; badge; selectores; useTodayFocus; i18n.
9. **Sleeping cleanup (Fase B migrate)** — clientes a nombres nuevos; ProjectsView/projects.tsx; useProductivityStats; paneles; i18n.
10. **QA + Fase C contract** — checklist; eliminar `sleeping*` deprecated; grep limpio; QA pause→resume y kill→graveyard→revive en web y móvil; flujo de Loop.

---

## 14. Lista de "NO hacer"

- NO hacer opcionales las notas en paused/killed.
- NO contar killed ni archived en el cap (D3); NO cambiar que paused cuente.
- NO borrar las notas al volver a active/idea (conservar historial); solo limpiar timestamps.
- NO mostrar tareas de paused/stalled/killed/archived en Today ni notificaciones.
- NO filtrar tareas sin proyecto (siempre visibles).
- NO excluir launched de las vistas diarias (D5).
- NO bloquear el kill por la llamada de IA (best-effort, post-commit).
- NO llamar al API por cada consulta de motivos: computar al escribir, cachear (D12).
- NO añadir JSON a `Activity`; usar `note`. Una sola entrada por transición.
- NO reordenar la firma de `update_project`; solo kwargs aditivos.
- NO usar `null=True` en columnas de texto (`default=""`).
- NO usar `core/services/builders.py` (es `core/notifications/builders.py`).
- NO llamar `set_project_status` (es `update_project`) ni `get_project_or_raise` (es `get_project`).
- NO importar `ActivityKind` de `core.activities` (vive en `core.models` / `..models`).
- NO eliminar `sleepingProjects`/`sleepingAlertsEnabled` de golpe (romper apps móviles): expand→migrate→contract.
- NO auto-estancar `idea` (solo active).
- NO parafrasear el copy de usuario.

---

## 15. Definition of done

1. `killed` existe en BD, GraphQL, ambos clientes y tools de IA.
2. Pausar exige context + next_action; matar exige reason + learnings (validado en servicio → `CLOSURE_NOTES_REQUIRED`).
3. Active >14d idle → stalled vía cron horario (solo active); modal in-app al cargar.
4. Today (web+móvil) y digest excluyen paused/stalled/killed/archived; incluyen active/idea/launched y tareas sueltas.
5. Cap excluye killed y archived; revive revalida cuota.
6. WelcomeBackCard muestra notas al reabrir paused; StalledModal en carga; Graveyard lista killed con reflexión IA.
7. Revive (active/idea) funciona y conserva historial.
8. Autopsia: Capa A 1 llamada al matar (best-effort), Capa B umbral 3 + cacheada; revisar no llama API.
9. Loop y conector honran las notas; conector pro-gated.
10. Sleeping eliminado tras Fase C; `grep` limpio; móvil con badge real.
11. QA manual: pause→resume, kill→graveyard→revive, flujo de Loop, en web y móvil.

---

## 16. Decisiones confirmadas vs. abiertas

Confirmadas: D1–D12 (todas arriba).

Abiertas (no bloquean el arranque):
- Revive: destino por defecto sugerido en UI (Active vs Idea) — el wireframe ofrece ambos sin default fuerte.
- Cola de StalledModal: uno-a-uno (decidido) vs lista única si hay muchos — revisar si N es alto.
- Autopsia: arrancar como capacidad de Loop por chat (recomendado) y dejar el panel cacheado para después, o ambos desde el día 1.
- Id de sección del riel en Today tras quitar "sleeping" (reusar "stalled-alert" vs nuevo).
- ~~**Mitigación de avalancha de stalled en el primer run del cron (§0.1):** grace period vs. fecha de corte.~~ **RESUELTO: cutoff auto-stamped.** `StalledSweepState` (singleton) graba `cutoff_at` en el primer run; el cron mide ociosidad desde `max(last_activity, cutoff)` → no estanca nada hasta 14 días después del lanzamiento, sin tocar datos ni env. (migración 0025)

---

*Fin del brief definitivo. Pendiente solo de la orden de implementar; no se ha tocado código.*

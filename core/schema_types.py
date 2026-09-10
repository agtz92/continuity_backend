"""Tipos e inputs GraphQL (Strawberry) de core.

Extraídos de schema.py (ver AUDITORIA_CODIGO.md). Solo definiciones de
tipos/inputs + sus conversores `from_model`; sin resolvers, servicios ni helpers,
para no acoplarse con schema.py (que los re-importa con `import *`).
"""

import datetime as dt
import uuid  # noqa: F401  (usado por algunos from_model)
from typing import Optional, List

import strawberry
from strawberry.types import Info

from . import analytics as analytics_mod
from .services import cooling as cooling_svc
from .analytics import AnalyticsRange as AnalyticsRangeEnum

from .models import (
    Activity as ActivityModel,
    Project as ProjectModel,
    ProjectNote as ProjectNoteModel,
    Task as TaskModel,
    TaskBlocker as TaskBlockerModel,
    Idea as IdeaModel,
    BackupMeta,
    GraveyardInsight as GraveyardInsightModel,
    Category as CategoryModel,
    NoteSection as NoteSectionModel,
    OnboardingProgress as OnboardingProgressModel,
    Profile as ProfileModel,
    QuickNote as QuickNoteModel,
    Routine as RoutineModel,
    RoutineOccurrence as RoutineOccurrenceModel,
)

# Enum de rango temporal de analítica (vive junto a los tipos que lo usan).
AnalyticsRange = strawberry.enum(AnalyticsRangeEnum, name="AnalyticsRange")


@strawberry.type
class Category:
    id: strawberry.ID
    name: str
    color: str
    created: dt.datetime

    @classmethod
    def from_model(cls, m: CategoryModel) -> "Category":
        return cls(
            id=strawberry.ID(str(m.id)),
            name=m.name,
            color=m.color,
            created=m.created,
        )


@strawberry.type
class Project:
    id: strawberry.ID
    name: str
    description: str
    why: str
    next_step: str
    status: str
    priority: str
    category_id: Optional[strawberry.ID]
    last_activity: dt.datetime
    created: dt.datetime
    due_date: Optional[dt.datetime] = None
    paused_context: Optional[str] = None
    paused_next_action: Optional[str] = None
    paused_blocker: Optional[str] = None
    paused_at: Optional[dt.datetime] = None
    killed_reason: Optional[str] = None
    killed_learnings: Optional[str] = None
    killed_would_restart: Optional[str] = None
    killed_at: Optional[dt.datetime] = None
    killed_ai_reflection: Optional[str] = None
    stalled_at: Optional[dt.datetime] = None
    position: int = 0
    # Derivados del rediseño (REDISENO_PLAN.md §8). Se calculan en el servidor
    # para que web y móvil no discrepen en los tramos.
    days_since_touch: int = 0
    cooling: str = cooling_svc.WARM
    # "Atorado" no es un estado del modelo: es tener alguna tarea abierta con
    # blocker sin resolver. Solo el dashboard lo puede calcular sin N+1, así que
    # el resto de resolvers lo dejan en None y la UI cae a "no bloqueado".
    blocked_since: Optional[dt.datetime] = None
    is_blocked: bool = False

    @classmethod
    def from_model(
        cls, m: ProjectModel, blocked_since: Optional[dt.datetime] = None
    ) -> "Project":
        days = cooling_svc.days_since_touch(m.last_activity)
        return cls(
            id=strawberry.ID(str(m.id)),
            name=m.name,
            description=m.description,
            why=m.why,
            next_step=m.next_step,
            status=m.status,
            priority=m.priority,
            category_id=strawberry.ID(str(m.category_id)) if m.category_id else None,
            last_activity=m.last_activity,
            created=m.created,
            due_date=m.due_date,
            paused_context=m.paused_context,
            paused_next_action=m.paused_next_action,
            paused_blocker=m.paused_blocker,
            paused_at=m.paused_at,
            killed_reason=m.killed_reason,
            killed_learnings=m.killed_learnings,
            killed_would_restart=m.killed_would_restart,
            killed_at=m.killed_at,
            killed_ai_reflection=m.killed_ai_reflection,
            stalled_at=m.stalled_at,
            position=m.position,
            days_since_touch=days,
            cooling=cooling_svc.cooling(days),
            blocked_since=blocked_since,
            is_blocked=blocked_since is not None,
        )


@strawberry.type
class ProjectNote:
    id: strawberry.ID
    project_id: strawberry.ID
    title: str
    body: str
    created: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, m: ProjectNoteModel) -> "ProjectNote":
        return cls(
            id=strawberry.ID(str(m.id)),
            project_id=strawberry.ID(str(m.project_id)),
            title=m.title,
            body=m.body,
            created=m.created,
            updated_at=m.updated_at,
        )


@strawberry.type
class TaskBlocker:
    id: strawberry.ID
    blocked_task_id: strawberry.ID
    blocking_task_id: Optional[strawberry.ID]
    external_description: str
    created: dt.datetime

    @classmethod
    def from_model(cls, m: TaskBlockerModel) -> "TaskBlocker":
        return cls(
            id=strawberry.ID(str(m.id)),
            blocked_task_id=strawberry.ID(str(m.blocked_task_id)),
            blocking_task_id=strawberry.ID(str(m.blocking_task_id)) if m.blocking_task_id else None,
            external_description=m.external_description,
            created=m.created,
        )


@strawberry.type
class Task:
    id: strawberry.ID
    title: str
    project_id: Optional[strawberry.ID]
    due_date: Optional[dt.datetime]
    done: bool
    completed_at: Optional[dt.datetime]
    created: dt.datetime
    effort_hours: Optional[float] = None
    due_time: Optional[dt.time] = None
    duration_minutes: Optional[int] = None
    # State-closure parking: the due-date snapshot kept while the parent project
    # is closed. Non-null means "this task had a due date" → the revive UI offers
    # to restore it. None on live tasks.
    parked_due_date: Optional[dt.datetime] = None
    parked_due_time: Optional[dt.time] = None
    blockers: List["TaskBlocker"] = strawberry.field(default_factory=list)
    # Derivados de `blockers` (REDISENO_PLAN.md §8). El badge de bloqueo necesita
    # los días y la razón, y no debería recalcularlos cada cliente.
    blocked_since: Optional[dt.datetime] = None
    blocked_reason: str = ""

    @classmethod
    def from_model(cls, m: TaskModel, blockers: Optional[List["TaskBlocker"]] = None) -> "Task":
        """Proyecta una tarea, recibiendo sus bloqueadores ya resueltos.

        Los `blockers` se pasan explícitos (no se consultan aquí) para que el
        dashboard pueda precargarlos en bloque y evitar un N+1; resolvers que no
        los necesitan pasan `None` -> lista vacía.
        """
        bs = blockers or []
        return cls(
            id=strawberry.ID(str(m.id)),
            title=m.title,
            project_id=strawberry.ID(str(m.project_id)) if m.project_id else None,
            due_date=m.due_date,
            done=m.done,
            completed_at=m.completed_at,
            created=m.created,
            effort_hours=m.effort_hours,
            due_time=m.due_time,
            duration_minutes=m.duration_minutes,
            parked_due_date=m.parked_due_date,
            parked_due_time=m.parked_due_time,
            blockers=bs,
            blocked_since=cooling_svc.blocked_since(bs),
            blocked_reason=cooling_svc.blocked_reason(bs),
        )


@strawberry.type
class Idea:
    id: strawberry.ID
    title: str
    description: str
    why: str
    created: dt.datetime

    @classmethod
    def from_model(cls, m: IdeaModel) -> "Idea":
        return cls(
            id=strawberry.ID(str(m.id)),
            title=m.title,
            description=m.description,
            why=m.why,
            created=m.created,
        )


@strawberry.type
class NoteSection:
    id: strawberry.ID
    note_id: strawberry.ID
    heading: str
    body: str
    position: int
    collapsed: bool
    created: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, m: NoteSectionModel) -> "NoteSection":
        return cls(
            id=strawberry.ID(str(m.id)),
            note_id=strawberry.ID(str(m.note_id)),
            heading=m.heading,
            body=m.body,
            position=m.position,
            collapsed=m.collapsed,
            created=m.created,
            updated_at=m.updated_at,
        )


@strawberry.type
class QuickNote:
    id: strawberry.ID
    title: str
    category_id: Optional[strawberry.ID]
    project_id: Optional[strawberry.ID]
    pinned: bool
    sections: List[NoteSection]
    created: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(
        cls, m: QuickNoteModel, sections: Optional[List[NoteSectionModel]] = None
    ) -> "QuickNote":
        """Proyecta una nota con sus secciones embebidas.

        Acepta `sections` precargadas para evitar el N+1 cuando el llamador ya
        las trajo; si no, las consulta perezosamente (`m.sections.all()`). Por
        eso QuickNotes vive fuera del `dashboard`: los cuerpos pueden ser
        grandes y se cargan al abrir la vista de Notas.
        """
        if sections is None:
            sections = list(m.sections.all())
        return cls(
            id=strawberry.ID(str(m.id)),
            title=m.title,
            category_id=strawberry.ID(str(m.category_id)) if m.category_id else None,
            project_id=strawberry.ID(str(m.project_id)) if m.project_id else None,
            pinned=m.pinned,
            sections=[NoteSection.from_model(s) for s in sections],
            created=m.created,
            updated_at=m.updated_at,
        )


@strawberry.type
class Activity:
    id: strawberry.ID
    kind: str
    entity_id: Optional[strawberry.ID]
    entity_title: str
    project_id: Optional[strawberry.ID]
    target_project_id: Optional[strawberry.ID]
    note: str
    previous_value: str
    new_value: str
    created: dt.datetime

    @classmethod
    def from_model(cls, m: ActivityModel) -> "Activity":
        return cls(
            id=strawberry.ID(str(m.id)),
            kind=m.kind,
            entity_id=strawberry.ID(str(m.entity_id)) if m.entity_id else None,
            entity_title=m.entity_title,
            project_id=strawberry.ID(str(m.project_id)) if m.project_id else None,
            target_project_id=strawberry.ID(str(m.target_project_id))
            if m.target_project_id
            else None,
            note=m.note,
            previous_value=m.previous_value,
            new_value=m.new_value,
            created=m.created,
        )


@strawberry.type
class Profile:
    avatar: Optional[str]
    first_name: Optional[str]

    @classmethod
    def from_model(cls, m: ProfileModel) -> "Profile":
        return cls(
            avatar=m.avatar or None,
            first_name=m.first_name or None,
        )


@strawberry.type
class OnboardingState:
    """Combined onboarding snapshot. One round-trip powers the whole flow."""

    status: str
    current_step: int
    tour_status: str
    completed_at: Optional[dt.datetime]
    completed_via: Optional[str]
    # Snapshot of the fields onboarding reads/writes, so the UI doesn't need
    # a second query against profile / notificationSettings / accountProfile.
    first_name: Optional[str]
    avatar: Optional[str]
    plan: str
    is_billing_exempt: bool


@strawberry.type
class TodayLayout:
    """User's customization of the Today screen.

    `order` is the MAIN column, in the user's order. `rail` is the side
    column, also ordered; a section is in one or the other, never both.
    Between them they cover the full canonical list. `hidden` lists ids
    the user has chosen not to render. Sections not in `hidden` still
    respect their data-existence condition (e.g. "sleeping" only renders
    if there are sleeping projects).

    `rail` se añadió con el Home de dos columnas del rediseño. Un cliente
    que no lo conozca (la app nativa) puede ignorarlo: `order` sigue
    siendo una lista válida por sí sola, solo que sin las secciones que
    el usuario mandó al lateral.
    """

    order: List[str]
    hidden: List[str]
    rail: List[str]


@strawberry.type
class Routine:
    id: strawberry.ID
    title: str
    description: str
    recurrence_type: str
    start_date: dt.date
    end_date: Optional[dt.date]
    weekdays: List[int]
    interval_n: Optional[int]
    interval_unit: Optional[str]
    monthly_day: Optional[int]
    effort_hours: Optional[float]
    archived: bool
    created: dt.datetime
    project_id: Optional[strawberry.ID] = None
    time_of_day: Optional[dt.time] = None
    duration_minutes: Optional[int] = None

    @classmethod
    def from_model(cls, m: RoutineModel) -> "Routine":
        return cls(
            id=strawberry.ID(str(m.id)),
            title=m.title,
            description=m.description,
            recurrence_type=m.recurrence_type,
            start_date=m.start_date,
            end_date=m.end_date,
            weekdays=[int(d) for d in (m.weekdays or [])],
            interval_n=m.interval_n,
            interval_unit=m.interval_unit or None,
            monthly_day=m.monthly_day,
            effort_hours=m.effort_hours,
            archived=m.archived,
            created=m.created,
            project_id=strawberry.ID(str(m.project_id)) if m.project_id else None,
            time_of_day=m.time_of_day,
            duration_minutes=m.duration_minutes,
        )


@strawberry.type
class RoutineOccurrence:
    id: strawberry.ID
    routine_id: strawberry.ID
    scheduled_date: dt.date
    completed_at: dt.datetime
    note: str
    created: dt.datetime

    @classmethod
    def from_model(cls, m: RoutineOccurrenceModel) -> "RoutineOccurrence":
        return cls(
            id=strawberry.ID(str(m.id)),
            routine_id=strawberry.ID(str(m.routine_id)),
            scheduled_date=m.scheduled_date,
            completed_at=m.completed_at,
            note=m.note,
            created=m.created,
        )


@strawberry.type
class RoutineDueItem:
    routine_id: strawberry.ID
    scheduled_date: dt.date
    occurrence_id: Optional[strawberry.ID]


@strawberry.type
class Dashboard:
    projects: List[Project]
    tasks: List[Task]
    ideas: List[Idea]
    activities: List[Activity]
    categories: List[Category]
    project_notes: List[ProjectNote]
    routines: List[Routine]
    routine_occurrences: List[RoutineOccurrence]
    last_backup: Optional[dt.datetime]


# ---------- Inputs ----------


@strawberry.input
class ProjectInput:
    name: str
    description: Optional[str] = ""
    why: Optional[str] = ""
    next_step: Optional[str] = ""
    status: Optional[str] = "idea"
    priority: Optional[str] = "medium"
    category_id: Optional[strawberry.ID] = None
    due_date: Optional[dt.datetime] = None
    # Closure notes (used by updateProject; ignored by createProject).
    paused_context: Optional[str] = None
    paused_next_action: Optional[str] = None
    paused_blocker: Optional[str] = None
    killed_reason: Optional[str] = None
    killed_learnings: Optional[str] = None
    killed_would_restart: Optional[str] = None


@strawberry.input
class ProjectNoteInput:
    project_id: strawberry.ID
    title: Optional[str] = ""
    body: str = ""


@strawberry.input
class CategoryInput:
    name: str
    color: Optional[str] = "emerald"


@strawberry.input
class TaskInput:
    title: str
    project_id: Optional[strawberry.ID] = None
    due_date: Optional[dt.datetime] = None
    done: Optional[bool] = False
    effort_hours: Optional[float] = None
    due_time: Optional[dt.time] = None
    duration_minutes: Optional[int] = None
    # Los dos ultimos SOLO los lee `createTask`; `updateTask` los ignora.
    # `blocker` es la razon de bloqueo externa, para que tarea y blocker entren
    # en la misma transaccion (antes eran dos mutations y podian quedar a
    # medias). `client_token` hace idempotente el reintento de la captura
    # rapida: mismo token = misma tarea, no una copia.
    blocker: Optional[str] = ""
    client_token: Optional[str] = ""


@strawberry.input
class IdeaInput:
    title: str
    description: Optional[str] = ""
    why: Optional[str] = ""


@strawberry.input
class QuickNoteInput:
    title: Optional[str] = ""
    category_id: Optional[strawberry.ID] = None
    project_id: Optional[strawberry.ID] = None
    pinned: Optional[bool] = False


@strawberry.input
class NoteSectionInput:
    heading: Optional[str] = ""
    body: Optional[str] = ""
    position: Optional[int] = None
    collapsed: Optional[bool] = False


@strawberry.input
class RoutineInput:
    title: str
    recurrence_type: str
    start_date: dt.date
    description: Optional[str] = ""
    end_date: Optional[dt.date] = None
    weekdays: Optional[List[int]] = None
    interval_n: Optional[int] = None
    interval_unit: Optional[str] = None
    monthly_day: Optional[int] = None
    effort_hours: Optional[float] = None
    project_id: Optional[strawberry.ID] = None
    time_of_day: Optional[dt.time] = None
    duration_minutes: Optional[int] = None


@strawberry.input
class TaskBlockerInput:
    blocked_task_id: strawberry.ID
    blocking_task_id: Optional[strawberry.ID] = None
    external_description: Optional[str] = ""


@strawberry.input
class ImportPayload:
    projects: str  # JSON string — keeps schema simple, validated server-side
    mode: str = "merge"  # "merge" | "replace"


# ---------- Google Tasks plugin ----------


@strawberry.type
class GoogleTasksConnection:
    connected: bool
    email: Optional[str] = None
    connected_at: Optional[dt.datetime] = None


@strawberry.type
class GoogleTaskList:
    id: str
    title: str


@strawberry.type
class McpConnection:
    """An MCP connector (e.g. Claude) the user has authorized."""

    client_id: strawberry.ID
    client_name: str
    connected_at: Optional[dt.datetime] = None


@strawberry.input
class GoogleTasksImportMapping:
    google_list_id: str
    project_id: Optional[strawberry.ID] = None
    new_project_name: Optional[str] = None


@strawberry.type
class GoogleTasksImportResult:
    imported: int
    skipped: int
    created_projects: List[str]


# ---------- Calendar integration plugin ----------


@strawberry.type
class GoogleCalendarItem:
    id: str
    title: str
    primary: bool


@strawberry.type
class CalendarIntegration:
    """Aggregated state for the calendar plugin UI: the subscribe-by-URL ICS
    feed (covers iCloud/iOS, Google, Outlook) + the direct Google Calendar
    push connection + the sync toggles."""

    feed_url: str
    sync_enabled: bool
    sync_tasks: bool
    sync_routines: bool
    google_connected: bool
    google_email: Optional[str] = None
    google_calendar_id: str = ""
    icloud_connected: bool = False
    icloud_apple_id: Optional[str] = None


@strawberry.type
class CalendarSyncResult:
    created: int
    updated: int
    deleted: int


# ---------- Analytics types ----------


@strawberry.type
class CadenceStats:
    active_days_in_range: int
    total_activity_events: int


@strawberry.type
class ActivityPoint:
    day: dt.date
    updates: int
    completed_tasks: int
    total_events: int


@strawberry.type
class WeekdayBucket:
    weekday: int
    count: int


@strawberry.type
class ProjectInteractionRow:
    project_id: strawberry.ID
    name: str
    status: str
    interactions: int
    delta_vs_prev: int


@strawberry.type
class StatusCount:
    status: str
    count: int


@strawberry.type
class CategoryRow:
    category_id: Optional[strawberry.ID]
    name: str
    color: str
    project_count: int
    interactions: int


@strawberry.type
class BacklogHealth:
    overdue_tasks: int
    due_soon_tasks: int
    open_tasks: int
    quick_wins: int
    almost_there: int


@strawberry.type
class SleepingProjectRow:
    project_id: strawberry.ID
    name: str
    days_idle: int
    bucket: str


@strawberry.type
class StaleIdeaRow:
    idea_id: strawberry.ID
    title: str
    days_old: int


@strawberry.type
class IdeaFunnel:
    ideas_created: int
    ideas_promoted: int
    promotion_rate: float


@strawberry.type
class EffortProjectRow:
    project_id: strawberry.ID
    name: str
    hours: float


@strawberry.type
class EffortStats:
    effort_hours_total: float
    tasks_with_effort_pct: float
    effort_hours_by_project: List[EffortProjectRow]


@strawberry.type
class LoopToolRow:
    tool: str
    count: int


@strawberry.type
class LoopDailyPoint:
    day: dt.date
    messages: int
    deep_messages: int


@strawberry.type
class LoopStats:
    messages_sent: int
    messages_delta_vs_prev: int
    conversations: int
    actions_taken: int
    active_days: int
    deep_messages: int
    connector_interactions: int
    daily: List[LoopDailyPoint]
    top_tools: List[LoopToolRow]


@strawberry.type
class Analytics:
    range: AnalyticsRange
    range_start: Optional[dt.datetime]
    range_end: dt.datetime
    cadence: CadenceStats
    activity_series: List[ActivityPoint]
    weekday_heatmap: List[WeekdayBucket]
    top_projects: List[ProjectInteractionRow]
    status_counts: List[StatusCount]
    category_breakdown: List[CategoryRow]
    backlog: BacklogHealth
    sleeping_projects: List[SleepingProjectRow]  # deprecated alias, see stalledProjects
    stalled_projects: List[SleepingProjectRow]
    stale_ideas: List[StaleIdeaRow]
    idea_funnel: IdeaFunnel
    effort: EffortStats
    loop: LoopStats


@strawberry.type
class GraveyardInsightType:
    body: str
    deaths_count: int
    computed_at: Optional[dt.datetime]
    is_stale: bool


# TODO: mover serializador a analytics.py
def _to_analytics_gql(r: analytics_mod.AnalyticsResult) -> Analytics:
    """Convierte el resultado de cálculo de analytics a los tipos GraphQL.

    Frontera entre el dominio (`analytics_mod.AnalyticsResult`, dataclasses
    planas) y el esquema. Es puro mapeo campo a campo y rebote de UUIDs a
    `strawberry.ID`; mantenerlo aquí evita que el módulo de cálculo dependa de
    Strawberry. Largo por exhaustivo, no por complejo.

    Nota: `sleeping_projects` se serializa además de `stalled_projects` por
    compatibilidad — es un alias deprecado (ver el tipo `Analytics`).

    Args:
        r: Resultado ya calculado por `analytics_mod.compute_analytics`.

    Returns:
        El tipo `Analytics` listo para devolver al cliente.
    """
    return Analytics(
        range=r.range,
        range_start=r.range_start,
        range_end=r.range_end,
        cadence=CadenceStats(
            active_days_in_range=r.cadence.active_days_in_range,
            total_activity_events=r.cadence.total_activity_events,
        ),
        activity_series=[
            ActivityPoint(
                day=p.day,
                updates=p.updates,
                completed_tasks=p.completed_tasks,
                total_events=p.total_events,
            )
            for p in r.activity_series
        ],
        weekday_heatmap=[
            WeekdayBucket(weekday=b.weekday, count=b.count) for b in r.weekday_heatmap
        ],
        top_projects=[
            ProjectInteractionRow(
                project_id=strawberry.ID(str(row.project_id)),
                name=row.name,
                status=row.status,
                interactions=row.interactions,
                delta_vs_prev=row.delta_vs_prev,
            )
            for row in r.top_projects
        ],
        status_counts=[
            StatusCount(status=s.status, count=s.count) for s in r.status_counts
        ],
        category_breakdown=[
            CategoryRow(
                category_id=strawberry.ID(str(c.category_id)) if c.category_id else None,
                name=c.name,
                color=c.color,
                project_count=c.project_count,
                interactions=c.interactions,
            )
            for c in r.category_breakdown
        ],
        backlog=BacklogHealth(
            overdue_tasks=r.backlog.overdue_tasks,
            due_soon_tasks=r.backlog.due_soon_tasks,
            open_tasks=r.backlog.open_tasks,
            quick_wins=r.backlog.quick_wins,
            almost_there=r.backlog.almost_there,
        ),
        sleeping_projects=[
            SleepingProjectRow(
                project_id=strawberry.ID(str(s.project_id)),
                name=s.name,
                days_idle=s.days_idle,
                bucket=s.bucket,
            )
            for s in r.sleeping_projects
        ],
        stalled_projects=[
            SleepingProjectRow(
                project_id=strawberry.ID(str(s.project_id)),
                name=s.name,
                days_idle=s.days_idle,
                bucket=s.bucket,
            )
            for s in r.stalled_projects
        ],
        stale_ideas=[
            StaleIdeaRow(
                idea_id=strawberry.ID(str(s.idea_id)),
                title=s.title,
                days_old=s.days_old,
            )
            for s in r.stale_ideas
        ],
        idea_funnel=IdeaFunnel(
            ideas_created=r.idea_funnel.ideas_created,
            ideas_promoted=r.idea_funnel.ideas_promoted,
            promotion_rate=r.idea_funnel.promotion_rate,
        ),
        effort=EffortStats(
            effort_hours_total=r.effort.effort_hours_total,
            tasks_with_effort_pct=r.effort.tasks_with_effort_pct,
            effort_hours_by_project=[
                EffortProjectRow(
                    project_id=strawberry.ID(str(e.project_id)),
                    name=e.name,
                    hours=e.hours,
                )
                for e in r.effort.effort_hours_by_project
            ],
        ),
        loop=LoopStats(
            messages_sent=r.loop.messages_sent,
            messages_delta_vs_prev=r.loop.messages_delta_vs_prev,
            conversations=r.loop.conversations,
            actions_taken=r.loop.actions_taken,
            active_days=r.loop.active_days,
            deep_messages=r.loop.deep_messages,
            connector_interactions=r.loop.connector_interactions,
            daily=[
                LoopDailyPoint(
                    day=p.day,
                    messages=p.messages,
                    deep_messages=p.deep_messages,
                )
                for p in r.loop.daily
            ],
            top_tools=[
                LoopToolRow(tool=tr.tool, count=tr.count)
                for tr in r.loop.top_tools
            ],
        ),
    )


def build_onboarding_state(info: Info) -> "OnboardingState":
    """The onboarding snapshot, shared by the query and every mutation that
    advances the flow.

    It lives here, next to the type it builds, because `Query` and `Mutation`
    are in different modules now: the mutations used to call
    `Query().onboarding_state(info)`, which raised `NameError: name 'Query' is
    not defined` at runtime — `Query` is defined in `schema.py` and never
    entered this module's namespace. Nothing caught it because no test
    exercised those mutations; the flow just broke for every new account.
    """
    from .schema_helpers import _user_id
    from .services import onboarding as onboarding_svc, profiles as profiles_svc
    from .assistant.quotas import get_or_create_profile

    uid = _user_id(info)
    progress = onboarding_svc.get_progress(uid)
    profile = profiles_svc.get_profile(uid)
    # Provisioned through the canonical path so the exemption decision has
    # already run by the time step 4 reads the flag.
    account = get_or_create_profile(uid)
    return OnboardingState(
        status=progress.status,
        current_step=progress.current_step,
        tour_status=progress.tour_status,
        completed_at=progress.completed_at,
        completed_via=progress.completed_via or None,
        first_name=profile.first_name or None,
        avatar=profile.avatar or None,
        plan=account.plan,
        is_billing_exempt=bool(account.is_billing_exempt),
    )


__all__ = [
    "AnalyticsRange",
    "build_onboarding_state",
    "Category",
    "Project",
    "ProjectNote",
    "TaskBlocker",
    "Task",
    "Idea",
    "NoteSection",
    "QuickNote",
    "Activity",
    "Profile",
    "OnboardingState",
    "TodayLayout",
    "Routine",
    "RoutineOccurrence",
    "RoutineDueItem",
    "Dashboard",
    "ProjectInput",
    "ProjectNoteInput",
    "CategoryInput",
    "TaskInput",
    "IdeaInput",
    "QuickNoteInput",
    "NoteSectionInput",
    "RoutineInput",
    "TaskBlockerInput",
    "ImportPayload",
    "GoogleTasksConnection",
    "GoogleTaskList",
    "McpConnection",
    "GoogleTasksImportMapping",
    "GoogleTasksImportResult",
    "GoogleCalendarItem",
    "CalendarIntegration",
    "CalendarSyncResult",
    "CadenceStats",
    "ActivityPoint",
    "WeekdayBucket",
    "ProjectInteractionRow",
    "StatusCount",
    "CategoryRow",
    "BacklogHealth",
    "SleepingProjectRow",
    "StaleIdeaRow",
    "IdeaFunnel",
    "EffortProjectRow",
    "EffortStats",
    "LoopToolRow",
    "LoopDailyPoint",
    "LoopStats",
    "Analytics",
    "GraveyardInsightType",
]

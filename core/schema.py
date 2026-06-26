"""Esquema GraphQL raíz de la app (Strawberry).

Este módulo es la cara pública de la API autenticada: define los **tipos**
GraphQL y sus `from_model` (proyección modelo Django -> tipo GraphQL), los
**inputs** de mutación, y los resolvers de `Query`/`Mutation`.

Principio de diseño: los resolvers son finos. Casi toda la lógica vive en
`core/services/*`; aquí solo se traduce (auth -> `uid`, args -> kwargs del
servicio, errores de dominio -> `GraphQLError` con `extensions.code`, y modelo
-> tipo GraphQL). La excepción notable es `dashboard()`, que aún consulta varios
modelos directamente para servir toda la pantalla inicial en un solo round-trip.

Al final, los tipos de esta app y los de las sub-apps (notifications, admin,
cms, billing, feedback, announcements) se fusionan con `merge_types()` en un
único `schema` raíz.
"""

import functools
import uuid
import datetime as dt
from typing import Optional, List

import strawberry
from strawberry.tools import merge_types
from strawberry.types import Info
from graphql import GraphQLError

from . import analytics as analytics_mod
from . import account_deletion
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
from .notifications.schema import NotificationsQuery, NotificationsMutation
from .admin_api.schema import AdminQuery, AdminMutation
from .admin_api.beta_schema import AdminBetaQuery, AdminBetaMutation
from .cms.schema_admin import CmsAdminQuery, CmsAdminMutation
from .billing.schema import BillingMutation
from .feedback.schema import (
    AdminFeedbackMutation,
    AdminFeedbackQuery,
    FeedbackMutation,
)
from .announcements.schema import (
    AdminAnnouncementsMutation,
    AdminAnnouncementsQuery,
    NotificationsQuery as InAppNotificationsQuery,
)
from .services import (
    activities as activities_svc,
    calendar_feed as calendar_feed_svc,
    categories as categories_svc,
    dashboard as dashboard_svc,
    google_calendar as google_calendar_svc,
    google_tasks as google_tasks_svc,
    icloud_calendar as icloud_calendar_svc,
    ideas as ideas_svc,
    mcp_connections as mcp_connections_svc,
    notes as notes_svc,
    onboarding as onboarding_svc,
    preferences as preferences_svc,
    profiles as profiles_svc,
    projects as projects_svc,
    quick_notes as quick_notes_svc,
    routines as routines_svc,
    tasks as tasks_svc,
)
from django.core.exceptions import ValidationError

from core.assistant.quotas import get_or_create_profile
from .services.projects import NotFoundError
from .quotas import EntityQuotaExceeded


AnalyticsRange = strawberry.enum(AnalyticsRangeEnum, name="AnalyticsRange")


def _user_id(info: Info) -> uuid.UUID:
    """Extrae el `user_id` autenticado del contexto o rechaza la petición.

    Centraliza el gate de auth para que todo resolver empiece con un `uid`
    fiable. El `user_id` lo inyecta el middleware de auth (Supabase JWT) en
    `info.context`; su ausencia significa petición sin token válido.

    Raises:
        GraphQLError: con `extensions.code = "UNAUTHENTICATED"` si no hay
            usuario en el contexto.
    """
    user_id = getattr(info.context, "user_id", None)
    if not user_id:
        raise GraphQLError(
            "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
        )
    return user_id


def _quota_error(e: EntityQuotaExceeded) -> GraphQLError:
    """Traduce un tope de cuota a `GraphQLError` con los datos para la UI.

    Expone en `extensions` el detalle accionable (qué cuota, uso actual, tope y
    plan) para que el cliente pueda mostrar el paywall/upsell correcto sin tener
    que parsear el mensaje.
    """
    return GraphQLError(
        str(e),
        extensions={
            "code": "QUOTA_EXCEEDED",
            "kind": e.kind,
            "current": e.current,
            "cap": e.cap,
            "plan": e.plan,
        },
    )


def _closure_error(e: ValidationError) -> GraphQLError:
    """Traduce el `ValidationError` de cierre de proyecto a `GraphQLError`.

    Cambiar de estado a pausado/matado exige notas de cierre; cuando faltan, el
    servicio levanta un `ValidationError` de Django. Aquí se aplana a un código
    propio (`CLOSURE_NOTES_REQUIRED`) que la UI usa para abrir el modal de notas
    en vez de tratarlo como error genérico.
    """
    msg = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
    return GraphQLError(msg, extensions={"code": "CLOSURE_NOTES_REQUIRED"})


def gql_error_handler(fn):
    """Traduce las excepciones de dominio UNIFORMES a `GraphQLError`.

    Centraliza el mapeo que se repetía en ~30 mutations:
    ``NotFoundError`` → ``NOT_FOUND`` (preservando el mensaje del servicio, que
    siempre es ``"<Entidad> not found"``) y ``EntityQuotaExceeded`` →
    ``QUOTA_EXCEEDED`` (vía :func:`_quota_error`).

    Deliberadamente NO captura ``ValidationError``: su mapeo es heterogéneo
    (``CLOSURE_NOTES_REQUIRED`` en cierre de proyecto vs. ``BAD_INPUT`` en
    rutinas/perfil/preferencias), así que cada resolver que lo necesita lo
    maneja explícito. ``UNAUTHENTICATED`` lo levanta ``_user_id`` antes de
    entrar al cuerpo, así que tampoco aplica aquí.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotFoundError as e:
            raise GraphQLError(str(e), extensions={"code": "NOT_FOUND"})
        except EntityQuotaExceeded as e:
            raise _quota_error(e)

    return wrapper


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

    @classmethod
    def from_model(cls, m: ProjectModel) -> "Project":
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

    @classmethod
    def from_model(cls, m: TaskModel, blockers: Optional[List["TaskBlocker"]] = None) -> "Task":
        """Proyecta una tarea, recibiendo sus bloqueadores ya resueltos.

        Los `blockers` se pasan explícitos (no se consultan aquí) para que el
        dashboard pueda precargarlos en bloque y evitar un N+1; resolvers que no
        los necesitan pasan `None` -> lista vacía.
        """
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
            blockers=blockers or [],
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

    `order` is always the full canonical section list with the user's
    reorder applied. `hidden` lists ids the user has chosen not to
    render. Sections not in `hidden` still respect their data-existence
    condition (e.g. "sleeping" only renders if there are sleeping
    projects).
    """

    order: List[str]
    hidden: List[str]


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


# ---------- Queries ----------


@strawberry.type
class Query:
    # TODO: refactor — mover a services/dashboard.py:get_full_dashboard(uid); consulta 7+ modelos en el resolver (ver AUDITORIA_CODIGO.md)
    @strawberry.field
    def dashboard(self, info: Info) -> Dashboard:
        """Carga inicial de la app: todo el estado del usuario en un round-trip.

        A diferencia del resto de resolvers, el acceso a datos se delega al
        servicio ``dashboard`` (que junta todo en un pase, un round-trip de
        producto); aquí solo se proyectan los modelos crudos a los tipos
        GraphQL con los conversores ``from_model``.
        """
        uid = _user_id(info)
        d = dashboard_svc.get_dashboard(uid)
        return Dashboard(
            projects=[Project.from_model(p) for p in d.projects],
            tasks=[
                Task.from_model(
                    t,
                    blockers=[TaskBlocker.from_model(b) for b in d.blocker_map.get(t.id, [])],
                )
                for t in d.tasks
            ],
            ideas=[Idea.from_model(i) for i in d.ideas],
            activities=[Activity.from_model(a) for a in d.activities],
            categories=[Category.from_model(c) for c in d.categories],
            project_notes=[ProjectNote.from_model(n) for n in d.project_notes],
            routines=[Routine.from_model(r) for r in d.routines],
            routine_occurrences=[
                RoutineOccurrence.from_model(o) for o in d.routine_occurrences
            ],
            last_backup=d.last_backup,
        )

    @strawberry.field
    def graveyard_insight(self, info: Info) -> Optional[GraveyardInsightType]:
        uid = _user_id(info)
        gi = GraveyardInsightModel.objects.filter(user_id=uid).first()
        if gi is None or not gi.body:
            return None
        return GraveyardInsightType(
            body=gi.body,
            deaths_count=gi.deaths_count,
            computed_at=gi.computed_at,
            is_stale=gi.is_stale,
        )

    @strawberry.field
    def quick_notes(
        self,
        info: Info,
        search: Optional[str] = None,
        category_id: Optional[strawberry.ID] = None,
        project_id: Optional[strawberry.ID] = None,
        pinned: Optional[bool] = None,
    ) -> List[QuickNote]:
        uid = _user_id(info)
        notes = quick_notes_svc.list_quick_notes(
            uid,
            search=search,
            category_id=category_id,
            project_id=project_id,
            pinned=pinned,
        )
        return [QuickNote.from_model(n) for n in notes]

    @strawberry.field
    def quick_note(self, info: Info, id: strawberry.ID) -> Optional[QuickNote]:
        uid = _user_id(info)
        try:
            n = quick_notes_svc.get_quick_note(uid, id)
        except NotFoundError:
            return None
        return QuickNote.from_model(n)

    @strawberry.field(name="routinesDue")
    def routines_due(
        self,
        info: Info,
        from_date: dt.date,
        to_date: dt.date,
    ) -> List[RoutineDueItem]:
        uid = _user_id(info)
        items = routines_svc.list_due_in_range(uid, from_date, to_date)
        return [
            RoutineDueItem(
                routine_id=strawberry.ID(str(it["routine_id"])),
                scheduled_date=it["scheduled_date"],
                occurrence_id=strawberry.ID(str(it["occurrence_id"]))
                if it["occurrence_id"]
                else None,
            )
            for it in items
        ]

    @strawberry.field
    def analytics(
        self,
        info: Info,
        range: AnalyticsRange = AnalyticsRange.LAST_30_DAYS,
    ) -> Analytics:
        uid = _user_id(info)
        result = analytics_mod.compute_analytics(uid, range)
        return _to_analytics_gql(result)

    @strawberry.field
    def profile(self, info: Info) -> Profile:
        uid = _user_id(info)
        return Profile.from_model(profiles_svc.get_profile(uid))

    @strawberry.field
    def onboarding_state(self, info: Info) -> OnboardingState:
        uid = _user_id(info)
        progress = onboarding_svc.get_progress(uid)
        profile = profiles_svc.get_profile(uid)
        # Provision the AccountProfile through the canonical path so the
        # early-adopter exemption decision has already run by the time we read
        # the flag. The resolver used to only *read* the profile (filter().first()),
        # so a brand-new user whose first request was this onboarding query saw
        # is_billing_exempt=False (the plan-picker screen) until some later
        # request (e.g. the assistant) lazily created the profile — a race that
        # randomly showed the wrong Step 4 screen. Reading it here makes the
        # screen deterministic: it now reflects the flag's true value, including
        # once the auto-exemption logic is eventually removed (flag = off →
        # plan-picker shows).
        account = get_or_create_profile(uid)
        plan = account.plan
        is_billing_exempt = bool(account.is_billing_exempt)
        return OnboardingState(
            status=progress.status,
            current_step=progress.current_step,
            tour_status=progress.tour_status,
            completed_at=progress.completed_at,
            completed_via=progress.completed_via or None,
            first_name=profile.first_name or None,
            avatar=profile.avatar or None,
            plan=plan,
            is_billing_exempt=is_billing_exempt,
        )

    @strawberry.field
    def today_layout(self, info: Info) -> TodayLayout:
        uid = _user_id(info)
        layout = preferences_svc.get_today_layout(uid)
        return TodayLayout(order=layout["order"], hidden=layout["hidden"])

    @strawberry.field
    def activity(
        self,
        info: Info,
        limit: int = 100,
        since: Optional[dt.datetime] = None,
        until: Optional[dt.datetime] = None,
        project_id: Optional[strawberry.ID] = None,
        kinds: Optional[List[str]] = None,
    ) -> List[Activity]:
        uid = _user_id(info)
        rows = activities_svc.list_activity(
            uid,
            project_id=project_id,
            kinds=kinds,
            limit=limit,
            since=since,
            until=until,
        )
        return [Activity.from_model(m) for m in rows]

    @strawberry.field
    def google_tasks_connection(self, info: Info) -> GoogleTasksConnection:
        uid = _user_id(info)
        status = google_tasks_svc.get_connection_status(uid)
        if status is None:
            return GoogleTasksConnection(connected=False)
        return GoogleTasksConnection(
            connected=True,
            email=status["email"] or None,
            connected_at=status["connected_at"],
        )

    @strawberry.field
    def google_task_lists(self, info: Info) -> List[GoogleTaskList]:
        uid = _user_id(info)
        try:
            items = google_tasks_svc.list_task_lists(uid)
        except google_tasks_svc.NotConnectedError:
            raise GraphQLError(
                "Google Tasks is not connected",
                extensions={"code": "NOT_CONNECTED"},
            )
        except google_tasks_svc.GoogleTasksError as e:
            raise GraphQLError(str(e), extensions={"code": "GOOGLE_TASKS_ERROR"})
        return [GoogleTaskList(id=it["id"], title=it["title"]) for it in items]

    @strawberry.field
    def calendar_integration(self, info: Info) -> CalendarIntegration:
        uid = _user_id(info)
        from .notifications.models import NotificationSettings as _NS

        s = _NS.objects.filter(user_id=uid).first()
        gstatus = google_calendar_svc.get_connection_status(uid)
        istatus = icloud_calendar_svc.get_connection_status(uid)
        return CalendarIntegration(
            feed_url=calendar_feed_svc.feed_url(uid),
            sync_enabled=bool(s.calendar_sync_enabled) if s else False,
            sync_tasks=bool(s.calendar_sync_tasks) if s else True,
            sync_routines=bool(s.calendar_sync_routines) if s else True,
            google_connected=gstatus is not None,
            google_email=(gstatus or {}).get("email") or None,
            google_calendar_id=(s.google_calendar_id if s else "") or "",
            icloud_connected=istatus is not None,
            icloud_apple_id=(istatus or {}).get("apple_id") or None,
        )

    @strawberry.field
    def google_calendars(self, info: Info) -> List[GoogleCalendarItem]:
        uid = _user_id(info)
        try:
            items = google_calendar_svc.list_calendars(uid)
        except google_calendar_svc.NotConnectedError:
            raise GraphQLError(
                "Google Calendar is not connected",
                extensions={"code": "NOT_CONNECTED"},
            )
        except google_calendar_svc.GoogleTasksError as e:
            raise GraphQLError(str(e), extensions={"code": "GOOGLE_CALENDAR_ERROR"})
        return [
            GoogleCalendarItem(id=it["id"], title=it["title"], primary=it["primary"])
            for it in items
        ]

    @strawberry.field
    def mcp_connections(self, info: Info) -> List[McpConnection]:
        uid = _user_id(info)
        return [
            McpConnection(
                client_id=strawberry.ID(c["client_id"]),
                client_name=c["client_name"],
                connected_at=c["connected_at"],
            )
            for c in mcp_connections_svc.list_connections(uid)
        ]


# ---------- Mutations ----------


@strawberry.type
class Mutation:
    # ===== Mutations: Conector MCP =====
    @strawberry.mutation
    def revoke_mcp_connection(self, info: Info, client_id: strawberry.ID) -> bool:
        """Revoke a connected MCP client (e.g. Claude). Returns True if any
        live token was revoked."""
        uid = _user_id(info)
        revoked = mcp_connections_svc.revoke_connection(uid, str(client_id))
        return revoked > 0

    # ===== Mutations: Proyectos =====
    @strawberry.mutation
    @gql_error_handler
    def create_project(self, info: Info, data: ProjectInput) -> Project:
        uid = _user_id(info)
        m = projects_svc.create_project(
            uid,
            name=data.name,
            description=data.description or "",
            why=data.why or "",
            next_step=data.next_step or "",
            status=data.status or "idea",
            priority=data.priority or "medium",
            category_id=data.category_id,
            due_date=data.due_date,
        )
        return Project.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_project(self, info: Info, id: strawberry.ID, data: ProjectInput) -> Project:
        uid = _user_id(info)
        try:
            m = projects_svc.update_project(
                uid,
                id,
                name=data.name,
                description=data.description or "",
                why=data.why or "",
                next_step=data.next_step or "",
                status=data.status,
                priority=data.priority,
                category_id=data.category_id,
                clear_category=data.category_id is None,
                due_date=data.due_date,
                paused_context=data.paused_context,
                paused_next_action=data.paused_next_action,
                paused_blocker=data.paused_blocker,
                killed_reason=data.killed_reason,
                killed_learnings=data.killed_learnings,
                killed_would_restart=data.killed_would_restart,
            )
        except ValidationError as e:
            # ValidationError aquí significa "faltan notas de cierre" → código propio.
            raise _closure_error(e)
        return Project.from_model(m)

    @strawberry.mutation
    def reorder_projects(
        self, info: Info, ordered_ids: List[strawberry.ID]
    ) -> List[Project]:
        uid = _user_id(info)
        rows = projects_svc.reorder_projects(uid, list(ordered_ids))
        return [Project.from_model(m) for m in rows]

    # ===== Mutations: Notas de proyecto (varias por proyecto) =====
    @strawberry.mutation
    @gql_error_handler
    def create_project_note(self, info: Info, data: ProjectNoteInput) -> ProjectNote:
        uid = _user_id(info)
        m = notes_svc.create_note(
            uid,
            project_id=data.project_id,
            title=data.title or "",
            body=data.body or "",
        )
        return ProjectNote.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_project_note(
        self, info: Info, id: strawberry.ID, data: ProjectNoteInput
    ) -> ProjectNote:
        uid = _user_id(info)
        m = notes_svc.update_note(
            uid, id, title=data.title or "", body=data.body or ""
        )
        return ProjectNote.from_model(m)

    @strawberry.mutation
    def delete_project_note(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        notes_svc.delete_note(uid, id)
        return True

    @strawberry.mutation
    def delete_project(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        projects_svc.delete_project(uid, id)
        return True

    # ===== Mutations: Tareas =====
    @strawberry.mutation
    @gql_error_handler
    def create_task(self, info: Info, data: TaskInput) -> Task:
        uid = _user_id(info)
        m = tasks_svc.create_task(
            uid,
            title=data.title,
            project_id=data.project_id or None,
            due_date=data.due_date,
            done=bool(data.done),
            effort_hours=data.effort_hours,
            due_time=data.due_time,
            duration_minutes=data.duration_minutes,
        )
        return Task.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_task(self, info: Info, id: strawberry.ID, data: TaskInput) -> Task:
        uid = _user_id(info)
        m = tasks_svc.update_task(
            uid,
            id,
            title=data.title,
            project_id=data.project_id or None,
            due_date=data.due_date,
            done=bool(data.done),
            effort_hours=data.effort_hours,
            due_time=data.due_time,
            duration_minutes=data.duration_minutes,
        )
        return Task.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def toggle_task(self, info: Info, id: strawberry.ID) -> Task:
        uid = _user_id(info)
        m = tasks_svc.toggle_task(uid, id)
        return Task.from_model(m)

    @strawberry.mutation
    def delete_task(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        tasks_svc.delete_task(uid, id)
        return True

    @strawberry.mutation
    def restore_parked_due_dates(self, info: Info, project_id: strawberry.ID) -> bool:
        """Revive 'restore original dates': re-apply the parked due-date
        snapshots for a project's tasks (skips ones rescheduled meanwhile)."""
        uid = _user_id(info)
        tasks_svc.restore_parked_due_dates(uid, project_id)
        return True

    @strawberry.mutation
    def dismiss_parked_due_dates(self, info: Info, project_id: strawberry.ID) -> bool:
        """Revive 'keep unscheduled': drop the reschedule suggestion, leaving the
        project's tasks without a due date."""
        uid = _user_id(info)
        tasks_svc.dismiss_parked_due_dates(uid, project_id)
        return True

    # ===== Mutations: Ideas =====
    @strawberry.mutation
    @gql_error_handler
    def create_idea(self, info: Info, data: IdeaInput) -> Idea:
        uid = _user_id(info)
        m = ideas_svc.create_idea(
            uid,
            title=data.title,
            description=data.description or "",
            why=data.why or "",
        )
        return Idea.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_idea(self, info: Info, id: strawberry.ID, data: IdeaInput) -> Idea:
        uid = _user_id(info)
        m = ideas_svc.update_idea(
            uid,
            id,
            title=data.title,
            description=data.description or "",
            why=data.why or "",
        )
        return Idea.from_model(m)

    @strawberry.mutation
    def delete_idea(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        ideas_svc.delete_idea(uid, id)
        return True

    @strawberry.mutation
    @gql_error_handler
    def promote_idea(self, info: Info, id: strawberry.ID) -> Project:
        uid = _user_id(info)
        p = ideas_svc.promote_idea(uid, id)
        return Project.from_model(p)

    # ===== Mutations: Quick Notes (notas con secciones) =====
    @strawberry.mutation
    @gql_error_handler
    def create_quick_note(self, info: Info, data: QuickNoteInput) -> QuickNote:
        uid = _user_id(info)
        m = quick_notes_svc.create_quick_note(
            uid,
            title=data.title or "",
            category_id=data.category_id,
            project_id=data.project_id,
            pinned=bool(data.pinned),
        )
        return QuickNote.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_quick_note(
        self, info: Info, id: strawberry.ID, data: QuickNoteInput
    ) -> QuickNote:
        uid = _user_id(info)
        m = quick_notes_svc.update_quick_note(
            uid,
            id,
            title=data.title or "",
            category_id=data.category_id,
            project_id=data.project_id,
            pinned=bool(data.pinned),
        )
        return QuickNote.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def set_quick_note_pinned(
        self, info: Info, id: strawberry.ID, pinned: bool
    ) -> QuickNote:
        uid = _user_id(info)
        m = quick_notes_svc.set_pin(uid, id, pinned)
        return QuickNote.from_model(m)

    @strawberry.mutation
    def delete_quick_note(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        quick_notes_svc.delete_quick_note(uid, id)
        return True

    @strawberry.mutation
    @gql_error_handler
    def add_note_section(
        self, info: Info, note_id: strawberry.ID, data: NoteSectionInput
    ) -> NoteSection:
        uid = _user_id(info)
        m = quick_notes_svc.add_section(
            uid,
            note_id,
            heading=data.heading or "",
            body=data.body or "",
            position=data.position,
            collapsed=bool(data.collapsed),
        )
        return NoteSection.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_note_section(
        self, info: Info, id: strawberry.ID, data: NoteSectionInput
    ) -> NoteSection:
        uid = _user_id(info)
        m = quick_notes_svc.update_section(
            uid,
            id,
            heading=data.heading or "",
            body=data.body or "",
            collapsed=data.collapsed,
        )
        return NoteSection.from_model(m)

    @strawberry.mutation
    def delete_note_section(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        quick_notes_svc.delete_section(uid, id)
        return True

    @strawberry.mutation
    @gql_error_handler
    def reorder_note_sections(
        self, info: Info, note_id: strawberry.ID, ordered_ids: List[strawberry.ID]
    ) -> QuickNote:
        uid = _user_id(info)
        m = quick_notes_svc.reorder_sections(uid, note_id, list(ordered_ids))
        return QuickNote.from_model(m)

    # ===== Mutations: Notas de actividad (kind=NOTE) =====
    @strawberry.mutation
    @gql_error_handler
    def add_note(self, info: Info, project_id: strawberry.ID, note: str) -> Activity:
        uid = _user_id(info)
        m = activities_svc.add_note(uid, project_id=project_id, note=note)
        return Activity.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_note(self, info: Info, id: strawberry.ID, note: str) -> Activity:
        uid = _user_id(info)
        m = activities_svc.update_note(uid, id, note=note)
        return Activity.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def delete_note(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        activities_svc.delete_note(uid, id)
        return True

    # ===== Mutations: Categorías =====
    @strawberry.mutation
    @gql_error_handler
    def create_category(self, info: Info, data: CategoryInput) -> Category:
        uid = _user_id(info)
        m = categories_svc.create_category(
            uid, name=data.name, color=data.color or "emerald"
        )
        return Category.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_category(self, info: Info, id: strawberry.ID, data: CategoryInput) -> Category:
        uid = _user_id(info)
        m = categories_svc.update_category(
            uid, id, name=data.name, color=data.color or ""
        )
        return Category.from_model(m)

    @strawberry.mutation
    def delete_category(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        categories_svc.delete_category(uid, id)
        return True

    # ===== Mutations: Rutinas =====
    @strawberry.mutation
    @gql_error_handler
    def create_routine(self, info: Info, data: RoutineInput) -> Routine:
        from django.core.exceptions import ValidationError

        uid = _user_id(info)
        try:
            m = routines_svc.create_routine(
                uid,
                title=data.title,
                description=data.description or "",
                recurrence_type=data.recurrence_type,
                start_date=data.start_date,
                end_date=data.end_date,
                weekdays=list(data.weekdays) if data.weekdays is not None else None,
                interval_n=data.interval_n,
                interval_unit=data.interval_unit or None,
                monthly_day=data.monthly_day,
                effort_hours=data.effort_hours,
                project_id=data.project_id or None,
                time_of_day=data.time_of_day,
                duration_minutes=data.duration_minutes,
            )
        except ValidationError as e:
            # ValidationError aquí = regla de recurrencia inválida → BAD_INPUT.
            raise GraphQLError(
                str(e.messages[0] if e.messages else "Invalid input"),
                extensions={"code": "BAD_INPUT"},
            )
        return Routine.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def update_routine(
        self, info: Info, id: strawberry.ID, data: RoutineInput
    ) -> Routine:
        from django.core.exceptions import ValidationError

        uid = _user_id(info)
        try:
            m = routines_svc.update_routine(
                uid,
                id,
                title=data.title,
                description=data.description or "",
                recurrence_type=data.recurrence_type,
                start_date=data.start_date,
                end_date=data.end_date,
                weekdays=list(data.weekdays) if data.weekdays is not None else None,
                interval_n=data.interval_n,
                interval_unit=data.interval_unit or None,
                monthly_day=data.monthly_day,
                effort_hours=data.effort_hours,
                project_id=data.project_id or None,
                time_of_day=data.time_of_day,
                duration_minutes=data.duration_minutes,
            )
        except ValidationError as e:
            # ValidationError aquí = regla de recurrencia inválida → BAD_INPUT.
            raise GraphQLError(
                str(e.messages[0] if e.messages else "Invalid input"),
                extensions={"code": "BAD_INPUT"},
            )
        return Routine.from_model(m)

    @strawberry.mutation
    @gql_error_handler
    def archive_routine(
        self, info: Info, id: strawberry.ID, archived: bool
    ) -> Routine:
        uid = _user_id(info)
        m = routines_svc.archive_routine(uid, id, archived=archived)
        return Routine.from_model(m)

    @strawberry.mutation
    def delete_routine(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        routines_svc.delete_routine(uid, id)
        return True

    @strawberry.mutation(name="completeRoutineOccurrence")
    @gql_error_handler
    def complete_routine_occurrence(
        self,
        info: Info,
        routine_id: strawberry.ID,
        scheduled_date: dt.date,
        note: Optional[str] = "",
    ) -> RoutineOccurrence:
        uid = _user_id(info)
        m = routines_svc.complete_occurrence(
            uid, routine_id, scheduled_date=scheduled_date, note=note or ""
        )
        return RoutineOccurrence.from_model(m)

    @strawberry.mutation(name="uncompleteRoutineOccurrence")
    def uncomplete_routine_occurrence(
        self, info: Info, id: strawberry.ID
    ) -> bool:
        uid = _user_id(info)
        routines_svc.uncomplete_occurrence(uid, id)
        return True

    # ===== Mutations: Metadatos de backup =====
    @strawberry.mutation
    def mark_backup(self, info: Info) -> dt.datetime:
        uid = _user_id(info)
        from django.utils import timezone

        now = timezone.now()
        BackupMeta.objects.update_or_create(
            user_id=uid, defaults={"last_backup": now}
        )
        return now

    # ===== Mutations: Perfil =====
    @strawberry.mutation
    def update_profile(
        self,
        info: Info,
        avatar: Optional[str] = strawberry.UNSET,
        first_name: Optional[str] = strawberry.UNSET,
    ) -> Profile:
        """Partial profile update.

        Field is omitted (UNSET) -> not touched.
        Field is null            -> cleared (existing AvatarPickerModal
                                    relies on this for the "clear avatar"
                                    button).
        Field is a string        -> set to that string.
        """
        from django.core.exceptions import ValidationError

        uid = _user_id(info)
        m = profiles_svc.get_profile(uid)
        try:
            if avatar is not strawberry.UNSET:
                m = profiles_svc.set_avatar(uid, avatar)
            if first_name is not strawberry.UNSET:
                m = profiles_svc.set_first_name(uid, first_name)
        except ValidationError as e:
            raise GraphQLError(
                str(e.messages[0] if e.messages else "Invalid input"),
                extensions={"code": "BAD_INPUT"},
            )
        return Profile.from_model(m)

    # ===== Mutations: Onboarding =====
    @strawberry.mutation
    def set_onboarding_step(self, info: Info, step: int) -> OnboardingState:
        from django.core.exceptions import ValidationError

        uid = _user_id(info)
        try:
            onboarding_svc.set_step(uid, step)
        except ValidationError as e:
            raise GraphQLError(
                str(e.messages[0] if e.messages else "Invalid input"),
                extensions={"code": "BAD_INPUT"},
            )
        return Query().onboarding_state(info)

    @strawberry.mutation
    def complete_onboarding(
        self, info: Info, mode: str = "finished"
    ) -> OnboardingState:
        from django.core.exceptions import ValidationError

        uid = _user_id(info)
        try:
            onboarding_svc.complete(uid, mode=mode)
        except ValidationError as e:
            raise GraphQLError(
                str(e.messages[0] if e.messages else "Invalid input"),
                extensions={"code": "BAD_INPUT"},
            )
        return Query().onboarding_state(info)

    @strawberry.mutation
    def mark_tour(self, info: Info, seen: bool) -> OnboardingState:
        uid = _user_id(info)
        onboarding_svc.mark_tour(uid, seen=seen)
        return Query().onboarding_state(info)

    # ===== Mutations: Preferencias de layout de Today =====
    @strawberry.mutation
    def update_today_layout(
        self,
        info: Info,
        order: Optional[List[str]] = None,
        hidden: Optional[List[str]] = None,
    ) -> TodayLayout:
        from django.core.exceptions import ValidationError

        uid = _user_id(info)
        try:
            layout = preferences_svc.update_today_layout(
                uid, order=order, hidden=hidden
            )
        except ValidationError as e:
            raise GraphQLError(
                str(e.messages[0] if e.messages else "Invalid input"),
                extensions={"code": "BAD_INPUT"},
            )
        return TodayLayout(order=layout["order"], hidden=layout["hidden"])

    @strawberry.mutation
    def reset_today_layout(self, info: Info) -> TodayLayout:
        uid = _user_id(info)
        layout = preferences_svc.reset_today_layout(uid)
        return TodayLayout(order=layout["order"], hidden=layout["hidden"])

    # ===== Mutations: Plugin Google Tasks =====
    @strawberry.mutation
    def google_tasks_auth_url(self, info: Info, return_to: str) -> str:
        """Return a URL to Google's OAuth consent screen.

        We do this as a GraphQL mutation (rather than a redirect endpoint)
        because browser top-level navigations can't carry the Authorization
        bearer token. The signed ``state`` embeds the user_id so the callback
        knows who is connecting without needing a session.
        """
        uid = _user_id(info)
        safe_return = return_to if return_to.startswith("/") else "/settings/plugins/google-tasks"
        try:
            return google_tasks_svc.build_authorization_url(uid, safe_return)
        except google_tasks_svc.GoogleTasksError as e:
            raise GraphQLError(str(e), extensions={"code": "GOOGLE_TASKS_ERROR"})

    @strawberry.mutation
    def import_google_tasks(
        self, info: Info, mappings: List[GoogleTasksImportMapping]
    ) -> GoogleTasksImportResult:
        uid = _user_id(info)
        try:
            result = google_tasks_svc.import_tasks(
                uid,
                [
                    {
                        "google_list_id": m.google_list_id,
                        "project_id": str(m.project_id) if m.project_id else None,
                        "new_project_name": m.new_project_name,
                    }
                    for m in mappings
                ],
            )
        except google_tasks_svc.NotConnectedError:
            raise GraphQLError(
                "Google Tasks is not connected",
                extensions={"code": "NOT_CONNECTED"},
            )
        except google_tasks_svc.GoogleTasksError as e:
            raise GraphQLError(str(e), extensions={"code": "GOOGLE_TASKS_ERROR"})
        return GoogleTasksImportResult(
            imported=result["imported"],
            skipped=result["skipped"],
            created_projects=result["created_projects"],
        )

    @strawberry.mutation
    def disconnect_google_tasks(self, info: Info) -> bool:
        uid = _user_id(info)
        google_tasks_svc.disconnect(uid)
        return True

    # ===== Mutations: Plugin de integración de calendario =====
    @strawberry.mutation
    def regenerate_calendar_feed_token(self, info: Info) -> str:
        """Rotate the ICS feed token and return the new subscription URL.
        Any previously shared URL stops working."""
        uid = _user_id(info)
        calendar_feed_svc.regenerate_feed_token(uid)
        return calendar_feed_svc.feed_url(uid)

    @strawberry.mutation
    def google_calendar_auth_url(self, info: Info, return_to: str) -> str:
        uid = _user_id(info)
        safe_return = (
            return_to
            if return_to.startswith("/")
            else "/settings/plugins/google-calendar"
        )
        try:
            return google_calendar_svc.build_authorization_url(uid, safe_return)
        except google_calendar_svc.GoogleTasksError as e:
            raise GraphQLError(str(e), extensions={"code": "GOOGLE_CALENDAR_ERROR"})

    @strawberry.mutation
    def disconnect_google_calendar(self, info: Info) -> bool:
        uid = _user_id(info)
        google_calendar_svc.disconnect(uid)
        return True

    @strawberry.mutation
    def sync_google_calendar_now(self, info: Info) -> CalendarSyncResult:
        uid = _user_id(info)
        try:
            res = google_calendar_svc.sync_user(uid)
        except google_calendar_svc.NotConnectedError:
            raise GraphQLError(
                "Google Calendar is not connected",
                extensions={"code": "NOT_CONNECTED"},
            )
        except google_calendar_svc.GoogleTasksError as e:
            raise GraphQLError(str(e), extensions={"code": "GOOGLE_CALENDAR_ERROR"})
        return CalendarSyncResult(
            created=res.get("created", 0),
            updated=res.get("updated", 0),
            deleted=res.get("deleted", 0),
        )

    @strawberry.mutation
    def connect_icloud_calendar(
        self, info: Info, apple_id: str, app_password: str
    ) -> bool:
        uid = _user_id(info)
        try:
            icloud_calendar_svc.connect(uid, apple_id, app_password)
        except icloud_calendar_svc.ICloudCalendarError as e:
            raise GraphQLError(str(e), extensions={"code": "ICLOUD_CALENDAR_ERROR"})
        return True

    @strawberry.mutation
    def disconnect_icloud_calendar(self, info: Info) -> bool:
        uid = _user_id(info)
        icloud_calendar_svc.disconnect(uid)
        return True

    @strawberry.mutation
    def sync_icloud_calendar_now(self, info: Info) -> int:
        uid = _user_id(info)
        try:
            res = icloud_calendar_svc.sync_user(uid)
        except icloud_calendar_svc.NotConnectedError:
            raise GraphQLError(
                "iCloud Calendar is not connected",
                extensions={"code": "NOT_CONNECTED"},
            )
        except icloud_calendar_svc.ICloudCalendarError as e:
            raise GraphQLError(str(e), extensions={"code": "ICLOUD_CALENDAR_ERROR"})
        return res.get("pushed", 0)

    # ===== Mutations: Bloqueadores de tareas =====
    @strawberry.mutation(name="addTaskBlocker")
    def add_task_blocker(self, info: Info, data: TaskBlockerInput) -> TaskBlocker:
        uid = _user_id(info)
        try:
            m = tasks_svc.add_task_blocker(
                uid,
                data.blocked_task_id,
                blocking_task_id=data.blocking_task_id or None,
                external_description=data.external_description or "",
            )
        except (NotFoundError, ValueError) as e:
            raise GraphQLError(str(e), extensions={"code": "BAD_INPUT"})
        return TaskBlocker.from_model(m)

    @strawberry.mutation(name="removeTaskBlocker")
    def remove_task_blocker(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        tasks_svc.remove_task_blocker(uid, id)
        return True

    # ===== Mutations: Cuenta =====
    @strawberry.mutation(name="deleteAccount")
    def delete_account(self, info: Info) -> bool:
        """Permanently delete the authenticated user's account + all their data
        (Apple App Store requirement). Erases app data then the Supabase auth
        user. Does NOT cancel Stripe — the client warns the user to cancel
        billing on the web first."""
        uid = _user_id(info)
        account_deletion.delete_account(uid)
        return True


CombinedQuery = merge_types(
    "Query",
    (
        Query,
        NotificationsQuery,
        AdminQuery,
        AdminBetaQuery,
        CmsAdminQuery,
        InAppNotificationsQuery,
        AdminAnnouncementsQuery,
        AdminFeedbackQuery,
    ),
)
CombinedMutation = merge_types(
    "Mutation",
    (
        Mutation,
        NotificationsMutation,
        AdminMutation,
        AdminBetaMutation,
        CmsAdminMutation,
        BillingMutation,
        AdminAnnouncementsMutation,
        FeedbackMutation,
        AdminFeedbackMutation,
    ),
)

from .interaction_tracking import InteractionTrackingExtension  # noqa: E402

schema = strawberry.Schema(
    query=CombinedQuery,
    mutation=CombinedMutation,
    extensions=[InteractionTrackingExtension],
)

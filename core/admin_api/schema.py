"""GraphQL surface for admin operations.

All admin fields go through `_admin_user_id(info)` which enforces
AccountProfile.is_admin == True. The frontend admin layout calls
`me { isAdmin }` to decide whether to render the panel; this enforces
the same check on every operation in case anyone hits GraphQL directly.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Optional

import strawberry
from django.db.models import Count, Max, Q
from django.utils import timezone
from graphql import GraphQLError
from strawberry.types import Info

from core.assistant.models import AccountProfile, Plan, UsageDay
from core.services import interactions as interactions_svc
from core.services import mcp_connections as mcp_connections_svc
from core.models import Activity as ActivityModel
from core.models import Idea as IdeaModel
from core.models import Project as ProjectModel
from core.models import Task as TaskModel
from core.notifications.models import (
    Notification,
    NotificationLink,
    NotificationSettings,
    NotificationStatus,
)

from .audit import record as audit_record
from .models import AdminAuditLog
from .permissions import _admin_user_id
from .supabase_admin import (
    SupabaseAdminError,
    SupabaseUser,
    fetch_all_users,
    get_user as supabase_get_user,
    get_users_map,
    list_users as supabase_list_users,
)

logger = logging.getLogger(__name__)

PlanEnum = strawberry.enum(Plan, name="UserPlan")


# ---------- Types ----------


@strawberry.type
class Me:
    user_id: strawberry.ID
    is_admin: bool


@strawberry.type
class UserCounts:
    projects: int
    tasks_open: int
    tasks_done: int
    ideas: int
    notes: int


@strawberry.type
class AdminUserSummary:
    user_id: strawberry.ID
    email: str
    plan: str
    is_admin: bool
    is_billing_exempt: bool
    created_at: Optional[dt.datetime]
    last_sign_in_at: Optional[dt.datetime]
    counts: UserCounts
    last_activity: Optional[dt.datetime]
    # Total "actions with effect" in the last 30 days, all channels combined.
    interactions_30d: int = 0


@strawberry.type
class AdminUserPage:
    users: list[AdminUserSummary]
    page: int
    per_page: int
    has_next: bool


@strawberry.type
class UsageDayPoint:
    date: dt.date
    messages_sent: int
    tokens_in: int
    tokens_out: int
    cost_usd_cents: int


@strawberry.type
class NotificationLinkInfo:
    channel: str
    verified: bool
    created: dt.datetime


@strawberry.type
class NotificationPrefs:
    digest_enabled: bool
    daily_digest_enabled: bool
    due_reminders_enabled: bool
    sleeping_alerts_enabled: bool
    is_admin: bool
    links: list[NotificationLinkInfo]


@strawberry.type
class AdminUserDetail:
    user_id: strawberry.ID
    email: str
    plan: str
    is_admin: bool
    is_billing_exempt: bool
    plan_renews_at: Optional[dt.datetime]
    stripe_customer_id: str
    stripe_subscription_id: str
    created_at: Optional[dt.datetime]
    last_sign_in_at: Optional[dt.datetime]
    email_confirmed_at: Optional[dt.datetime]
    banned_until: Optional[dt.datetime]
    counts: UserCounts
    last_activity: Optional[dt.datetime]
    usage_last_30d: list[UsageDayPoint]
    notifications: Optional[NotificationPrefs]
    # Interaction counts (actions with effect) over the last 30 days, split by
    # channel (web / mobile / connector / unknown). Counts only — no content.
    interactions_by_source: list[LabeledCount]
    interactions_30d_total: int


@strawberry.type
class AdminNotificationJob:
    id: strawberry.ID
    user_id: strawberry.ID
    channel: str
    kind: str
    dedupe_key: str
    body: str
    scheduled_for: Optional[dt.datetime]
    status: str
    attempts: int
    external_message_id: str
    error: str
    created: dt.datetime
    sent_at: Optional[dt.datetime]


@strawberry.type
class AdminNotificationJobPage:
    jobs: list[AdminNotificationJob]
    page: int
    per_page: int
    has_next: bool


@strawberry.type
class PlanCount:
    plan: str
    count: int


@strawberry.type
class JobStatusCount:
    status: str
    count: int


@strawberry.type
class LabeledCount:
    """Generic (label, count) pair for categorical breakdowns."""

    label: str
    count: int


@strawberry.type
class AdminMcpConnection:
    user_id: strawberry.ID
    client_id: str
    client_name: str
    connected_at: Optional[dt.datetime] = None


@strawberry.type
class AdminMcpConnectionEvent:
    user_id: strawberry.ID
    client_id: str
    client_name: str
    event: str
    created: dt.datetime


@strawberry.type
class AdminMcpStats:
    active_connections: int
    distinct_users: int
    by_client: list[LabeledCount]


@strawberry.type
class SeriesPoint:
    """One day's data point for a time series chart."""

    date: dt.date
    value: int


@strawberry.type
class RecentSignup:
    user_id: strawberry.ID
    email: str
    created_at: Optional[dt.datetime]
    plan: str


@strawberry.type
class AdminSystemStats:
    # Headline counts.
    total_users: int  # Real Supabase auth.users count.
    total_accounts: int  # AccountProfile rows — may include orphans, kept for back-compat.
    admins: int
    plan_counts: list[PlanCount]

    # Engagement.
    dau: int
    wau: int
    mau: int
    signups_series: list[SeriesPoint]  # last 30 days, by day
    activity_series: list[SeriesPoint]  # DAU per day, last 30 days
    activity_by_kind: list[LabeledCount]  # last 30 days

    # Product objects.
    project_state_counts: list[LabeledCount]
    tasks_open: int
    tasks_done_30d: int
    ideas_total: int

    # CMS.
    blog_posts_published: int
    blog_posts_draft: int
    pages_published: int

    # System health.
    pending_jobs: int
    failed_jobs: int
    job_status_counts: list[JobStatusCount]

    # Lists.
    recent_signups: list[RecentSignup]


@strawberry.type
class PlanPeriodBreakdown:
    plan: str  # "pro" | "studio"
    period: str  # "monthly" | "annual"
    count: int
    monthly_cents_each: int  # monthly-equivalent per subscriber (annual ÷ 12)
    total_monthly_cents: int  # count * monthly_cents_each


@strawberry.type
class UpcomingChurnRow:
    user_id: strawberry.ID
    email: str
    plan: str
    period: str
    plan_renews_at: Optional[dt.datetime]
    monthly_cents: int


@strawberry.type
class AdminBillingOverview:
    currency: str  # ISO 4217 lowercase ("usd", "mxn")
    is_test_mode: bool
    paying_subscribers: int
    mrr_cents: int
    arr_cents: int
    billing_exempt_count: int
    pending_cancellations: int
    breakdown: list[PlanPeriodBreakdown]
    upcoming_churn: list[UpcomingChurnRow]


@strawberry.type
class AdminSubscriberRow:
    user_id: strawberry.ID
    email: str
    plan: str
    period: str  # "monthly" | "annual" | "" when unknown
    monthly_cents: int
    plan_renews_at: Optional[dt.datetime]
    cancel_at_period_end: bool
    is_billing_exempt: bool
    stripe_customer_id: str
    stripe_subscription_id: str


@strawberry.type
class AdminSubscriberPage:
    rows: list[AdminSubscriberRow]
    page: int
    per_page: int
    has_next: bool
    total: int


@strawberry.type
class AdminAuditEntry:
    id: strawberry.ID
    actor_user_id: strawberry.ID
    action: str
    target_type: str
    target_id: str
    payload: strawberry.scalars.JSON
    created: dt.datetime


@strawberry.type
class AdminAuditPage:
    entries: list[AdminAuditEntry]
    page: int
    per_page: int
    has_next: bool


# ---------- Helpers ----------


def _parse_dt(value: Optional[str]) -> Optional[dt.datetime]:
    """Parsea timestamps ISO 8601 que llegan de Supabase auth.

    Supabase devuelve las fechas como texto (created_at, last_sign_in_at, etc.),
    a veces con sufijo ``Z`` que ``fromisoformat`` no acepta antes de 3.11; por
    eso lo normalizamos a ``+00:00``. Devuelve ``None`` ante valor vacío o mal
    formado para que un timestamp corrupto nunca tumbe el resolver.

    Args:
        value: Cadena de fecha ISO 8601 de Supabase, o ``None``.

    Returns:
        El ``datetime`` parseado, o ``None`` si está vacío o es inválido.
    """
    if not value:
        return None
    try:
        # Supabase returns ISO 8601 with Z or +00:00
        normalized = value.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None


# FIXME: capas — ORM directo en helper de resolver; mover a admin_api/services/user_stats.py
def _build_counts_for(user_id: uuid.UUID) -> UserCounts:
    """Cuenta los objetos de producto de un solo usuario (vista de detalle).

    Variante por-usuario que emite una query ``COUNT`` por entidad. Se usa en
    los caminos de un único usuario (``adminUser``, mutaciones que devuelven el
    summary); para listas usar ``_bulk_counts`` y evitar el N+1.

    Args:
        user_id: UUID del usuario a contar.

    Returns:
        ``UserCounts`` con proyectos, tareas abiertas/hechas, ideas y notas.
    """
    projects = ProjectModel.objects.filter(user_id=user_id).count()
    tasks_open = TaskModel.objects.filter(user_id=user_id, done=False).count()
    tasks_done = TaskModel.objects.filter(user_id=user_id, done=True).count()
    ideas = IdeaModel.objects.filter(user_id=user_id).count()
    notes = ActivityModel.objects.filter(user_id=user_id, kind="note").count()
    return UserCounts(
        projects=projects,
        tasks_open=tasks_open,
        tasks_done=tasks_done,
        ideas=ideas,
        notes=notes,
    )


# FIXME: capas — ORM directo en helper de resolver; mover a admin_api/services/user_stats.py
def _bulk_counts(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, UserCounts]:
    """Cuenta objetos de producto de muchos usuarios de una vez (lista admin).

    Versión bulk de ``_build_counts_for``: agrupa con ``annotate(Count)`` para
    resolver cada entidad en UNA query en vez de una por usuario, lo que evita
    el N+1 al pintar la tabla paginada de ``adminUsers``.

    Args:
        user_ids: UUIDs de la página actual de usuarios.

    Returns:
        Mapa ``user_id -> UserCounts``; los usuarios sin filas en una entidad
        quedan en 0 vía ``.get(uid, 0)``. Vacío si ``user_ids`` está vacío.
    """
    if not user_ids:
        return {}
    projects = dict(
        ProjectModel.objects.filter(user_id__in=user_ids)
        .values_list("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )
    tasks_open = dict(
        TaskModel.objects.filter(user_id__in=user_ids, done=False)
        .values_list("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )
    tasks_done = dict(
        TaskModel.objects.filter(user_id__in=user_ids, done=True)
        .values_list("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )
    ideas = dict(
        IdeaModel.objects.filter(user_id__in=user_ids)
        .values_list("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )
    notes = dict(
        ActivityModel.objects.filter(user_id__in=user_ids, kind="note")
        .values_list("user_id")
        .annotate(c=Count("id"))
        .values_list("user_id", "c")
    )
    return {
        uid: UserCounts(
            projects=projects.get(uid, 0),
            tasks_open=tasks_open.get(uid, 0),
            tasks_done=tasks_done.get(uid, 0),
            ideas=ideas.get(uid, 0),
            notes=notes.get(uid, 0),
        )
        for uid in user_ids
    }


def _last_activity_map(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dt.datetime]:
    """Última actividad por usuario, bulk, para la lista admin.

    Resuelve el ``MAX(created)`` de Activity de todos los usuarios de la página
    en UNA query (mismo motivo que ``_bulk_counts``: evitar N+1).

    Args:
        user_ids: UUIDs de la página actual.

    Returns:
        Mapa ``user_id -> datetime`` de la actividad más reciente. Los usuarios
        sin actividad se omiten (no aparecen en el dict).
    """
    if not user_ids:
        return {}
    rows = (
        ActivityModel.objects.filter(user_id__in=user_ids)
        .values_list("user_id")
        .annotate(latest=Max("created"))
        .values_list("user_id", "latest")
    )
    return {uid: latest for uid, latest in rows if latest is not None}


def _build_summary(
    s_user: SupabaseUser,
    profile: Optional[AccountProfile],
    counts: UserCounts,
    last_activity: Optional[dt.datetime],
    interactions_30d: int = 0,
) -> AdminUserSummary:
    """Ensambla el ``AdminUserSummary`` cruzando Supabase auth y el perfil local.

    La identidad (email, fechas de alta/login) vive en Supabase mientras que el
    plan/flags viven en ``AccountProfile``; este helper combina ambas fuentes y
    asume defaults de cuenta gratuita (plan FREE, flags ``False``) cuando el
    usuario aún no tiene perfil local. Counts/last_activity/interactions se pasan
    ya calculados (en bulk) para no re-consultar por usuario.

    Args:
        s_user: Usuario de Supabase auth (fuente de identidad).
        profile: ``AccountProfile`` local, o ``None`` si no existe todavía.
        counts: Conteos de objetos ya resueltos para este usuario.
        last_activity: Timestamp de última actividad, o ``None``.
        interactions_30d: Total de interacciones de 30 días (todos los canales).

    Returns:
        El ``AdminUserSummary`` listo para la respuesta GraphQL.
    """
    return AdminUserSummary(
        user_id=strawberry.ID(str(s_user.id)),
        email=s_user.email,
        plan=(profile.plan if profile else Plan.FREE.value),
        is_admin=bool(profile.is_admin) if profile else False,
        is_billing_exempt=bool(profile.is_billing_exempt) if profile else False,
        created_at=_parse_dt(s_user.created_at),
        last_sign_in_at=_parse_dt(s_user.last_sign_in_at),
        counts=counts,
        last_activity=last_activity,
        interactions_30d=interactions_30d,
    )


# ---------- Query ----------


@strawberry.type
class AdminQuery:
    @strawberry.field
    def me(self, info: Info) -> Me:
        """Devuelve la identidad del solicitante y si es admin.

        Es el único campo de este schema que NO exige ser admin: el frontend lo
        consulta primero para decidir si pinta el panel de administración. Por
        eso solo requiere estar autenticado.

        Args:
            info: Contexto GraphQL; debe traer ``user_id`` (JWT de Supabase).

        Returns:
            ``Me`` con el ``user_id`` y el flag ``is_admin``.

        Raises:
            GraphQLError: ``UNAUTHENTICATED`` si no hay usuario en el contexto.
        """
        user_id = getattr(info.context, "user_id", None)
        if not user_id:
            raise GraphQLError(
                "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
            )
        is_admin = (
            AccountProfile.objects.filter(user_id=user_id)
            .values_list("is_admin", flat=True)
            .first()
        )
        return Me(user_id=strawberry.ID(str(user_id)), is_admin=bool(is_admin))

    @strawberry.field(name="adminUsers")
    def admin_users(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 25,
        email_contains: Optional[str] = None,
        plan: Optional[str] = None,
        admins_only: bool = False,
    ) -> AdminUserPage:
        """Lista paginada de usuarios para el panel admin.

        Pagina sobre Supabase auth (fuente de verdad de usuarios) y enriquece
        cada fila con plan/flags del perfil local y conteos/actividad/interac-
        ciones resueltos en bulk para evitar N+1. Los filtros ``email_contains``,
        ``plan`` y ``admins_only`` se aplican EN MEMORIA sobre la página ya
        traída: Supabase no ofrece búsqueda bulk por esos campos, así que el
        filtrado es local a la página (tradeoff conocido, mismo patrón que
        ``adminSubscribers``).

        Args:
            info: Contexto GraphQL; debe ser admin.
            page: Página 1-based.
            per_page: Tamaño de página (acotado a 1..100).
            email_contains: Subcadena case-insensitive para filtrar por email.
            plan: Filtra por plan exacto (los sin perfil cuentan como FREE).
            admins_only: Si ``True``, solo usuarios con perfil admin.

        Returns:
            ``AdminUserPage`` con los summaries y metadatos de paginación.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``)
                o ``SUPABASE_ADMIN_ERROR`` si falla la API admin de Supabase.
        """
        _admin_user_id(info)
        # NOTE: paginación duplicada — extraer paginate() + constantes
        per_page = max(1, min(per_page, 100))
        page = max(1, page)

        try:
            page_result = supabase_list_users(page=page, per_page=per_page)
        except SupabaseAdminError as e:
            raise GraphQLError(
                f"Supabase admin API error: {e}",
                extensions={"code": "SUPABASE_ADMIN_ERROR"},
            )

        s_users = page_result.users

        if email_contains:
            needle = email_contains.strip().lower()
            s_users = [u for u in s_users if needle in u.email.lower()]

        user_ids = [u.id for u in s_users]
        profiles = {
            p.user_id: p
            for p in AccountProfile.objects.filter(user_id__in=user_ids)
        }

        if plan:
            allowed = plan.lower()
            s_users = [
                u
                for u in s_users
                if (profiles.get(u.id).plan if profiles.get(u.id) else Plan.FREE.value)
                == allowed
            ]
        if admins_only:
            s_users = [
                u
                for u in s_users
                if profiles.get(u.id) and profiles[u.id].is_admin
            ]

        kept_ids = [u.id for u in s_users]
        counts_map = _bulk_counts(kept_ids)
        last_act_map = _last_activity_map(kept_ids)
        interactions_map = interactions_svc.bulk_interactions_total(kept_ids, days=30)

        zero_counts = UserCounts(
            projects=0, tasks_open=0, tasks_done=0, ideas=0, notes=0
        )
        summaries = [
            _build_summary(
                u,
                profiles.get(u.id),
                counts_map.get(u.id, zero_counts),
                last_act_map.get(u.id),
                interactions_map.get(u.id, 0),
            )
            for u in s_users
        ]

        # has_next se decide con la página CRUDA de Supabase (antes de filtrar en
        # memoria): si Supabase devolvió la página llena asumimos que hay más.
        has_next = len(page_result.users) >= per_page

        return AdminUserPage(
            users=summaries,
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="adminUser")
    def admin_user(self, info: Info, user_id: strawberry.ID) -> AdminUserDetail:
        """Ficha completa de un usuario para el detalle admin.

        Reúne en una sola respuesta todo lo disperso de un usuario: identidad de
        Supabase auth, plan/flags/datos de Stripe del perfil local, conteos de
        objetos, uso de los últimos 30 días, preferencias de notificaciones e
        interacciones desglosadas por canal. Más pesado que el summary de lista,
        por eso es un resolver de un solo usuario.

        Args:
            info: Contexto GraphQL; debe ser admin.
            user_id: ID del usuario a inspeccionar.

        Returns:
            ``AdminUserDetail`` con todas las secciones de la ficha.

        Raises:
            GraphQLError: ``BAD_INPUT`` si el ``user_id`` no es UUID válido;
                ``SUPABASE_ADMIN_ERROR`` si falla la API admin de Supabase;
                ``NOT_FOUND`` si el usuario no existe en Supabase; o el error de
                ``_admin_user_id`` si el solicitante no es admin.
        """
        _admin_user_id(info)
        try:
            uid = uuid.UUID(str(user_id))
        except ValueError:
            raise GraphQLError("Invalid user_id", extensions={"code": "BAD_INPUT"})

        try:
            s_user = supabase_get_user(uid)
        except SupabaseAdminError as e:
            raise GraphQLError(
                f"Supabase admin API error: {e}",
                extensions={"code": "SUPABASE_ADMIN_ERROR"},
            )
        if s_user is None:
            raise GraphQLError("User not found", extensions={"code": "NOT_FOUND"})

        profile = AccountProfile.objects.filter(user_id=uid).first()
        counts = _build_counts_for(uid)
        last_activity = (
            ActivityModel.objects.filter(user_id=uid)
            .order_by("-created")
            .values_list("created", flat=True)
            .first()
        )

        since = dt.date.today() - dt.timedelta(days=30)
        usage_rows = list(
            UsageDay.objects.filter(user_id=uid, date__gte=since).order_by("date")
        )
        usage = [
            UsageDayPoint(
                date=r.date,
                messages_sent=r.messages_sent,
                tokens_in=r.tokens_in,
                tokens_out=r.tokens_out,
                cost_usd_cents=r.cost_usd_cents,
            )
            for r in usage_rows
        ]

        by_source = interactions_svc.interactions_by_source(uid, days=30)
        interactions_by_source = [
            LabeledCount(label=label, count=by_source.get(label, 0))
            for label in (
                interactions_svc.WEB,
                interactions_svc.MOBILE,
                interactions_svc.CONNECTOR,
                interactions_svc.UNKNOWN,
            )
        ]
        interactions_30d_total = sum(by_source.values())

        notif_settings = NotificationSettings.objects.filter(user_id=uid).first()
        if notif_settings:
            links_qs = NotificationLink.objects.filter(user_id=uid)
            link_infos = [
                NotificationLinkInfo(
                    channel=l.channel,
                    verified=bool(l.verified_at),
                    created=l.created,
                )
                for l in links_qs
            ]
            prefs = NotificationPrefs(
                digest_enabled=notif_settings.digest_enabled,
                daily_digest_enabled=notif_settings.daily_digest_enabled,
                due_reminders_enabled=notif_settings.due_reminders_enabled,
                sleeping_alerts_enabled=notif_settings.sleeping_alerts_enabled,
                is_admin=notif_settings.is_admin,
                links=link_infos,
            )
        else:
            prefs = None

        return AdminUserDetail(
            user_id=strawberry.ID(str(uid)),
            email=s_user.email,
            plan=(profile.plan if profile else Plan.FREE.value),
            is_admin=bool(profile.is_admin) if profile else False,
            is_billing_exempt=bool(profile.is_billing_exempt) if profile else False,
            plan_renews_at=(profile.plan_renews_at if profile else None),
            stripe_customer_id=(profile.stripe_customer_id if profile else ""),
            stripe_subscription_id=(
                profile.stripe_subscription_id if profile else ""
            ),
            created_at=_parse_dt(s_user.created_at),
            last_sign_in_at=_parse_dt(s_user.last_sign_in_at),
            email_confirmed_at=_parse_dt(s_user.email_confirmed_at),
            banned_until=_parse_dt(s_user.banned_until),
            counts=counts,
            last_activity=last_activity,
            usage_last_30d=usage,
            notifications=prefs,
            interactions_by_source=interactions_by_source,
            interactions_30d_total=interactions_30d_total,
        )

    @strawberry.field(name="adminNotificationJobs")
    def admin_notification_jobs(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 50,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        kind: Optional[str] = None,
        user_id: Optional[strawberry.ID] = None,
    ) -> AdminNotificationJobPage:
        """Cola de notificaciones paginada y filtrable para depurar envíos.

        Permite al admin inspeccionar los jobs de la tabla ``Notification`` (su
        estado, intentos, error, etc.) filtrando por estado/canal/tipo/usuario.
        Pide ``per_page + 1`` filas para saber si hay página siguiente sin un
        ``COUNT`` extra.

        Args:
            info: Contexto GraphQL; debe ser admin.
            page: Página 1-based.
            per_page: Tamaño de página (acotado a 1..200).
            status: Filtra por estado (se normaliza a minúsculas).
            channel: Filtra por canal exacto.
            kind: Filtra por tipo exacto.
            user_id: Filtra por destinatario.

        Returns:
            ``AdminNotificationJobPage`` con los jobs y paginación.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)
        # NOTE: paginación duplicada — extraer paginate() + constantes
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = Notification.objects.all()
        if status:
            qs = qs.filter(status=status.lower())
        if channel:
            qs = qs.filter(channel=channel)
        if kind:
            qs = qs.filter(kind=kind)
        if user_id:
            qs = qs.filter(user_id=uuid.UUID(str(user_id)))

        rows = list(qs[offset : offset + per_page + 1])
        has_next = len(rows) > per_page
        rows = rows[:per_page]
        return AdminNotificationJobPage(
            jobs=[
                AdminNotificationJob(
                    id=strawberry.ID(str(n.id)),
                    user_id=strawberry.ID(str(n.user_id)),
                    channel=n.channel,
                    kind=n.kind,
                    dedupe_key=n.dedupe_key,
                    body=n.body,
                    scheduled_for=n.scheduled_for,
                    status=n.status,
                    attempts=n.attempts,
                    external_message_id=n.external_message_id,
                    error=n.error,
                    created=n.created,
                    sent_at=n.sent_at,
                )
                for n in rows
            ],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    # TODO: refactor — mover esta agregación (186 líneas, 5 niveles) a admin_api/services/stats.py (ver AUDITORIA_CODIGO.md)
    @strawberry.field(name="adminSystemStats")
    def admin_system_stats(self, info: Info) -> AdminSystemStats:
        """Panel global de métricas del sistema (la "home" del admin).

        Agrega de golpe todas las cifras del dashboard: usuarios y planes,
        engagement (DAU/WAU/MAU + series diarias), objetos de producto, CMS y
        salud de la cola de notificaciones. Es deliberadamente caro y se sirve a
        una sola pantalla; los usuarios salen de Supabase auth (fuente real) y el
        resto del ORM local. Si Supabase falla se degrada a una lista vacía en
        vez de romper toda la query.

        Args:
            info: Contexto GraphQL; debe ser admin.

        Returns:
            ``AdminSystemStats`` con todas las secciones del panel.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
                Un fallo de Supabase NO lanza: se loguea y degrada.
        """
        _admin_user_id(info)
        now = timezone.now()
        today = now.date()
        # Ventanas de engagement: DAU/WAU/MAU = actividad en los últimos 1/7/30 días.
        d1 = now - dt.timedelta(days=1)
        d7 = now - dt.timedelta(days=7)
        d30 = now - dt.timedelta(days=30)
        day0 = today - dt.timedelta(days=29)  # 30-day window inclusive of today

        # --- Users (real source: Supabase auth) ----------------------------
        try:
            supabase_users = fetch_all_users()
        except SupabaseAdminError as e:
            logger.warning("adminSystemStats: supabase fetch failed: %s", e)
            supabase_users = []
        total_users = len(supabase_users)

        signup_buckets: dict[dt.date, int] = {
            day0 + dt.timedelta(days=i): 0 for i in range(30)
        }
        for u in supabase_users:
            if not u.created_at:
                continue
            try:
                created = dt.datetime.fromisoformat(
                    u.created_at.replace("Z", "+00:00")
                )
            except ValueError:
                continue
            d = created.date()
            if d in signup_buckets:
                signup_buckets[d] += 1
        signups_series = [
            SeriesPoint(date=d, value=signup_buckets[d])
            for d in sorted(signup_buckets)
        ]

        # Recent signups: top 10 by created_at desc, joined with plan.
        sorted_users = sorted(
            supabase_users,
            key=lambda u: u.created_at or "",
            reverse=True,
        )[:10]
        recent_uids = [u.id for u in sorted_users]
        plan_by_uid = {
            p.user_id: p.plan
            for p in AccountProfile.objects.filter(user_id__in=recent_uids)
        }
        recent_signups: list[RecentSignup] = []
        for u in sorted_users:
            created_dt: Optional[dt.datetime] = None
            if u.created_at:
                try:
                    created_dt = dt.datetime.fromisoformat(
                        u.created_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    created_dt = None
            recent_signups.append(
                RecentSignup(
                    user_id=strawberry.ID(str(u.id)),
                    email=u.email,
                    created_at=created_dt,
                    plan=plan_by_uid.get(u.id, Plan.FREE.value),
                )
            )

        # --- Local accounts / plans ---------------------------------------
        total_accounts = AccountProfile.objects.count()
        admins = AccountProfile.objects.filter(is_admin=True).count()
        plan_rows = (
            AccountProfile.objects.values("plan")
            .annotate(c=Count("user_id"))
            .order_by("plan")
        )
        plan_counts = [
            PlanCount(plan=row["plan"], count=row["c"]) for row in plan_rows
        ]

        # --- Engagement ---------------------------------------------------
        # DAU/WAU/MAU = usuarios DISTINTOS con actividad en la ventana 1/7/30 días.
        dau = (
            ActivityModel.objects.filter(created__gte=d1)
            .values("user_id")
            .distinct()
            .count()
        )
        wau = (
            ActivityModel.objects.filter(created__gte=d7)
            .values("user_id")
            .distinct()
            .count()
        )
        mau = (
            ActivityModel.objects.filter(created__gte=d30)
            .values("user_id")
            .distinct()
            .count()
        )

        # DAU per day for the last 30 days. Se usa un set por día para deduplicar
        # usuarios en Python (un solo recorrido) en lugar de 30 queries distinct.
        activity_buckets: dict[dt.date, set[uuid.UUID]] = {
            day0 + dt.timedelta(days=i): set() for i in range(30)
        }
        for row in ActivityModel.objects.filter(created__gte=d30).values(
            "user_id", "created"
        ):
            d = row["created"].date()
            if d in activity_buckets:
                activity_buckets[d].add(row["user_id"])
        activity_series = [
            SeriesPoint(date=d, value=len(activity_buckets[d]))
            for d in sorted(activity_buckets)
        ]

        # Activity-by-kind in the last 30 days.
        kind_rows = (
            ActivityModel.objects.filter(created__gte=d30)
            .values("kind")
            .annotate(c=Count("id"))
            .order_by("-c")
        )
        activity_by_kind = [
            LabeledCount(label=row["kind"], count=row["c"]) for row in kind_rows
        ]

        # --- Product objects ----------------------------------------------
        proj_rows = (
            ProjectModel.objects.values("status")
            .annotate(c=Count("id"))
            .order_by("status")
        )
        project_state_counts = [
            LabeledCount(label=row["status"], count=row["c"]) for row in proj_rows
        ]
        tasks_open = TaskModel.objects.filter(done=False).count()
        tasks_done_30d = TaskModel.objects.filter(
            done=True, completed_at__gte=d30
        ).count()
        ideas_total = IdeaModel.objects.count()

        # --- CMS -----------------------------------------------------------
        from core.cms.models import BlogPost, Page, PostStatus as CmsStatus

        blog_published = BlogPost.objects.filter(status=CmsStatus.PUBLISHED).count()
        blog_draft = BlogPost.objects.filter(status=CmsStatus.DRAFT).count()
        pages_published = Page.objects.filter(status=CmsStatus.PUBLISHED).count()

        # --- System health -------------------------------------------------
        pending_jobs = Notification.objects.filter(
            status=NotificationStatus.PENDING
        ).count()
        failed_jobs = Notification.objects.filter(
            status=NotificationStatus.FAILED
        ).count()
        status_rows = (
            Notification.objects.values("status")
            .annotate(c=Count("id"))
            .order_by("status")
        )
        job_status_counts = [
            JobStatusCount(status=r["status"], count=r["c"]) for r in status_rows
        ]

        return AdminSystemStats(
            total_users=total_users,
            total_accounts=total_accounts,
            admins=admins,
            plan_counts=plan_counts,
            dau=dau,
            wau=wau,
            mau=mau,
            signups_series=signups_series,
            activity_series=activity_series,
            activity_by_kind=activity_by_kind,
            project_state_counts=project_state_counts,
            tasks_open=tasks_open,
            tasks_done_30d=tasks_done_30d,
            ideas_total=ideas_total,
            blog_posts_published=blog_published,
            blog_posts_draft=blog_draft,
            pages_published=pages_published,
            pending_jobs=pending_jobs,
            failed_jobs=failed_jobs,
            job_status_counts=job_status_counts,
            recent_signups=recent_signups,
        )

    @strawberry.field(name="adminBillingOverview")
    def admin_billing_overview(self, info: Info) -> AdminBillingOverview:
        """Resumen de ingresos recurrentes y churn próxima.

        Calcula MRR/ARR y el desglose por (plan, periodo) sumando el equivalente
        mensual de cada suscripción de pago activa (excluye exentos y sin
        ``stripe_subscription_id``). El ``price_id`` se colapsa en periodo vía
        ``period_for_price`` para que la UI vea una matriz limpia de 4 filas. Los
        emails de la churn próxima se traen en bloque (best-effort) y quedan ""
        si Supabase falla, para no tumbar el panel.

        Args:
            info: Contexto GraphQL; debe ser admin.

        Returns:
            ``AdminBillingOverview`` con MRR/ARR, conteos y churn próxima.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)

        from django.conf import settings as dj_settings

        from core.billing.plans import (
            amount_cents_for_price,
            is_stripe_test_mode,
            monthly_cents_for_price,
            period_for_price,
        )

        paid_plans = [Plan.PRO.value, Plan.STUDIO.value]
        paying_qs = AccountProfile.objects.filter(
            plan__in=paid_plans,
            is_billing_exempt=False,
        ).exclude(stripe_subscription_id="")

        # Aggregate breakdown by (plan, price_id) — we collapse price_id into
        # period via period_for_price() so the UI sees a clean 4-row matrix.
        bucket: dict[tuple[str, str], dict] = {}
        mrr_cents = 0
        paying_count = 0
        for plan, price_id in paying_qs.values_list("plan", "stripe_price_id"):
            period = period_for_price(price_id) or "unknown"
            monthly = monthly_cents_for_price(price_id)
            key = (plan, period)
            slot = bucket.setdefault(
                key,
                {"count": 0, "monthly_each": monthly, "total": 0},
            )
            slot["count"] += 1
            slot["total"] += monthly
            # Keep the "each" value stable even if some rows have monthly=0
            # (unconfigured amount) — prefer the first non-zero we see.
            if slot["monthly_each"] == 0 and monthly > 0:
                slot["monthly_each"] = monthly
            mrr_cents += monthly
            paying_count += 1

        breakdown = [
            PlanPeriodBreakdown(
                plan=plan,
                period=period,
                count=slot["count"],
                monthly_cents_each=slot["monthly_each"],
                total_monthly_cents=slot["total"],
            )
            for (plan, period), slot in sorted(bucket.items())
        ]

        billing_exempt_count = AccountProfile.objects.filter(
            is_billing_exempt=True,
        ).exclude(plan=Plan.FREE.value).count()

        pending_cancel_qs = paying_qs.filter(cancel_at_period_end=True).order_by(
            "plan_renews_at"
        )
        pending_cancellations = pending_cancel_qs.count()

        # Upcoming churn — top 20 by soonest renewal, fetch emails in one go.
        churn_rows = list(pending_cancel_qs[:20])
        churn_uids = [r.user_id for r in churn_rows]
        users_map = {}
        if churn_uids:
            try:
                users_map = get_users_map(churn_uids)
            except SupabaseAdminError as e:
                logger.warning("adminBillingOverview: supabase fetch failed: %s", e)

        upcoming_churn = [
            UpcomingChurnRow(
                user_id=strawberry.ID(str(r.user_id)),
                email=(users_map.get(r.user_id).email if users_map.get(r.user_id) else ""),
                plan=r.plan,
                period=period_for_price(r.stripe_price_id) or "unknown",
                plan_renews_at=r.plan_renews_at,
                monthly_cents=monthly_cents_for_price(r.stripe_price_id),
            )
            for r in churn_rows
        ]

        return AdminBillingOverview(
            currency=(getattr(dj_settings, "STRIPE_CURRENCY", "usd") or "usd").lower(),
            is_test_mode=is_stripe_test_mode(),
            paying_subscribers=paying_count,
            mrr_cents=mrr_cents,
            arr_cents=mrr_cents * 12,
            billing_exempt_count=billing_exempt_count,
            pending_cancellations=pending_cancellations,
            breakdown=breakdown,
            upcoming_churn=upcoming_churn,
        )

    @strawberry.field(name="adminSubscribers")
    def admin_subscribers(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 50,
        plan: Optional[str] = None,
        period: Optional[str] = None,
        email_contains: Optional[str] = None,
        include_exempt: bool = False,
    ) -> AdminSubscriberPage:
        """Lista paginada de suscriptores de pago con filtros.

        Pagina sobre ``AccountProfile`` (donde vive el estado de billing) y trae
        los emails de la página en bloque desde Supabase. Filtros por plan y
        periodo se hacen en SQL; el de email se aplica EN MEMORIA post-fetch
        porque Supabase no expone búsqueda bulk por email (mismo tradeoff que
        ``adminUsers``).

        Args:
            info: Contexto GraphQL; debe ser admin.
            page: Página 1-based.
            per_page: Tamaño de página (acotado a 1..200).
            plan: Filtra por plan válido (se ignora si no es un Plan conocido).
            period: ``"monthly"``/``"annual"``, mapeado a price_ids de settings.
            email_contains: Subcadena case-insensitive (filtrado local).
            include_exempt: Si ``True``, incluye exentos y sin suscripción.

        Returns:
            ``AdminSubscriberPage`` con las filas, paginación y total.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)

        from core.billing.plans import (
            monthly_cents_for_price,
            period_for_price,
        )

        # NOTE: paginación duplicada — extraer paginate() + constantes
        per_page = max(1, min(per_page, 200))
        page = max(1, page)

        paid_plans = [Plan.PRO.value, Plan.STUDIO.value]
        qs = AccountProfile.objects.filter(plan__in=paid_plans)
        if not include_exempt:
            qs = qs.filter(is_billing_exempt=False).exclude(stripe_subscription_id="")
        if plan:
            normalized_plan = plan.lower()
            if normalized_plan in {p.value for p in Plan}:
                qs = qs.filter(plan=normalized_plan)
        if period:
            # Filter by period via the underlying price_id columns.
            normalized_period = period.lower()
            from django.conf import settings as dj_settings

            ids: list[str] = []
            if normalized_period == "monthly":
                ids = [
                    getattr(dj_settings, "STRIPE_PRICE_PRO_MONTHLY", ""),
                    getattr(dj_settings, "STRIPE_PRICE_STUDIO_MONTHLY", ""),
                ]
            elif normalized_period == "annual":
                ids = [
                    getattr(dj_settings, "STRIPE_PRICE_PRO_ANNUAL", ""),
                    getattr(dj_settings, "STRIPE_PRICE_STUDIO_ANNUAL", ""),
                ]
            ids = [i for i in ids if i]
            if ids:
                qs = qs.filter(stripe_price_id__in=ids)

        qs = qs.order_by("-plan_renews_at", "user_id")

        total = qs.count()
        offset = (page - 1) * per_page
        rows = list(qs[offset : offset + per_page])

        # Bulk-fetch emails for just this page.
        uids = [r.user_id for r in rows]
        users_map = {}
        if uids:
            try:
                users_map = get_users_map(uids)
            except SupabaseAdminError as e:
                logger.warning("adminSubscribers: supabase fetch failed: %s", e)

        # Apply email filter post-fetch (Supabase doesn't expose query-by-email
        # bulk lookup; we filter the page locally — known tradeoff, same pattern
        # as adminUsers).
        if email_contains:
            needle = email_contains.strip().lower()
            rows = [
                r
                for r in rows
                if users_map.get(r.user_id)
                and needle in users_map[r.user_id].email.lower()
            ]

        result_rows = [
            AdminSubscriberRow(
                user_id=strawberry.ID(str(r.user_id)),
                email=(users_map.get(r.user_id).email if users_map.get(r.user_id) else ""),
                plan=r.plan,
                period=period_for_price(r.stripe_price_id) or "",
                monthly_cents=monthly_cents_for_price(r.stripe_price_id),
                plan_renews_at=r.plan_renews_at,
                cancel_at_period_end=r.cancel_at_period_end,
                is_billing_exempt=r.is_billing_exempt,
                stripe_customer_id=r.stripe_customer_id,
                stripe_subscription_id=r.stripe_subscription_id,
            )
            for r in rows
        ]

        return AdminSubscriberPage(
            rows=result_rows,
            page=page,
            per_page=per_page,
            has_next=(offset + per_page) < total,
            total=total,
        )

    @strawberry.field(name="adminAuditLog")
    def admin_audit_log(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 50,
        actor_user_id: Optional[strawberry.ID] = None,
        action_contains: Optional[str] = None,
        target_user_id: Optional[strawberry.ID] = None,
    ) -> AdminAuditPage:
        """Bitácora de auditoría admin, paginada y filtrable.

        Expone las entradas de ``AdminAuditLog`` (qué admin hizo qué, sobre qué
        objeto) para investigar acciones. El filtro por usuario objetivo cubre
        tanto ``target_type="user"`` como ``"account_profile"`` porque distintas
        acciones registran el mismo UUID bajo uno u otro tipo.

        Args:
            info: Contexto GraphQL; debe ser admin.
            page: Página 1-based.
            per_page: Tamaño de página (acotado a 1..200).
            actor_user_id: Filtra por el admin que ejecutó la acción.
            action_contains: Subcadena (icontains) sobre el nombre de acción.
            target_user_id: Filtra por usuario objetivo (user o account_profile).

        Returns:
            ``AdminAuditPage`` con las entradas y paginación.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)
        # NOTE: paginación duplicada — extraer paginate() + constantes
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = AdminAuditLog.objects.all()
        if actor_user_id:
            qs = qs.filter(actor_user_id=uuid.UUID(str(actor_user_id)))
        if action_contains:
            qs = qs.filter(action__icontains=action_contains)
        if target_user_id:
            qs = qs.filter(
                Q(target_type="user", target_id=str(target_user_id))
                | Q(target_type="account_profile", target_id=str(target_user_id))
            )

        items = list(qs[offset : offset + per_page + 1])
        has_next = len(items) > per_page
        items = items[:per_page]
        return AdminAuditPage(
            entries=[
                AdminAuditEntry(
                    id=strawberry.ID(str(e.id)),
                    actor_user_id=strawberry.ID(str(e.actor_user_id)),
                    action=e.action,
                    target_type=e.target_type,
                    target_id=e.target_id,
                    payload=e.payload or {},
                    created=e.created,
                )
                for e in items
            ],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="adminMcpConnections")
    def admin_mcp_connections(
        self, info: Info, limit: int = 50
    ) -> list[AdminMcpConnection]:
        _admin_user_id(info)
        return [
            AdminMcpConnection(
                user_id=strawberry.ID(str(c["user_id"])),
                client_id=c["client_id"],
                client_name=c["client_name"],
                connected_at=c["connected_at"],
            )
            for c in mcp_connections_svc.list_all_connections(limit=limit)
        ]

    @strawberry.field(name="adminMcpConnectionEvents")
    def admin_mcp_connection_events(
        self, info: Info, limit: int = 50
    ) -> list[AdminMcpConnectionEvent]:
        _admin_user_id(info)
        return [
            AdminMcpConnectionEvent(
                user_id=strawberry.ID(str(e.user_id)),
                client_id=e.client_id,
                client_name=e.client_name,
                event=e.event,
                created=e.created,
            )
            for e in mcp_connections_svc.recent_events(limit=limit)
        ]

    @strawberry.field(name="adminMcpStats")
    def admin_mcp_stats(self, info: Info) -> AdminMcpStats:
        _admin_user_id(info)
        s = mcp_connections_svc.connection_stats()
        return AdminMcpStats(
            active_connections=s["active_connections"],
            distinct_users=s["distinct_users"],
            by_client=[
                LabeledCount(label=k, count=v) for k, v in s["by_client"].items()
            ],
        )


# ---------- Mutations ----------


@strawberry.type
class AdminMutation:
    @strawberry.mutation(name="adminRevokeMcpConnection")
    def admin_revoke_mcp_connection(
        self, info: Info, user_id: strawberry.ID, client_id: str
    ) -> bool:
        """Revoca una conexión MCP de un usuario (acción de admin).

        Fuerza la desconexión de un cliente MCP por seguridad/soporte y deja
        rastro en la bitácora de auditoría.

        Args:
            info: Contexto GraphQL; debe ser admin.
            user_id: Dueño de la conexión a revocar.
            client_id: Cliente MCP a desconectar.

        Returns:
            ``True`` si se revocó al menos una conexión.

        Raises:
            GraphQLError: ``BAD_INPUT`` si ``user_id`` no es UUID válido, o el
                error de ``_admin_user_id`` si el solicitante no es admin.
        """
        actor = _admin_user_id(info)
        import uuid as _uuid

        try:
            uid = _uuid.UUID(str(user_id))
        except ValueError:
            raise GraphQLError("Invalid user_id", extensions={"code": "BAD_INPUT"})
        n = mcp_connections_svc.revoke_connection(uid, str(client_id), by_admin=True)
        audit_record(
            actor_user_id=actor,
            action="mcp.revoke_connection",
            target_type="mcp_connection",
            target_id=f"{user_id}:{client_id}",
            payload={"revoked": n},
        )
        return n > 0

    @strawberry.mutation(name="adminSetUserPlan")
    def admin_set_user_plan(
        self, info: Info, user_id: strawberry.ID, plan: str
    ) -> AdminUserSummary:
        """Cambia manualmente el plan de un usuario (override admin).

        Permite forzar el plan sin pasar por Stripe (soporte, cortesías, etc.).
        Crea el ``AccountProfile`` si no existe y audita el antes/después. NO
        toca Stripe: solo el estado local del plan.

        Args:
            info: Contexto GraphQL; debe ser admin.
            user_id: Usuario a modificar.
            plan: Plan destino (validado contra el enum ``Plan``).

        Returns:
            El ``AdminUserSummary`` actualizado del usuario.

        Raises:
            GraphQLError: ``BAD_INPUT`` si el ``user_id`` no es UUID válido o el
                plan no es válido; o el error de ``_admin_user_id`` si no es admin.
        """
        actor = _admin_user_id(info)
        try:
            uid = uuid.UUID(str(user_id))
        except ValueError:
            raise GraphQLError("Invalid user_id", extensions={"code": "BAD_INPUT"})

        normalized = plan.lower()
        valid = {p.value for p in Plan}
        if normalized not in valid:
            raise GraphQLError(
                f"Invalid plan '{plan}'. Allowed: {sorted(valid)}",
                extensions={"code": "BAD_INPUT"},
            )

        profile, created = AccountProfile.objects.get_or_create(user_id=uid)
        before = profile.plan
        profile.plan = normalized
        profile.save(update_fields=["plan", "updated_at"])

        audit_record(
            actor_user_id=actor,
            action="user.set_plan",
            target_type="user",
            target_id=uid,
            payload={
                "before": before if not created else None,
                "after": normalized,
                "created_profile": created,
            },
        )

        try:
            s_user = supabase_get_user(uid)
        except SupabaseAdminError:
            s_user = None
        email = s_user.email if s_user else ""
        counts = _build_counts_for(uid)
        last_activity = (
            ActivityModel.objects.filter(user_id=uid)
            .order_by("-created")
            .values_list("created", flat=True)
            .first()
        )

        return AdminUserSummary(
            user_id=strawberry.ID(str(uid)),
            email=email,
            plan=profile.plan,
            is_admin=profile.is_admin,
            is_billing_exempt=profile.is_billing_exempt,
            created_at=_parse_dt(s_user.created_at) if s_user else None,
            last_sign_in_at=_parse_dt(s_user.last_sign_in_at) if s_user else None,
            counts=counts,
            last_activity=last_activity,
            interactions_30d=interactions_svc.interactions_total(uid),
        )

    @strawberry.mutation(name="adminNotificationJobRetry")
    def admin_notification_job_retry(
        self, info: Info, id: strawberry.ID
    ) -> AdminNotificationJob:
        """Re-encola un job de notificación fallido o saltado.

        Lo devuelve a estado PENDING y limpia el error para que el worker lo
        reintente. Solo aplica a jobs FAILED o SKIPPED: reintentar uno enviado o
        pendiente no tiene sentido y se rechaza.

        Args:
            info: Contexto GraphQL; debe ser admin.
            id: ID del job de notificación.

        Returns:
            El ``AdminNotificationJob`` ya en estado PENDING.

        Raises:
            GraphQLError: ``NOT_FOUND`` si el job no existe (o id inválido);
                ``BAD_INPUT`` si el job no está en estado reintenta­ble; o el
                error de ``_admin_user_id`` si el solicitante no es admin.
        """
        actor = _admin_user_id(info)
        try:
            job = Notification.objects.get(id=uuid.UUID(str(id)))
        except (Notification.DoesNotExist, ValueError):
            raise GraphQLError("Job not found", extensions={"code": "NOT_FOUND"})
        if job.status not in {
            NotificationStatus.FAILED,
            NotificationStatus.SKIPPED,
        }:
            raise GraphQLError(
                f"Only failed or skipped jobs can be retried (current: {job.status})",
                extensions={"code": "BAD_INPUT"},
            )
        before = job.status
        job.status = NotificationStatus.PENDING
        job.error = ""
        job.save(update_fields=["status", "error"])
        audit_record(
            actor_user_id=actor,
            action="notification.retry",
            target_type="notification",
            target_id=job.id,
            payload={"before": before, "after": job.status},
        )
        return AdminNotificationJob(
            id=strawberry.ID(str(job.id)),
            user_id=strawberry.ID(str(job.user_id)),
            channel=job.channel,
            kind=job.kind,
            dedupe_key=job.dedupe_key,
            body=job.body,
            scheduled_for=job.scheduled_for,
            status=job.status,
            attempts=job.attempts,
            external_message_id=job.external_message_id,
            error=job.error,
            created=job.created,
            sent_at=job.sent_at,
        )

    @strawberry.mutation(name="adminSetUserIsAdmin")
    def admin_set_user_is_admin(
        self, info: Info, user_id: strawberry.ID, is_admin: bool
    ) -> AdminUserSummary:
        """Concede o revoca el rol de admin a un usuario.

        Crea el perfil si hace falta y audita el cambio. Salvaguarda clave: un
        admin no puede quitarse el rol a sí mismo, para no provocar un lockout
        accidental (debe pedírselo a otro admin).

        Args:
            info: Contexto GraphQL; debe ser admin.
            user_id: Usuario a modificar.
            is_admin: Nuevo valor del flag.

        Returns:
            El ``AdminUserSummary`` actualizado.

        Raises:
            GraphQLError: ``BAD_INPUT`` si el ``user_id`` no es UUID válido o si
                el actor intenta revocarse su propio admin; o el error de
                ``_admin_user_id`` si el solicitante no es admin.
        """
        actor = _admin_user_id(info)
        try:
            uid = uuid.UUID(str(user_id))
        except ValueError:
            raise GraphQLError("Invalid user_id", extensions={"code": "BAD_INPUT"})

        if uid == actor and not is_admin:
            raise GraphQLError(
                "Refusing to remove admin from your own account. "
                "Ask another admin to do it.",
                extensions={"code": "BAD_INPUT"},
            )

        profile, created = AccountProfile.objects.get_or_create(user_id=uid)
        before = profile.is_admin
        profile.is_admin = is_admin
        profile.save(update_fields=["is_admin", "updated_at"])

        audit_record(
            actor_user_id=actor,
            action="user.set_is_admin",
            target_type="user",
            target_id=uid,
            payload={
                "before": before if not created else None,
                "after": is_admin,
                "created_profile": created,
            },
        )

        try:
            s_user = supabase_get_user(uid)
        except SupabaseAdminError:
            s_user = None
        email = s_user.email if s_user else ""
        counts = _build_counts_for(uid)
        last_activity = (
            ActivityModel.objects.filter(user_id=uid)
            .order_by("-created")
            .values_list("created", flat=True)
            .first()
        )

        return AdminUserSummary(
            user_id=strawberry.ID(str(uid)),
            email=email,
            plan=profile.plan,
            is_admin=profile.is_admin,
            is_billing_exempt=profile.is_billing_exempt,
            created_at=_parse_dt(s_user.created_at) if s_user else None,
            last_sign_in_at=_parse_dt(s_user.last_sign_in_at) if s_user else None,
            counts=counts,
            last_activity=last_activity,
            interactions_30d=interactions_svc.interactions_total(uid),
        )

    @strawberry.mutation(name="adminSetUserIsBillingExempt")
    def admin_set_user_is_billing_exempt(
        self, info: Info, user_id: strawberry.ID, is_billing_exempt: bool
    ) -> AdminUserSummary:
        """Marca o desmarca a un usuario como exento de cobro.

        Controla ``is_billing_exempt`` (no se le cobra) de forma independiente
        del plan y de la cohorte beta. Crea el perfil si no existe y audita el
        cambio.

        Args:
            info: Contexto GraphQL; debe ser admin.
            user_id: Usuario a modificar.
            is_billing_exempt: Nuevo valor del flag.

        Returns:
            El ``AdminUserSummary`` actualizado.

        Raises:
            GraphQLError: ``BAD_INPUT`` si el ``user_id`` no es UUID válido; o el
                error de ``_admin_user_id`` si el solicitante no es admin.
        """
        actor = _admin_user_id(info)
        try:
            uid = uuid.UUID(str(user_id))
        except ValueError:
            raise GraphQLError("Invalid user_id", extensions={"code": "BAD_INPUT"})

        profile, created = AccountProfile.objects.get_or_create(user_id=uid)
        before = profile.is_billing_exempt
        profile.is_billing_exempt = is_billing_exempt
        profile.save(update_fields=["is_billing_exempt", "updated_at"])

        audit_record(
            actor_user_id=actor,
            action="user.set_is_billing_exempt",
            target_type="user",
            target_id=uid,
            payload={
                "before": before if not created else None,
                "after": is_billing_exempt,
                "created_profile": created,
            },
        )

        try:
            s_user = supabase_get_user(uid)
        except SupabaseAdminError:
            s_user = None
        email = s_user.email if s_user else ""
        counts = _build_counts_for(uid)
        last_activity = (
            ActivityModel.objects.filter(user_id=uid)
            .order_by("-created")
            .values_list("created", flat=True)
            .first()
        )

        return AdminUserSummary(
            user_id=strawberry.ID(str(uid)),
            email=email,
            plan=profile.plan,
            is_admin=profile.is_admin,
            is_billing_exempt=profile.is_billing_exempt,
            created_at=_parse_dt(s_user.created_at) if s_user else None,
            last_sign_in_at=_parse_dt(s_user.last_sign_in_at) if s_user else None,
            counts=counts,
            last_activity=last_activity,
            interactions_30d=interactions_svc.interactions_total(uid),
        )

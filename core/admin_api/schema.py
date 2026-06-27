"""GraphQL surface for admin operations — área de usuarios + ensamblaje.

All admin fields go through `_admin_user_id(info)` which enforces
AccountProfile.is_admin == True. The frontend admin layout calls
`me { isAdmin }` to decide whether to render the panel; this enforces
the same check on every operation in case anyone hits GraphQL directly.

`AdminQuery`/`AdminMutation` se ensamblan aquí con `merge_types` a partir de las
clases por área: usuarios (este archivo), billing (`schema_billing.py`) y sistema
(`schema_system.py`). Ver AUDITORIA_CODIGO.md.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

import strawberry
from graphql import GraphQLError
from strawberry.tools import merge_types
from strawberry.types import Info

from core.assistant.models import AccountProfile, Plan, UsageDay
from core.services import interactions as interactions_svc
from core.models import Activity as ActivityModel
from core.notifications.models import NotificationLink, NotificationSettings

from .audit import record as audit_record
from .permissions import _admin_user_id
from .services import user_stats as user_stats_svc
from .supabase_admin import (
    SupabaseAdminError,
    SupabaseUser,
    get_user as supabase_get_user,
    list_users as supabase_list_users,
)
from .types import *  # noqa: F401,F403

from .schema_billing import AdminBillingQuery
from .schema_system import AdminSystemMutation, AdminSystemQuery

PlanEnum = strawberry.enum(Plan, name="UserPlan")


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


def _counts_to_gql(c: user_stats_svc.EntityCounts) -> UserCounts:
    """Mapea el dataclass plano del servicio al tipo GraphQL ``UserCounts``."""
    return UserCounts(
        projects=c.projects,
        tasks_open=c.tasks_open,
        tasks_done=c.tasks_done,
        ideas=c.ideas,
        notes=c.notes,
    )


def _build_counts_for(user_id: uuid.UUID) -> UserCounts:
    """Conteos de producto de un usuario (delega en ``user_stats`` service)."""
    return _counts_to_gql(user_stats_svc.counts_for(user_id))


def _bulk_counts(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, UserCounts]:
    """Conteos en bulk para la lista admin (delega en ``user_stats`` service)."""
    return {
        uid: _counts_to_gql(c)
        for uid, c in user_stats_svc.bulk_counts(user_ids).items()
    }


def _last_activity_map(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dt.datetime]:
    """Última actividad por usuario (delega en ``user_stats`` service)."""
    return user_stats_svc.last_activity_map(user_ids)


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


# ---------- Query (usuarios) ----------


@strawberry.type
class AdminUsersQuery:
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


# ---------- Mutation (usuarios) ----------


@strawberry.type
class AdminUsersMutation:
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


# ---------- Ensamblaje por área ----------

AdminQuery = merge_types(
    "AdminQuery",
    (AdminUsersQuery, AdminBillingQuery, AdminSystemQuery),
)

AdminMutation = merge_types(
    "AdminMutation",
    (AdminUsersMutation, AdminSystemMutation),
)

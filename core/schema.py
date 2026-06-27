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

import uuid
import datetime as dt
from typing import Optional, List

import strawberry
from strawberry.tools import merge_types
from strawberry.types import Info
from graphql import GraphQLError

from . import analytics as analytics_mod
from .models import GraveyardInsight as GraveyardInsightModel
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
    dashboard as dashboard_svc,
    google_calendar as google_calendar_svc,
    google_tasks as google_tasks_svc,
    icloud_calendar as icloud_calendar_svc,
    mcp_connections as mcp_connections_svc,
    onboarding as onboarding_svc,
    preferences as preferences_svc,
    profiles as profiles_svc,
    quick_notes as quick_notes_svc,
    routines as routines_svc,
)

from core.assistant.quotas import get_or_create_profile
from .services.projects import NotFoundError


# Helpers de error/auth viven en schema_helpers.py (extraídos).
from .schema_helpers import (
    _user_id,
    _quota_error,
    _closure_error,
    gql_error_handler,
)


# Tipos e inputs GraphQL viven en schema_types.py (extraídos, ver AUDITORIA_CODIGO.md).
from .schema_types import *  # noqa: F401,F403
from .schema_types import _to_analytics_gql  # conversor privado (no entra por *)

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


# ---------- Mutations (extraídas a schema_mutations.py) ----------
from .schema_mutations import Mutation
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

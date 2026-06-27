"""Mutations GraphQL de core, extraídas de schema.py (ver AUDITORIA_CODIGO.md).

Solo la clase `Mutation`; importa los tipos de `schema_types`, los helpers de
`schema_helpers` y los servicios de dominio. No depende de schema.py (que la
re-importa para el `merge_types`).
"""

import uuid
import datetime as dt
from typing import Optional, List

import strawberry
from strawberry.types import Info
from graphql import GraphQLError
from django.core.exceptions import ValidationError

from . import account_deletion
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
from .services.projects import NotFoundError
from .quotas import EntityQuotaExceeded
from .schema_types import *  # noqa: F401,F403
from .schema_helpers import (
    _user_id,
    _quota_error,
    _closure_error,
    gql_error_handler,
)


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

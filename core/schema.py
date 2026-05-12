import uuid
import datetime as dt
from typing import Optional, List

import strawberry
from strawberry.tools import merge_types
from strawberry.types import Info
from graphql import GraphQLError

from . import analytics as analytics_mod
from .analytics import AnalyticsRange as AnalyticsRangeEnum
from .models import (
    Project as ProjectModel,
    ProjectNote as ProjectNoteModel,
    Task as TaskModel,
    Idea as IdeaModel,
    Update as UpdateModel,
    BackupMeta,
    Category as CategoryModel,
    Profile as ProfileModel,
)
from .notifications.schema import NotificationsQuery, NotificationsMutation
from .services import (
    categories as categories_svc,
    ideas as ideas_svc,
    notes as notes_svc,
    profiles as profiles_svc,
    projects as projects_svc,
    tasks as tasks_svc,
    updates as updates_svc,
)
from .services.projects import NotFoundError


AnalyticsRange = strawberry.enum(AnalyticsRangeEnum, name="AnalyticsRange")


def _user_id(info: Info) -> uuid.UUID:
    user_id = getattr(info.context, "user_id", None)
    if not user_id:
        raise GraphQLError(
            "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
        )
    return user_id


def _not_found(label: str) -> GraphQLError:
    return GraphQLError(f"{label} not found", extensions={"code": "NOT_FOUND"})


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
class Task:
    id: strawberry.ID
    title: str
    project_id: Optional[strawberry.ID]
    due_date: Optional[dt.datetime]
    done: bool
    completed_at: Optional[dt.datetime]
    created: dt.datetime
    effort_hours: Optional[float] = None

    @classmethod
    def from_model(cls, m: TaskModel) -> "Task":
        return cls(
            id=strawberry.ID(str(m.id)),
            title=m.title,
            project_id=strawberry.ID(str(m.project_id)) if m.project_id else None,
            due_date=m.due_date,
            done=m.done,
            completed_at=m.completed_at,
            created=m.created,
            effort_hours=m.effort_hours,
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
class Update:
    id: strawberry.ID
    project_id: strawberry.ID
    note: str
    date: dt.datetime

    @classmethod
    def from_model(cls, m: UpdateModel) -> "Update":
        return cls(
            id=strawberry.ID(str(m.id)),
            project_id=strawberry.ID(str(m.project_id)),
            note=m.note,
            date=m.date,
        )


@strawberry.type
class Profile:
    avatar: Optional[str]

    @classmethod
    def from_model(cls, m: ProfileModel) -> "Profile":
        return cls(avatar=m.avatar or None)


@strawberry.type
class Dashboard:
    projects: List[Project]
    tasks: List[Task]
    ideas: List[Idea]
    updates: List[Update]
    categories: List[Category]
    project_notes: List[ProjectNote]
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


@strawberry.input
class IdeaInput:
    title: str
    description: Optional[str] = ""
    why: Optional[str] = ""


@strawberry.input
class ImportPayload:
    projects: str  # JSON string — keeps schema simple, validated server-side
    mode: str = "merge"  # "merge" | "replace"


# ---------- Analytics types ----------


@strawberry.type
class CadenceStats:
    current_streak: int
    longest_streak: int
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
    sleeping_projects: List[SleepingProjectRow]
    stale_ideas: List[StaleIdeaRow]
    idea_funnel: IdeaFunnel
    effort: EffortStats


def _to_analytics_gql(r: analytics_mod.AnalyticsResult) -> Analytics:
    return Analytics(
        range=r.range,
        range_start=r.range_start,
        range_end=r.range_end,
        cadence=CadenceStats(
            current_streak=r.cadence.current_streak,
            longest_streak=r.cadence.longest_streak,
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
    )


# ---------- Queries ----------


@strawberry.type
class Query:
    @strawberry.field
    def dashboard(self, info: Info) -> Dashboard:
        uid = _user_id(info)
        projects = list(ProjectModel.objects.filter(user_id=uid))
        tasks = list(TaskModel.objects.filter(user_id=uid))
        ideas = list(IdeaModel.objects.filter(user_id=uid))
        updates = list(UpdateModel.objects.filter(user_id=uid))
        categories = list(CategoryModel.objects.filter(user_id=uid))
        project_notes = list(ProjectNoteModel.objects.filter(user_id=uid))
        meta = BackupMeta.objects.filter(user_id=uid).first()
        return Dashboard(
            projects=[Project.from_model(p) for p in projects],
            tasks=[Task.from_model(t) for t in tasks],
            ideas=[Idea.from_model(i) for i in ideas],
            updates=[Update.from_model(u) for u in updates],
            categories=[Category.from_model(c) for c in categories],
            project_notes=[ProjectNote.from_model(n) for n in project_notes],
            last_backup=meta.last_backup if meta else None,
        )

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


# ---------- Mutations ----------


@strawberry.type
class Mutation:
    # Projects
    @strawberry.mutation
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
        )
        return Project.from_model(m)

    @strawberry.mutation
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
            )
        except NotFoundError:
            raise _not_found("Project")
        return Project.from_model(m)

    # Project notes (multiple per project)
    @strawberry.mutation
    def create_project_note(self, info: Info, data: ProjectNoteInput) -> ProjectNote:
        uid = _user_id(info)
        try:
            m = notes_svc.create_note(
                uid,
                project_id=data.project_id,
                title=data.title or "",
                body=data.body or "",
            )
        except NotFoundError:
            raise _not_found("Project")
        return ProjectNote.from_model(m)

    @strawberry.mutation
    def update_project_note(
        self, info: Info, id: strawberry.ID, data: ProjectNoteInput
    ) -> ProjectNote:
        uid = _user_id(info)
        try:
            m = notes_svc.update_note(
                uid, id, title=data.title or "", body=data.body or ""
            )
        except NotFoundError:
            raise _not_found("ProjectNote")
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

    # Tasks
    @strawberry.mutation
    def create_task(self, info: Info, data: TaskInput) -> Task:
        uid = _user_id(info)
        try:
            m = tasks_svc.create_task(
                uid,
                title=data.title,
                project_id=data.project_id or None,
                due_date=data.due_date,
                done=bool(data.done),
                effort_hours=data.effort_hours,
            )
        except NotFoundError:
            raise _not_found("Project")
        return Task.from_model(m)

    @strawberry.mutation
    def update_task(self, info: Info, id: strawberry.ID, data: TaskInput) -> Task:
        uid = _user_id(info)
        try:
            m = tasks_svc.update_task(
                uid,
                id,
                title=data.title,
                project_id=data.project_id or None,
                due_date=data.due_date,
                done=bool(data.done),
                effort_hours=data.effort_hours,
            )
        except NotFoundError as e:
            raise _not_found(str(e).split(" ", 1)[0])
        return Task.from_model(m)

    @strawberry.mutation
    def toggle_task(self, info: Info, id: strawberry.ID) -> Task:
        uid = _user_id(info)
        try:
            m = tasks_svc.toggle_task(uid, id)
        except NotFoundError:
            raise _not_found("Task")
        return Task.from_model(m)

    @strawberry.mutation
    def delete_task(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        tasks_svc.delete_task(uid, id)
        return True

    # Ideas
    @strawberry.mutation
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
    def update_idea(self, info: Info, id: strawberry.ID, data: IdeaInput) -> Idea:
        uid = _user_id(info)
        try:
            m = ideas_svc.update_idea(
                uid,
                id,
                title=data.title,
                description=data.description or "",
                why=data.why or "",
            )
        except NotFoundError:
            raise _not_found("Idea")
        return Idea.from_model(m)

    @strawberry.mutation
    def delete_idea(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        ideas_svc.delete_idea(uid, id)
        return True

    @strawberry.mutation
    def promote_idea(self, info: Info, id: strawberry.ID) -> Project:
        uid = _user_id(info)
        try:
            p = ideas_svc.promote_idea(uid, id)
        except NotFoundError:
            raise _not_found("Idea")
        return Project.from_model(p)

    # Updates / activity log
    @strawberry.mutation
    def add_update(self, info: Info, project_id: strawberry.ID, note: str) -> Update:
        uid = _user_id(info)
        try:
            m = updates_svc.add_update(uid, project_id=project_id, note=note)
        except NotFoundError:
            raise _not_found("Project")
        return Update.from_model(m)

    @strawberry.mutation
    def update_update(self, info: Info, id: strawberry.ID, note: str) -> Update:
        uid = _user_id(info)
        try:
            m = updates_svc.edit_update(uid, id, note=note)
        except NotFoundError:
            raise _not_found("Update")
        return Update.from_model(m)

    @strawberry.mutation
    def delete_update(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        updates_svc.delete_update(uid, id)
        return True

    # Categories
    @strawberry.mutation
    def create_category(self, info: Info, data: CategoryInput) -> Category:
        uid = _user_id(info)
        m = categories_svc.create_category(
            uid, name=data.name, color=data.color or "emerald"
        )
        return Category.from_model(m)

    @strawberry.mutation
    def update_category(self, info: Info, id: strawberry.ID, data: CategoryInput) -> Category:
        uid = _user_id(info)
        try:
            m = categories_svc.update_category(
                uid, id, name=data.name, color=data.color or ""
            )
        except NotFoundError:
            raise _not_found("Category")
        return Category.from_model(m)

    @strawberry.mutation
    def delete_category(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        categories_svc.delete_category(uid, id)
        return True

    # Backup metadata
    @strawberry.mutation
    def mark_backup(self, info: Info) -> dt.datetime:
        uid = _user_id(info)
        from django.utils import timezone

        now = timezone.now()
        BackupMeta.objects.update_or_create(
            user_id=uid, defaults={"last_backup": now}
        )
        return now

    # Profile
    @strawberry.mutation
    def update_profile(
        self, info: Info, avatar: Optional[str] = None
    ) -> Profile:
        from django.core.exceptions import ValidationError

        uid = _user_id(info)
        try:
            m = profiles_svc.set_avatar(uid, avatar)
        except ValidationError as e:
            raise GraphQLError(
                str(e.messages[0] if e.messages else "Invalid input"),
                extensions={"code": "BAD_INPUT"},
            )
        return Profile.from_model(m)


CombinedQuery = merge_types("Query", (Query, NotificationsQuery))
CombinedMutation = merge_types("Mutation", (Mutation, NotificationsMutation))

schema = strawberry.Schema(query=CombinedQuery, mutation=CombinedMutation)

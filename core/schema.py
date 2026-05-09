import uuid
import datetime as dt
from typing import Optional, List

import strawberry
from strawberry.types import Info
from graphql import GraphQLError
from django.db import transaction
from django.utils import timezone

from . import analytics as analytics_mod
from .analytics import AnalyticsRange as AnalyticsRangeEnum
from .models import (
    Project as ProjectModel,
    Task as TaskModel,
    Idea as IdeaModel,
    Update as UpdateModel,
    BackupMeta,
    Category as CategoryModel,
)


AnalyticsRange = strawberry.enum(AnalyticsRangeEnum, name="AnalyticsRange")


def _user_id(info: Info) -> uuid.UUID:
    user_id = getattr(info.context, "user_id", None)
    if not user_id:
        raise GraphQLError(
            "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
        )
    return user_id


def _get_owned(model, pk, uid, label: str):
    obj = model.objects.filter(pk=pk, user_id=uid).first()
    if obj is None:
        raise GraphQLError(
            f"{label} not found", extensions={"code": "NOT_FOUND"}
        )
    return obj


def _assert_owned_project(uid, project_id) -> None:
    if project_id and not ProjectModel.objects.filter(
        pk=project_id, user_id=uid
    ).exists():
        raise GraphQLError(
            "Project not found", extensions={"code": "NOT_FOUND"}
        )


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
class Dashboard:
    projects: List[Project]
    tasks: List[Task]
    ideas: List[Idea]
    updates: List[Update]
    categories: List[Category]
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
        meta = BackupMeta.objects.filter(user_id=uid).first()
        return Dashboard(
            projects=[Project.from_model(p) for p in projects],
            tasks=[Task.from_model(t) for t in tasks],
            ideas=[Idea.from_model(i) for i in ideas],
            updates=[Update.from_model(u) for u in updates],
            categories=[Category.from_model(c) for c in categories],
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


# ---------- Mutations ----------


@strawberry.type
class Mutation:
    # Projects
    @strawberry.mutation
    def create_project(self, info: Info, data: ProjectInput) -> Project:
        uid = _user_id(info)
        category = None
        if data.category_id:
            category = CategoryModel.objects.filter(pk=data.category_id, user_id=uid).first()
        m = ProjectModel.objects.create(
            user_id=uid,
            name=data.name,
            description=data.description or "",
            why=data.why or "",
            next_step=data.next_step or "",
            status=data.status or "idea",
            priority=data.priority or "medium",
            category=category,
        )
        return Project.from_model(m)

    @strawberry.mutation
    def update_project(self, info: Info, id: strawberry.ID, data: ProjectInput) -> Project:
        uid = _user_id(info)
        m = _get_owned(ProjectModel, id, uid, "Project")
        m.name = data.name
        m.description = data.description or ""
        m.why = data.why or ""
        m.next_step = data.next_step or ""
        m.status = data.status or m.status
        m.priority = data.priority or m.priority
        if data.category_id is None:
            m.category = None
        else:
            m.category = CategoryModel.objects.filter(
                pk=data.category_id, user_id=uid
            ).first()
        m.last_activity = timezone.now()
        m.save()
        return Project.from_model(m)

    @strawberry.mutation
    def delete_project(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        ProjectModel.objects.filter(pk=id, user_id=uid).delete()
        return True

    # Tasks
    @strawberry.mutation
    def create_task(self, info: Info, data: TaskInput) -> Task:
        uid = _user_id(info)
        _assert_owned_project(uid, data.project_id)
        m = TaskModel.objects.create(
            user_id=uid,
            title=data.title,
            project_id=data.project_id or None,
            due_date=data.due_date,
            done=bool(data.done),
            effort_hours=data.effort_hours,
        )
        if m.project_id:
            ProjectModel.objects.filter(pk=m.project_id, user_id=uid).update(
                last_activity=timezone.now()
            )
        return Task.from_model(m)

    @strawberry.mutation
    def update_task(self, info: Info, id: strawberry.ID, data: TaskInput) -> Task:
        uid = _user_id(info)
        _assert_owned_project(uid, data.project_id)
        m = _get_owned(TaskModel, id, uid, "Task")
        m.title = data.title
        m.project_id = data.project_id or None
        m.due_date = data.due_date
        m.done = bool(data.done)
        m.effort_hours = data.effort_hours
        if m.done and not m.completed_at:
            m.completed_at = timezone.now()
        if not m.done:
            m.completed_at = None
        m.save()
        return Task.from_model(m)

    @strawberry.mutation
    def toggle_task(self, info: Info, id: strawberry.ID) -> Task:
        uid = _user_id(info)
        m = _get_owned(TaskModel, id, uid, "Task")
        m.done = not m.done
        m.completed_at = timezone.now() if m.done else None
        m.save()
        if m.done and m.project_id:
            UpdateModel.objects.create(
                user_id=uid, project_id=m.project_id, note=f"Completed: {m.title}"
            )
            ProjectModel.objects.filter(pk=m.project_id, user_id=uid).update(
                last_activity=timezone.now()
            )
        return Task.from_model(m)

    @strawberry.mutation
    def delete_task(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        TaskModel.objects.filter(pk=id, user_id=uid).delete()
        return True

    # Ideas
    @strawberry.mutation
    def create_idea(self, info: Info, data: IdeaInput) -> Idea:
        uid = _user_id(info)
        m = IdeaModel.objects.create(
            user_id=uid,
            title=data.title,
            description=data.description or "",
            why=data.why or "",
        )
        return Idea.from_model(m)

    @strawberry.mutation
    def update_idea(self, info: Info, id: strawberry.ID, data: IdeaInput) -> Idea:
        uid = _user_id(info)
        m = _get_owned(IdeaModel, id, uid, "Idea")
        m.title = data.title
        m.description = data.description or ""
        m.why = data.why or ""
        m.save()
        return Idea.from_model(m)

    @strawberry.mutation
    def delete_idea(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        IdeaModel.objects.filter(pk=id, user_id=uid).delete()
        return True

    @strawberry.mutation
    def promote_idea(self, info: Info, id: strawberry.ID) -> Project:
        uid = _user_id(info)
        with transaction.atomic():
            i = _get_owned(IdeaModel, id, uid, "Idea")
            p = ProjectModel.objects.create(
                user_id=uid,
                name=i.title,
                description=i.description,
                why=i.why,
                status="idea",
                promoted_from_idea_at=timezone.now(),
            )
            i.delete()
        return Project.from_model(p)

    # Updates / activity log
    @strawberry.mutation
    def add_update(self, info: Info, project_id: strawberry.ID, note: str) -> Update:
        uid = _user_id(info)
        _assert_owned_project(uid, project_id)
        m = UpdateModel.objects.create(user_id=uid, project_id=project_id, note=note)
        ProjectModel.objects.filter(pk=project_id, user_id=uid).update(
            last_activity=timezone.now()
        )
        return Update.from_model(m)

    @strawberry.mutation
    def update_update(self, info: Info, id: strawberry.ID, note: str) -> Update:
        uid = _user_id(info)
        m = _get_owned(UpdateModel, id, uid, "Update")
        m.note = note
        m.save()
        return Update.from_model(m)

    @strawberry.mutation
    def delete_update(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        UpdateModel.objects.filter(pk=id, user_id=uid).delete()
        return True

    # Categories
    @strawberry.mutation
    def create_category(self, info: Info, data: CategoryInput) -> Category:
        uid = _user_id(info)
        m, _ = CategoryModel.objects.get_or_create(
            user_id=uid,
            name=data.name,
            defaults={"color": data.color or "emerald"},
        )
        return Category.from_model(m)

    @strawberry.mutation
    def update_category(self, info: Info, id: strawberry.ID, data: CategoryInput) -> Category:
        uid = _user_id(info)
        m = _get_owned(CategoryModel, id, uid, "Category")
        m.name = data.name
        m.color = data.color or m.color
        m.save()
        return Category.from_model(m)

    @strawberry.mutation
    def delete_category(self, info: Info, id: strawberry.ID) -> bool:
        uid = _user_id(info)
        CategoryModel.objects.filter(pk=id, user_id=uid).delete()
        return True

    # Backup metadata
    @strawberry.mutation
    def mark_backup(self, info: Info) -> dt.datetime:
        uid = _user_id(info)
        now = timezone.now()
        BackupMeta.objects.update_or_create(
            user_id=uid, defaults={"last_backup": now}
        )
        return now


schema = strawberry.Schema(query=Query, mutation=Mutation)

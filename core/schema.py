import uuid
import datetime as dt
from typing import Optional, List

import strawberry
from strawberry.types import Info
from graphql import GraphQLError
from django.db import transaction
from django.utils import timezone

from .models import (
    Project as ProjectModel,
    Task as TaskModel,
    Idea as IdeaModel,
    Update as UpdateModel,
    BackupMeta,
    Category as CategoryModel,
)


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


@strawberry.input
class IdeaInput:
    title: str
    description: Optional[str] = ""
    why: Optional[str] = ""


@strawberry.input
class ImportPayload:
    projects: str  # JSON string — keeps schema simple, validated server-side
    mode: str = "merge"  # "merge" | "replace"


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

"""Compact dashboard summary for the assistant's skinny-context."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from django.db.models import Count, Q
from django.utils import timezone

from ..models import Category, Idea, Project, Task, TaskBlocker


@dataclass
class DashboardSummary:
    active_projects: int
    sleeping_projects: int
    launched_projects: int
    archived_projects: int
    open_tasks: int
    overdue_tasks: int
    due_soon_tasks: int
    blocked_tasks: int
    open_ideas: int
    categories: int
    last_activity: dt.datetime | None


SLEEPING_DAYS = 7
DUE_SOON_DAYS = 7


def get_dashboard_summary(user_id: uuid.UUID) -> DashboardSummary:
    now = timezone.now()
    sleeping_cutoff = now - dt.timedelta(days=SLEEPING_DAYS)
    due_soon_cutoff = now + dt.timedelta(days=DUE_SOON_DAYS)

    project_counts = Project.objects.filter(user_id=user_id).aggregate(
        active=Count(
            "id",
            filter=Q(status__in=["active", "idea"], last_activity__gte=sleeping_cutoff),
        ),
        sleeping=Count(
            "id",
            filter=Q(status__in=["active", "idea"], last_activity__lt=sleeping_cutoff),
        ),
        launched=Count("id", filter=Q(status="launched")),
        archived=Count("id", filter=Q(status="archived")),
    )

    task_counts = Task.objects.filter(user_id=user_id, done=False).aggregate(
        open=Count("id"),
        overdue=Count("id", filter=Q(due_date__isnull=False, due_date__lt=now)),
        due_soon=Count(
            "id",
            filter=Q(
                due_date__isnull=False, due_date__gte=now, due_date__lt=due_soon_cutoff
            ),
        ),
    )

    last = (
        Project.objects.filter(user_id=user_id)
        .order_by("-last_activity")
        .values_list("last_activity", flat=True)
        .first()
    )

    blocked_tasks = (
        Task.objects.filter(user_id=user_id, done=False, blockers__isnull=False)
        .distinct()
        .count()
    )

    return DashboardSummary(
        active_projects=project_counts["active"] or 0,
        sleeping_projects=project_counts["sleeping"] or 0,
        launched_projects=project_counts["launched"] or 0,
        archived_projects=project_counts["archived"] or 0,
        open_tasks=task_counts["open"] or 0,
        overdue_tasks=task_counts["overdue"] or 0,
        due_soon_tasks=task_counts["due_soon"] or 0,
        blocked_tasks=blocked_tasks,
        open_ideas=Idea.objects.filter(user_id=user_id).count(),
        categories=Category.objects.filter(user_id=user_id).count(),
        last_activity=last,
    )

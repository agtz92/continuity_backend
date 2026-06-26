"""Agregación de métricas del sistema para el panel admin (capa de servicio).

Extrae la lógica de negocio + ORM que vivía dentro del resolver
``admin_system_stats`` de ``core/admin_api/schema.py`` (186 líneas, ver
AUDITORIA_CODIGO.md). Devuelve un dataclass plano ``SystemStats`` con datos
crudos (sin tipos Strawberry); el resolver se limita a gatear admin y mapear
el resultado a los tipos GraphQL. El comportamiento es idéntico al original.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from django.db.models import Count
from django.utils import timezone

from core.assistant.models import AccountProfile, Plan
from core.models import Activity as ActivityModel
from core.models import Idea as IdeaModel
from core.models import Project as ProjectModel
from core.models import Task as TaskModel
from core.notifications.models import Notification, NotificationStatus

from ..supabase_admin import SupabaseAdminError, fetch_all_users

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Point:
    """Punto de una serie temporal diaria (``value`` para la fecha ``date``)."""

    date: dt.date
    value: int


@dataclass(frozen=True)
class Labeled:
    """Conteo etiquetado genérico (``label`` → ``count``)."""

    label: str
    count: int


@dataclass(frozen=True)
class RecentSignupRow:
    """Alta reciente cruzando Supabase auth (identidad) con el plan local."""

    user_id: uuid.UUID
    email: str
    created_at: Optional[dt.datetime]
    plan: str


@dataclass
class SystemStats:
    """Snapshot completo del panel global de métricas del admin."""

    total_users: int
    total_accounts: int
    admins: int
    plan_counts: list[Labeled]
    dau: int
    wau: int
    mau: int
    signups_series: list[Point]
    activity_series: list[Point]
    activity_by_kind: list[Labeled]
    project_state_counts: list[Labeled]
    tasks_open: int
    tasks_done_30d: int
    ideas_total: int
    blog_posts_published: int
    blog_posts_draft: int
    pages_published: int
    pending_jobs: int
    failed_jobs: int
    job_status_counts: list[Labeled]
    recent_signups: list[RecentSignupRow] = field(default_factory=list)


def _parse_iso(value: Optional[str]) -> Optional[dt.datetime]:
    """Parsea un timestamp ISO 8601 de Supabase (sufijo ``Z`` → ``+00:00``)."""
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_system_stats() -> SystemStats:
    """Agrega todas las cifras del dashboard admin en un solo snapshot.

    Reúne usuarios y planes, engagement (DAU/WAU/MAU + series diarias), objetos
    de producto, CMS y salud de la cola de notificaciones. Los usuarios salen de
    Supabase auth (fuente real) y el resto del ORM local. Es deliberadamente
    caro y se sirve a una sola pantalla. Si Supabase falla se degrada a una lista
    vacía de usuarios en vez de romper toda la consulta.

    Returns:
        ``SystemStats`` con datos crudos (sin tipos GraphQL).
    """
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
        created = _parse_iso(u.created_at)
        if created is None:
            continue
        d = created.date()
        if d in signup_buckets:
            signup_buckets[d] += 1
    signups_series = [
        Point(date=d, value=signup_buckets[d]) for d in sorted(signup_buckets)
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
    recent_signups: list[RecentSignupRow] = [
        RecentSignupRow(
            user_id=u.id,
            email=u.email,
            created_at=_parse_iso(u.created_at),
            plan=plan_by_uid.get(u.id, Plan.FREE.value),
        )
        for u in sorted_users
    ]

    # --- Local accounts / plans ---------------------------------------
    total_accounts = AccountProfile.objects.count()
    admins = AccountProfile.objects.filter(is_admin=True).count()
    plan_rows = (
        AccountProfile.objects.values("plan")
        .annotate(c=Count("user_id"))
        .order_by("plan")
    )
    plan_counts = [
        Labeled(label=row["plan"], count=row["c"]) for row in plan_rows
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
        Point(date=d, value=len(activity_buckets[d]))
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
        Labeled(label=row["kind"], count=row["c"]) for row in kind_rows
    ]

    # --- Product objects ----------------------------------------------
    proj_rows = (
        ProjectModel.objects.values("status")
        .annotate(c=Count("id"))
        .order_by("status")
    )
    project_state_counts = [
        Labeled(label=row["status"], count=row["c"]) for row in proj_rows
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
        Labeled(label=r["status"], count=r["c"]) for r in status_rows
    ]

    return SystemStats(
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

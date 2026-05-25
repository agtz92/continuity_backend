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
class AdminSystemStats:
    total_accounts: int
    admins: int
    plan_counts: list[PlanCount]
    dau: int  # last 24h: users with activity
    wau: int  # last 7d
    mau: int  # last 30d
    blog_posts_published: int
    blog_posts_draft: int
    pages_published: int
    pending_jobs: int
    failed_jobs: int
    job_status_counts: list[JobStatusCount]


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
    if not value:
        return None
    try:
        # Supabase returns ISO 8601 with Z or +00:00
        normalized = value.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _build_counts_for(user_id: uuid.UUID) -> UserCounts:
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


def _bulk_counts(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, UserCounts]:
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
) -> AdminUserSummary:
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
    )


# ---------- Query ----------


@strawberry.type
class AdminQuery:
    @strawberry.field
    def me(self, info: Info) -> Me:
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
        _admin_user_id(info)
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

        zero_counts = UserCounts(
            projects=0, tasks_open=0, tasks_done=0, ideas=0, notes=0
        )
        summaries = [
            _build_summary(
                u,
                profiles.get(u.id),
                counts_map.get(u.id, zero_counts),
                last_act_map.get(u.id),
            )
            for u in s_users
        ]

        has_next = len(page_result.users) >= per_page

        return AdminUserPage(
            users=summaries,
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="adminUser")
    def admin_user(self, info: Info, user_id: strawberry.ID) -> AdminUserDetail:
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
        _admin_user_id(info)
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

    @strawberry.field(name="adminSystemStats")
    def admin_system_stats(self, info: Info) -> AdminSystemStats:
        _admin_user_id(info)
        now = timezone.now()
        d1 = now - dt.timedelta(days=1)
        d7 = now - dt.timedelta(days=7)
        d30 = now - dt.timedelta(days=30)

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

        # CMS counts — keep loose imports inside to avoid circulars.
        from core.cms.models import BlogPost, Page, PostStatus as CmsStatus

        blog_published = BlogPost.objects.filter(status=CmsStatus.PUBLISHED).count()
        blog_draft = BlogPost.objects.filter(status=CmsStatus.DRAFT).count()
        pages_published = Page.objects.filter(status=CmsStatus.PUBLISHED).count()

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
            total_accounts=total_accounts,
            admins=admins,
            plan_counts=plan_counts,
            dau=dau,
            wau=wau,
            mau=mau,
            blog_posts_published=blog_published,
            blog_posts_draft=blog_draft,
            pages_published=pages_published,
            pending_jobs=pending_jobs,
            failed_jobs=failed_jobs,
            job_status_counts=job_status_counts,
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
        _admin_user_id(info)
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


# ---------- Mutations ----------


@strawberry.type
class AdminMutation:
    @strawberry.mutation(name="adminSetUserPlan")
    def admin_set_user_plan(
        self, info: Info, user_id: strawberry.ID, plan: str
    ) -> AdminUserSummary:
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
        )

    @strawberry.mutation(name="adminNotificationJobRetry")
    def admin_notification_job_retry(
        self, info: Info, id: strawberry.ID
    ) -> AdminNotificationJob:
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
        )

    @strawberry.mutation(name="adminSetUserIsBillingExempt")
    def admin_set_user_is_billing_exempt(
        self, info: Info, user_id: strawberry.ID, is_billing_exempt: bool
    ) -> AdminUserSummary:
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
        )

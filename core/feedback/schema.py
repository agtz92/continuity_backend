"""GraphQL surface for user → admin bug reports.

Public (authenticated user):
- `submitBugReport(data)` — file a bug report. One-way; no reply channel.

Admin (gated by `_admin_user_id`, audit-logged):
- `adminBugReports(page, perPage, status?)` — paginated inbox.
- `adminBugReportsUnreadCount` — count of `new` reports (nav badge).
- `adminBugReportSetStatus(id, status)` — triage (new | read | archived).
- `adminBugReportDelete(id)` — remove a report.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Optional

import strawberry
from django.utils import timezone
from graphql import GraphQLError
from strawberry.types import Info

from core.admin_api.audit import record as audit_record
from core.admin_api.permissions import _admin_user_id
from core.admin_api.supabase_admin import SupabaseAdminError, get_users_map

from .models import BugReport, Platform, Status

logger = logging.getLogger(__name__)

MAX_TOPIC_LEN = 120
MAX_MESSAGE_LEN = 4000
# Soft anti-abuse throttle for the inbox: max reports per user per rolling hour.
RATE_LIMIT_PER_HOUR = 10


def _user_id(info: Info) -> uuid.UUID:
    uid = getattr(info.context, "user_id", None)
    if not uid:
        raise GraphQLError(
            "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
        )
    return uid


# ---------- Public (user) ----------


@strawberry.input
class BugReportInput:
    topic: str
    message: str
    platform: Optional[str] = None  # web | app


@strawberry.type
class FeedbackMutation:
    @strawberry.mutation(name="submitBugReport")
    def submit_bug_report(self, info: Info, data: BugReportInput) -> bool:
        uid = _user_id(info)

        topic = (data.topic or "").strip()
        message = (data.message or "").strip()
        if not topic:
            raise GraphQLError(
                "A topic is required", extensions={"code": "BAD_INPUT"}
            )
        if not message:
            raise GraphQLError(
                "A message is required", extensions={"code": "BAD_INPUT"}
            )
        if len(topic) > MAX_TOPIC_LEN:
            topic = topic[:MAX_TOPIC_LEN]
        if len(message) > MAX_MESSAGE_LEN:
            message = message[:MAX_MESSAGE_LEN]

        platform = (data.platform or Platform.WEB.value).strip().lower()
        if platform not in {p.value for p in Platform}:
            platform = Platform.WEB.value

        # Soft throttle to keep the inbox clean.
        since = timezone.now() - dt.timedelta(hours=1)
        recent = BugReport.objects.filter(user_id=uid, created__gte=since).count()
        if recent >= RATE_LIMIT_PER_HOUR:
            raise GraphQLError(
                "Too many reports. Please try again later.",
                extensions={"code": "RATE_LIMITED"},
            )

        BugReport.objects.create(
            user_id=uid,
            topic=topic,
            message=message,
            platform=platform,
            status=Status.NEW.value,
        )
        return True


# ---------- Admin ----------


@strawberry.type
class AdminBugReport:
    id: strawberry.ID
    user_id: strawberry.ID
    email: str
    topic: str
    message: str
    platform: str
    status: str
    created: dt.datetime

    @classmethod
    def from_model(cls, r: BugReport, email: str = "") -> "AdminBugReport":
        return cls(
            id=strawberry.ID(str(r.id)),
            user_id=strawberry.ID(str(r.user_id)),
            email=email,
            topic=r.topic,
            message=r.message,
            platform=r.platform,
            status=r.status,
            created=r.created,
        )


@strawberry.type
class AdminBugReportPage:
    reports: list[AdminBugReport]
    page: int
    per_page: int
    has_next: bool


def _get_or_404(id_: strawberry.ID) -> BugReport:
    try:
        return BugReport.objects.get(id=uuid.UUID(str(id_)))
    except (BugReport.DoesNotExist, ValueError):
        raise GraphQLError(
            "Bug report not found", extensions={"code": "NOT_FOUND"}
        )


@strawberry.type
class AdminFeedbackQuery:
    @strawberry.field(name="adminBugReports")
    def admin_bug_reports(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 50,
        status: Optional[str] = None,
    ) -> AdminBugReportPage:
        _admin_user_id(info)

        per_page = max(1, min(per_page, 200))
        page = max(1, page)

        qs = BugReport.objects.all()
        if status:
            qs = qs.filter(status=status)

        offset = (page - 1) * per_page
        rows = list(qs[offset : offset + per_page + 1])
        has_next = len(rows) > per_page
        rows = rows[:per_page]

        # Bulk-resolve emails for just this page (best effort; same pattern as
        # adminUsers/adminSubscribers — empty map if Supabase admin is unset).
        uids = [r.user_id for r in rows]
        users_map = {}
        if uids:
            try:
                users_map = get_users_map(uids)
            except SupabaseAdminError as e:
                logger.warning("adminBugReports: supabase fetch failed: %s", e)

        reports = [
            AdminBugReport.from_model(
                r,
                email=(
                    users_map.get(r.user_id).email if users_map.get(r.user_id) else ""
                ),
            )
            for r in rows
        ]
        return AdminBugReportPage(
            reports=reports, page=page, per_page=per_page, has_next=has_next
        )

    @strawberry.field(name="adminBugReportsUnreadCount")
    def admin_bug_reports_unread_count(self, info: Info) -> int:
        _admin_user_id(info)
        return BugReport.objects.filter(status=Status.NEW.value).count()


@strawberry.type
class AdminFeedbackMutation:
    @strawberry.mutation(name="adminBugReportSetStatus")
    def admin_bug_report_set_status(
        self, info: Info, id: strawberry.ID, status: str
    ) -> AdminBugReport:
        actor = _admin_user_id(info)
        if status not in {s.value for s in Status}:
            raise GraphQLError(
                f"Invalid status '{status}'", extensions={"code": "BAD_INPUT"}
            )
        r = _get_or_404(id)
        before = r.status
        r.status = status
        r.save(update_fields=["status", "updated_at"])
        audit_record(
            actor_user_id=actor,
            action="feedback.set_status",
            target_type="bug_report",
            target_id=r.id,
            payload={"before": before, "after": status},
        )
        return AdminBugReport.from_model(r)

    @strawberry.mutation(name="adminBugReportDelete")
    def admin_bug_report_delete(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        r = _get_or_404(id)
        topic = r.topic
        r.delete()
        audit_record(
            actor_user_id=actor,
            action="feedback.delete",
            target_type="bug_report",
            target_id=id,
            payload={"topic": topic},
        )
        return True

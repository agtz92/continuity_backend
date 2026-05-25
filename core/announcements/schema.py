"""GraphQL surface for in-app announcements.

Public:
- `notifications` query — returns merged list (derived + active announcements)
  for the authenticated user, priority-sorted.

Admin (under AdminQuery/AdminMutation extension):
- `adminAnnouncements` — list all (with status filter)
- `adminAnnouncement` — fetch one by id
- `adminAnnouncementCreate / Update / Publish / Archive / Delete`

All admin operations go through `_admin_user_id(info)` and audit-log
side effects via `audit_record`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from core.admin_api.audit import record as audit_record
from core.admin_api.permissions import _admin_user_id

from .models import Announcement, Severity, Status
from .services import compute_user_notifications


# ---------- Public types ----------


@strawberry.type
class Notification:
    id: str
    kind: str
    severity: str
    title: str
    body: str
    cta_label: str
    cta_url: str
    dismissible: bool
    i18n_kind: Optional[str]
    i18n_vars_json: Optional[str]


def _user_id(info: Info) -> uuid.UUID:
    uid = getattr(info.context, "user_id", None)
    if not uid:
        raise GraphQLError(
            "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
        )
    return uid


@strawberry.type
class NotificationsQuery:
    @strawberry.field
    def notifications(self, info: Info) -> list[Notification]:
        import json

        uid = _user_id(info)
        items = compute_user_notifications(uid)
        return [
            Notification(
                id=n.id,
                kind=n.kind,
                severity=n.severity,
                title=n.title,
                body=n.body,
                cta_label=n.cta_label,
                cta_url=n.cta_url,
                dismissible=n.dismissible,
                i18n_kind=n.i18n_kind,
                i18n_vars_json=json.dumps(n.i18n_vars) if n.i18n_vars else None,
            )
            for n in items
        ]


# ---------- Admin types ----------


@strawberry.type
class AdminAnnouncement:
    id: strawberry.ID
    title: str
    body: str
    severity: str
    status: str
    audience_plans: list[str]
    audience_user_ids: list[str]
    starts_at: Optional[dt.datetime]
    ends_at: Optional[dt.datetime]
    dismissible: bool
    cta_label: str
    cta_url: str
    created_by: Optional[strawberry.ID]
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, a: Announcement) -> "AdminAnnouncement":
        return cls(
            id=strawberry.ID(str(a.id)),
            title=a.title,
            body=a.body,
            severity=a.severity,
            status=a.status,
            audience_plans=list(a.audience_plans or []),
            audience_user_ids=[str(x) for x in (a.audience_user_ids or [])],
            starts_at=a.starts_at,
            ends_at=a.ends_at,
            dismissible=a.dismissible,
            cta_label=a.cta_label,
            cta_url=a.cta_url,
            created_by=strawberry.ID(str(a.created_by)) if a.created_by else None,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )


@strawberry.input
class AnnouncementInput:
    title: str
    body: Optional[str] = None
    severity: Optional[str] = None  # info | warn | error
    audience_plans: Optional[list[str]] = None
    audience_user_ids: Optional[list[str]] = None
    starts_at: Optional[dt.datetime] = None
    ends_at: Optional[dt.datetime] = None
    dismissible: Optional[bool] = None
    cta_label: Optional[str] = None
    cta_url: Optional[str] = None


def _apply_input(a: Announcement, data: AnnouncementInput) -> None:
    a.title = data.title
    if data.body is not None:
        a.body = data.body
    if data.severity is not None:
        if data.severity not in {s.value for s in Severity}:
            raise GraphQLError(
                f"Invalid severity '{data.severity}'",
                extensions={"code": "BAD_INPUT"},
            )
        a.severity = data.severity
    if data.audience_plans is not None:
        a.audience_plans = list(data.audience_plans)
    if data.audience_user_ids is not None:
        a.audience_user_ids = list(data.audience_user_ids)
    if data.starts_at is not None:
        a.starts_at = data.starts_at
    if data.ends_at is not None:
        a.ends_at = data.ends_at
    if data.dismissible is not None:
        a.dismissible = data.dismissible
    if data.cta_label is not None:
        a.cta_label = data.cta_label
    if data.cta_url is not None:
        a.cta_url = data.cta_url


def _get_or_404(id_: strawberry.ID) -> Announcement:
    try:
        return Announcement.objects.get(id=uuid.UUID(str(id_)))
    except (Announcement.DoesNotExist, ValueError):
        raise GraphQLError(
            "Announcement not found", extensions={"code": "NOT_FOUND"}
        )


@strawberry.type
class AdminAnnouncementsQuery:
    @strawberry.field(name="adminAnnouncements")
    def admin_announcements(
        self, info: Info, status: Optional[str] = None
    ) -> list[AdminAnnouncement]:
        _admin_user_id(info)
        qs = Announcement.objects.all()
        if status:
            qs = qs.filter(status=status)
        return [AdminAnnouncement.from_model(a) for a in qs]

    @strawberry.field(name="adminAnnouncement")
    def admin_announcement(self, info: Info, id: strawberry.ID) -> AdminAnnouncement:
        _admin_user_id(info)
        return AdminAnnouncement.from_model(_get_or_404(id))


@strawberry.type
class AdminAnnouncementsMutation:
    @strawberry.mutation(name="adminAnnouncementCreate")
    def create(self, info: Info, data: AnnouncementInput) -> AdminAnnouncement:
        actor = _admin_user_id(info)
        a = Announcement(created_by=actor)
        _apply_input(a, data)
        a.save()
        audit_record(
            actor_user_id=actor,
            action="announcement.create",
            target_type="announcement",
            target_id=a.id,
            payload={"title": a.title, "severity": a.severity},
        )
        return AdminAnnouncement.from_model(a)

    @strawberry.mutation(name="adminAnnouncementUpdate")
    def update(
        self, info: Info, id: strawberry.ID, data: AnnouncementInput
    ) -> AdminAnnouncement:
        actor = _admin_user_id(info)
        a = _get_or_404(id)
        _apply_input(a, data)
        a.save()
        audit_record(
            actor_user_id=actor,
            action="announcement.update",
            target_type="announcement",
            target_id=a.id,
            payload={"title": a.title, "severity": a.severity},
        )
        return AdminAnnouncement.from_model(a)

    @strawberry.mutation(name="adminAnnouncementSetStatus")
    def set_status(
        self, info: Info, id: strawberry.ID, status: str
    ) -> AdminAnnouncement:
        actor = _admin_user_id(info)
        if status not in {s.value for s in Status}:
            raise GraphQLError(
                f"Invalid status '{status}'", extensions={"code": "BAD_INPUT"}
            )
        a = _get_or_404(id)
        before = a.status
        a.status = status
        a.save(update_fields=["status", "updated_at"])
        audit_record(
            actor_user_id=actor,
            action="announcement.set_status",
            target_type="announcement",
            target_id=a.id,
            payload={"before": before, "after": status},
        )
        return AdminAnnouncement.from_model(a)

    @strawberry.mutation(name="adminAnnouncementDelete")
    def delete(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        a = _get_or_404(id)
        a.delete()
        audit_record(
            actor_user_id=actor,
            action="announcement.delete",
            target_type="announcement",
            target_id=id,
            payload={"title": a.title},
        )
        return True

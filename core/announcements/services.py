"""Compute the in-app notification list for a given user.

Two sources merged into a single, priority-sorted list:

1. **Derived** — quota overages (and future derived signals like
   "subscription cancelled, renews on X"). Computed every fetch.
2. **Announcements** — admin-managed banners filtered by audience and
   time window.

The frontend renders these as banners at the top of the dashboard. The
caller (GraphQL resolver) translates the dataclass into the API shape.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

from core.assistant.models import AccountProfile, Plan
from core.quotas import ENTITY_QUOTAS, _count

from .models import Announcement, Severity, Status


# Stable string IDs the frontend uses as dismissal keys / React keys.
# Derived notifications use deterministic IDs so a dismissed banner stays
# dismissed across page loads (when the underlying state still matches).
DERIVED_QUOTA_PREFIX = "quota_over."


@dataclass
class UserNotification:
    id: str
    kind: str  # "quota_over" | "announcement" | "system"
    severity: str  # info | warn | error
    title: str
    body: str
    cta_label: str
    cta_url: str
    dismissible: bool
    # i18n key for derived notifications. None for announcements (admin
    # writes title/body literally — no translation key).
    i18n_kind: Optional[str] = None
    # Interpolation data for derived notifications.
    i18n_vars: Optional[dict] = None


# ---------- Derived ----------

# Which kinds make sense as "you're over your quota" warnings.
# Per-project counts (tasks_per_project, notes_per_project) aren't useful
# here because they require iterating every project; the user fixes them
# project-by-project when they edit.
_DERIVED_QUOTA_KINDS = [
    "projects",
    "tasks_total",
    "routines",
    "ideas",
    "categories",
]


def _quota_warnings(
    user_id: uuid.UUID,
    plan: str,
    *,
    cancel_scheduled: bool = False,
    renews_at_iso: Optional[str] = None,
) -> list[UserNotification]:
    out: list[UserNotification] = []
    seen_kinds: set[str] = set()

    # 1. Current overages — already exceeding the cap of the *current* plan.
    for kind in _DERIVED_QUOTA_KINDS:
        cap = ENTITY_QUOTAS.get(kind, {}).get(plan)
        if cap is None:
            continue  # Unlimited — nothing to warn about
        current = _count(kind, user_id, project_id=None)
        if current <= cap:
            continue
        over_by = current - cap
        seen_kinds.add(kind)
        out.append(
            UserNotification(
                id=f"{DERIVED_QUOTA_PREFIX}{kind}",
                kind="quota_over",
                severity="warn",
                # Title/body are placeholders — frontend resolves the real
                # copy from i18n using i18n_kind + i18n_vars.
                title="",
                body="",
                cta_label="",
                cta_url="",
                dismissible=False,
                i18n_kind=kind,
                i18n_vars={
                    "current": current,
                    "cap": cap,
                    "over_by": over_by,
                    "plan": plan,
                },
            )
        )

    # 2. Future overages — user is scheduled to drop to free at end of
    # period. Warn now if their current counts exceed the *free* plan caps,
    # so they have time to archive before the downgrade hits.
    if cancel_scheduled:
        future_plan = Plan.FREE.value
        for kind in _DERIVED_QUOTA_KINDS:
            if kind in seen_kinds:
                continue  # Already warning about the current overage
            future_cap = ENTITY_QUOTAS.get(kind, {}).get(future_plan)
            if future_cap is None:
                continue
            current = _count(kind, user_id, project_id=None)
            if current <= future_cap:
                continue
            over_by = current - future_cap
            out.append(
                UserNotification(
                    id=f"quota_will_exceed.{kind}",
                    kind="quota_will_exceed",
                    severity="warn",
                    title="",
                    body="",
                    cta_label="",
                    cta_url="",
                    dismissible=True,
                    i18n_kind=kind,
                    i18n_vars={
                        "current": current,
                        "cap": future_cap,
                        "over_by": over_by,
                        "future_plan": future_plan,
                        "date_iso": renews_at_iso or "",
                    },
                )
            )
    return out


# ---------- Announcements ----------


def _announcement_visible_to(a: Announcement, user_id: uuid.UUID, plan: str) -> bool:
    has_plan_filter = bool(a.audience_plans)
    has_user_filter = bool(a.audience_user_ids)
    if not has_plan_filter and not has_user_filter:
        return True  # "Everyone"
    plan_match = has_plan_filter and plan in (a.audience_plans or [])
    user_match = has_user_filter and str(user_id) in (a.audience_user_ids or [])
    return plan_match or user_match


def _active_announcements(user_id: uuid.UUID, plan: str) -> list[UserNotification]:
    now = timezone.now()
    qs = Announcement.objects.filter(status=Status.PUBLISHED)
    out: list[UserNotification] = []
    for a in qs:
        if a.starts_at and a.starts_at > now:
            continue
        if a.ends_at and a.ends_at < now:
            continue
        if not _announcement_visible_to(a, user_id, plan):
            continue
        out.append(
            UserNotification(
                id=f"ann.{a.id}",
                kind="announcement",
                severity=a.severity,
                title=a.title,
                body=a.body,
                cta_label=a.cta_label,
                cta_url=a.cta_url,
                dismissible=a.dismissible,
            )
        )
    return out


# ---------- Combined ----------


_SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


def compute_user_notifications(user_id: uuid.UUID) -> list[UserNotification]:
    """Return the merged, priority-sorted list for this user.

    Order:
    1. By severity (error → warn → info)
    2. Within severity: derived first (quota), then announcements (newest first)
    """
    profile = AccountProfile.objects.filter(user_id=user_id).first()
    plan = (profile.plan if profile else Plan.FREE.value)
    is_exempt = bool(profile and profile.is_billing_exempt)
    cancel_scheduled = bool(profile and profile.cancel_at_period_end)
    renews_at_iso = (
        profile.plan_renews_at.isoformat()
        if profile and profile.plan_renews_at
        else None
    )

    # Skip quota warnings for exempt accounts — staff comp shouldn't be nagged.
    derived = (
        []
        if is_exempt
        else _quota_warnings(
            user_id,
            plan,
            cancel_scheduled=cancel_scheduled,
            renews_at_iso=renews_at_iso,
        )
    )
    announcements = _active_announcements(user_id, plan)

    items = derived + announcements
    # Order: severity first, then current overages before forecasts before announcements.
    _kind_order = {"quota_over": 0, "quota_will_exceed": 1}
    items.sort(
        key=lambda n: (
            _SEVERITY_ORDER.get(n.severity, 99),
            _kind_order.get(n.kind, 2),
        )
    )
    return items

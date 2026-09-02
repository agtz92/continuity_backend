"""Tipos GraphQL (Strawberry) del panel admin.

Extraídos de admin_api/schema.py (ver AUDITORIA_CODIGO.md). Solo definiciones de
tipos; sin resolvers, helpers ni servicios. `schema.py` los re-importa con
`import *`.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import strawberry

from core.assistant.models import Plan  # noqa: F401  (usado en defaults de tipos)

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
    # Total "actions with effect" in the last 30 days, all channels combined.
    interactions_30d: int = 0


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
    # Identifiers at whichever issuer sold the plan — see `billing_source`.
    # Renamed from `stripe_*`: they now carry App Store / Google Play ids too.
    billing_customer_id: str
    billing_transaction_id: str
    created_at: Optional[dt.datetime]
    last_sign_in_at: Optional[dt.datetime]
    email_confirmed_at: Optional[dt.datetime]
    banned_until: Optional[dt.datetime]
    counts: UserCounts
    last_activity: Optional[dt.datetime]
    usage_last_30d: list[UsageDayPoint]
    notifications: Optional[NotificationPrefs]
    # Interaction counts (actions with effect) over the last 30 days, split by
    # channel (web / mobile / connector / unknown). Counts only — no content.
    interactions_by_source: list[LabeledCount]
    interactions_30d_total: int


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
class LabeledCount:
    """Generic (label, count) pair for categorical breakdowns."""

    label: str
    count: int


@strawberry.type
class AdminMcpConnection:
    user_id: strawberry.ID
    client_id: str
    client_name: str
    connected_at: Optional[dt.datetime] = None


@strawberry.type
class AdminMcpConnectionEvent:
    user_id: strawberry.ID
    client_id: str
    client_name: str
    event: str
    created: dt.datetime


@strawberry.type
class AdminMcpStats:
    active_connections: int
    distinct_users: int
    by_client: list[LabeledCount]


@strawberry.type
class SeriesPoint:
    """One day's data point for a time series chart."""

    date: dt.date
    value: int


@strawberry.type
class RecentSignup:
    user_id: strawberry.ID
    email: str
    created_at: Optional[dt.datetime]
    plan: str


@strawberry.type
class AdminSystemStats:
    # Headline counts.
    total_users: int  # Real Supabase auth.users count.
    total_accounts: int  # AccountProfile rows — may include orphans, kept for back-compat.
    admins: int
    plan_counts: list[PlanCount]

    # Engagement.
    dau: int
    wau: int
    mau: int
    signups_series: list[SeriesPoint]  # last 30 days, by day
    activity_series: list[SeriesPoint]  # DAU per day, last 30 days
    activity_by_kind: list[LabeledCount]  # last 30 days

    # Product objects.
    project_state_counts: list[LabeledCount]
    tasks_open: int
    tasks_done_30d: int
    ideas_total: int

    # CMS.
    blog_posts_published: int
    blog_posts_draft: int
    pages_published: int

    # System health.
    pending_jobs: int
    failed_jobs: int
    job_status_counts: list[JobStatusCount]

    # Lists.
    recent_signups: list[RecentSignup]


@strawberry.type
class PlanPeriodBreakdown:
    plan: str  # "pro" | "studio"
    period: str  # "monthly" | "annual"
    count: int
    monthly_cents_each: int  # monthly-equivalent per subscriber (annual ÷ 12)
    total_monthly_cents: int  # count * monthly_cents_each


@strawberry.type
class SourceBreakdown:
    """Revenue split by who sold the subscription.

    Gross is what subscribers are billed; net is what survives the channel's
    cut — Apple and Google keep a commission, the web channel pays card
    processing plus RevenueCat. Both
    numbers matter and they are not close to each other, so the dashboard
    shows them side by side rather than picking one.
    """

    source: str  # "web" | "apple" | "google"
    count: int
    gross_monthly_cents: int
    net_monthly_cents: int


@strawberry.type
class UpcomingChurnRow:
    user_id: strawberry.ID
    email: str
    plan: str
    period: str
    plan_renews_at: Optional[dt.datetime]
    monthly_cents: int


@strawberry.type
class AdminBillingOverview:
    currency: str  # ISO 4217 lowercase ("usd", "mxn")
    is_test_mode: bool
    paying_subscribers: int
    mrr_cents: int  # gross — what subscribers are billed
    # Net of store commission and web-channel fees. Diverges from `mrr_cents` as
    # the mobile channel grows, which is exactly why it's reported.
    net_mrr_cents: int
    arr_cents: int
    net_arr_cents: int
    billing_exempt_count: int
    pending_cancellations: int
    breakdown: list[PlanPeriodBreakdown]
    by_source: list[SourceBreakdown]
    upcoming_churn: list[UpcomingChurnRow]


@strawberry.type
class AdminSubscriberRow:
    user_id: strawberry.ID
    email: str
    plan: str
    period: str  # "monthly" | "annual" | "" when unknown
    monthly_cents: int
    # "web" | "apple" | "google", or "unknown" if the row was left half
    # written — we never guess a channel.
    billing_source: str
    net_monthly_cents: int
    plan_renews_at: Optional[dt.datetime]
    cancel_at_period_end: bool
    is_billing_exempt: bool
    # One set of identifiers for every channel. Which issuer they belong to is
    # `billing_source`; the admin UI must branch on that before deep-linking,
    # since a card-processor URL is meaningless for a Play purchase token.
    billing_customer_id: str
    billing_transaction_id: str
    billing_product_id: str


@strawberry.type
class AdminSubscriberPage:
    rows: list[AdminSubscriberRow]
    page: int
    per_page: int
    has_next: bool
    total: int


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


__all__ = [
    "Me",
    "UserCounts",
    "AdminUserSummary",
    "AdminUserPage",
    "UsageDayPoint",
    "NotificationLinkInfo",
    "NotificationPrefs",
    "AdminUserDetail",
    "AdminNotificationJob",
    "AdminNotificationJobPage",
    "PlanCount",
    "JobStatusCount",
    "LabeledCount",
    "AdminMcpConnection",
    "AdminMcpConnectionEvent",
    "AdminMcpStats",
    "SeriesPoint",
    "RecentSignup",
    "AdminSystemStats",
    "PlanPeriodBreakdown",
    "SourceBreakdown",
    "UpcomingChurnRow",
    "AdminBillingOverview",
    "AdminSubscriberRow",
    "AdminSubscriberPage",
    "AdminAuditEntry",
    "AdminAuditPage",
]

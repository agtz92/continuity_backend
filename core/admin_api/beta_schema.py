"""Admin GraphQL for the beta lifecycle: cohort list, pipeline, and the
mutations to manage beta status / billing exemption / global config.

Kept separate from the (large) admin_api/schema.py and merged into the root
schema in core/schema.py. All fields gate on `_admin_user_id` and every write
calls `audit_record`. Per the design invariant, beta mutations NEVER touch
is_billing_exempt — only `adminSetBillingExempt` does, and the automatic
reclaim. The "days inactive" column reuses `beta_lifecycle.significant_events_q`
so admin and cron measure identically (incl. the Graveyard auto-stall exclusion).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Optional

import strawberry
from django.db.models import Count, Max, Q
from django.utils import timezone
from graphql import GraphQLError
from strawberry.types import Info

from core.assistant.models import AccountProfile, BetaStatus
from core.models import Activity
from core.notifications.models import EmailSend
from core.services import app_config, beta_lifecycle

from .audit import record as audit_record
from .permissions import _admin_user_id
from .supabase_admin import SupabaseAdminError, fetch_all_users, get_user


@strawberry.type
class BetaUserRow:
    user_id: strawberry.ID
    email: str
    created_at: Optional[dt.datetime]
    beta_cohort: bool
    beta_status: str
    is_billing_exempt: bool
    billing_exempt_reason: str
    billing_exempt_until: Optional[dt.datetime]
    beta_enrolled_at: Optional[dt.datetime]
    days_since_last_significant_event: Optional[int]
    last_email_id: str
    last_email_at: Optional[dt.datetime]


@strawberry.type
class BetaLabeledCount:
    label: str
    count: int


# AppConfig key holding the cron heartbeat (last-run timestamp/mode/summary).
# It's operational state, not a tunable knob: written by run_beta_lifecycle,
# surfaced via adminBetaPipeline, and hidden from the adminAppConfig knob list.
HEARTBEAT_KEY = "beta_lifecycle_last_run"


@strawberry.type
class BetaPipeline:
    status_counts: list[BetaLabeledCount]
    threshold_counts: list[BetaLabeledCount]
    recent_reclaims: list[BetaUserRow]
    # Cron heartbeat: null when run_beta_lifecycle has never run.
    last_run_at: Optional[str]
    last_run_mode: str
    last_run_summary: str


@strawberry.type
class AppConfigRow:
    key: str
    value_json: str


# ---------- helpers ----------


def _uid(user_id: strawberry.ID) -> uuid.UUID:
    try:
        return uuid.UUID(str(user_id))
    except ValueError:
        raise GraphQLError("Invalid user_id", extensions={"code": "BAD_INPUT"})


def _last_sig_map(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dt.datetime]:
    rows = (
        Activity.objects.filter(
            Q(user_id__in=user_ids) & beta_lifecycle.significant_events_q()
        )
        .values("user_id")
        .annotate(last=Max("created"))
    )
    return {r["user_id"]: r["last"] for r in rows}


def _last_email_map(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, EmailSend]:
    m: dict[uuid.UUID, EmailSend] = {}
    for es in EmailSend.objects.filter(user_id__in=user_ids).order_by("created"):
        m[es.user_id] = es  # ascending → last write wins = most recent
    return m


def _build_rows(profiles: list[AccountProfile], now: dt.datetime) -> list[BetaUserRow]:
    ids = [p.user_id for p in profiles]
    # Resolve emails via the same bulk source as adminUsers so the two tables
    # always agree. (get_users_map did one fragile request per id, which could
    # leave real users showing as a bare id when a lookup failed.)
    try:
        emails = {u.id: u for u in fetch_all_users()}
    except SupabaseAdminError:
        emails = {}
    last_sig = _last_sig_map(ids)
    last_email = _last_email_map(ids)

    rows: list[BetaUserRow] = []
    for p in profiles:
        anchor = last_sig.get(p.user_id) or p.beta_enrolled_at
        days = (now - anchor).days if anchor else None
        s_user = emails.get(p.user_id)
        es = last_email.get(p.user_id)
        rows.append(
            BetaUserRow(
                user_id=strawberry.ID(str(p.user_id)),
                email=s_user.email if s_user else "",
                created_at=p.created,
                beta_cohort=p.beta_cohort,
                beta_status=p.beta_status,
                is_billing_exempt=p.is_billing_exempt,
                billing_exempt_reason=p.billing_exempt_reason,
                billing_exempt_until=p.billing_exempt_until,
                beta_enrolled_at=p.beta_enrolled_at,
                days_since_last_significant_event=days,
                last_email_id=es.email_id if es else "",
                last_email_at=es.sent_at if es else None,
            )
        )
    return rows


def _single_row(uid: uuid.UUID, now: dt.datetime) -> BetaUserRow:
    p = AccountProfile.objects.get(user_id=uid)
    return _build_rows([p], now)[0]


# ---------- Query ----------


@strawberry.type
class AdminBetaQuery:
    @strawberry.field(name="adminBetaUsers")
    def admin_beta_users(
        self,
        info: Info,
        beta_status: Optional[str] = None,
        billing_exempt: Optional[bool] = None,
        days_inactive_min: Optional[int] = None,
    ) -> list[BetaUserRow]:
        _admin_user_id(info)
        now = timezone.now()
        qs = AccountProfile.objects.filter(beta_cohort=True)
        if beta_status:
            qs = qs.filter(beta_status=beta_status)
        if billing_exempt is not None:
            qs = qs.filter(is_billing_exempt=billing_exempt)
        profiles = list(qs.order_by("beta_enrolled_at"))
        rows = _build_rows(profiles, now)
        if days_inactive_min is not None:
            rows = [
                r
                for r in rows
                if r.days_since_last_significant_event is not None
                and r.days_since_last_significant_event >= days_inactive_min
            ]
        return rows

    @strawberry.field(name="adminBetaPipeline")
    def admin_beta_pipeline(self, info: Info) -> BetaPipeline:
        _admin_user_id(info)
        now = timezone.now()

        status_counts = [
            BetaLabeledCount(label=r["beta_status"] or "unknown", count=r["c"])
            for r in AccountProfile.objects.filter(beta_cohort=True)
            .values("beta_status")
            .annotate(c=Count("user_id"))
        ]

        active = list(
            AccountProfile.objects.filter(
                beta_cohort=True, beta_status=BetaStatus.ACTIVE
            )
        )
        last_sig = _last_sig_map([p.user_id for p in active])
        buckets = {"day_3": 0, "day_7": 0, "day_14": 0, "day_21_plus": 0}
        for p in active:
            anchor = last_sig.get(p.user_id) or p.beta_enrolled_at
            if not anchor:
                continue
            d = (now - anchor).days
            if d >= 3:
                buckets["day_3"] += 1
            if d >= 7:
                buckets["day_7"] += 1
            if d >= 14:
                buckets["day_14"] += 1
            if d >= 21:
                buckets["day_21_plus"] += 1
        threshold_counts = [BetaLabeledCount(label=k, count=v) for k, v in buckets.items()]

        reclaimed = list(
            AccountProfile.objects.filter(beta_status=BetaStatus.RECLAIMED).order_by(
                "-updated_at"
            )[:10]
        )
        hb = app_config.get(HEARTBEAT_KEY) or {}
        return BetaPipeline(
            status_counts=status_counts,
            threshold_counts=threshold_counts,
            recent_reclaims=_build_rows(reclaimed, now),
            last_run_at=hb.get("at") or None,
            last_run_mode=hb.get("mode") or "",
            last_run_summary=hb.get("summary") or "",
        )

    @strawberry.field(name="adminAppConfig")
    def admin_app_config(self, info: Info) -> list[AppConfigRow]:
        _admin_user_id(info)
        from core.models import AppConfig

        # Surface defaults even for keys not yet persisted. The cron heartbeat is
        # operational state, not a knob — keep it out of the config list.
        merged = dict(app_config.DEFAULTS)
        for row in AppConfig.objects.all():
            if row.key == HEARTBEAT_KEY:
                continue
            merged[row.key] = row.value
        return [
            AppConfigRow(key=k, value_json=json.dumps(v)) for k, v in sorted(merged.items())
        ]


# ---------- Mutation ----------


@strawberry.type
class AdminBetaMutation:
    @strawberry.mutation(name="adminSetBeta")
    def admin_set_beta(
        self,
        info: Info,
        user_id: strawberry.ID,
        beta_cohort: Optional[bool] = None,
        beta_status: Optional[str] = None,
    ) -> BetaUserRow:
        """Set beta_cohort / beta_status. NEVER touches is_billing_exempt."""
        actor = _admin_user_id(info)
        uid = _uid(user_id)
        if beta_status is not None and beta_status not in BetaStatus.values:
            raise GraphQLError("Invalid beta_status", extensions={"code": "BAD_INPUT"})

        profile, _ = AccountProfile.objects.get_or_create(user_id=uid)
        changes: dict = {}
        fields = ["updated_at"]
        if beta_cohort is not None and beta_cohort != profile.beta_cohort:
            changes["beta_cohort"] = {"before": profile.beta_cohort, "after": beta_cohort}
            profile.beta_cohort = beta_cohort
            fields.append("beta_cohort")
            if beta_cohort and not profile.beta_enrolled_at:
                profile.beta_enrolled_at = timezone.now()
                profile.beta_status = BetaStatus.ACTIVE
                fields += ["beta_enrolled_at", "beta_status"]
        if beta_status is not None and beta_status != profile.beta_status:
            changes["beta_status"] = {"before": profile.beta_status, "after": beta_status}
            profile.beta_status = beta_status
            if "beta_status" not in fields:
                fields.append("beta_status")
        profile.save(update_fields=fields)

        audit_record(
            actor_user_id=actor,
            action="beta.set_fields",
            target_type="account_profile",
            target_id=uid,
            payload=changes,
        )
        return _single_row(uid, timezone.now())

    @strawberry.mutation(name="adminSetBillingExempt")
    def admin_set_billing_exempt(
        self,
        info: Info,
        user_id: strawberry.ID,
        is_billing_exempt: bool,
        reason: Optional[str] = None,
        until: Optional[dt.datetime] = None,
    ) -> BetaUserRow:
        """Set exemption + reason/until. Independent of beta cohort."""
        actor = _admin_user_id(info)
        uid = _uid(user_id)
        profile, _ = AccountProfile.objects.get_or_create(user_id=uid)
        before = {
            "is_billing_exempt": profile.is_billing_exempt,
            "reason": profile.billing_exempt_reason,
        }
        profile.is_billing_exempt = is_billing_exempt
        if reason is not None:
            profile.billing_exempt_reason = reason
        if not is_billing_exempt:
            profile.billing_exempt_reason = ""
            profile.billing_exempt_until = None
        else:
            profile.billing_exempt_until = until
        profile.save(
            update_fields=[
                "is_billing_exempt",
                "billing_exempt_reason",
                "billing_exempt_until",
                "updated_at",
            ]
        )
        audit_record(
            actor_user_id=actor,
            action="billing.set_exempt",
            target_type="account_profile",
            target_id=uid,
            payload={"before": before, "after": is_billing_exempt, "reason": reason},
        )
        return _single_row(uid, timezone.now())

    @strawberry.mutation(name="adminSendTestEmail")
    def admin_send_test_email(
        self, info: Info, email_id: str, locale: str = "en"
    ) -> str:
        """Send one rendered template to the calling admin's own email. Bypasses
        dry_run and the email_sends ledger (it's a deliverability test, not a
        real lifecycle send). Subject is prefixed with [TEST]."""
        from core.notifications import lifecycle
        from core.notifications.email_templates import TEMPLATES, render
        from core.notifications.providers.base import ProviderError
        from core.notifications.providers.resend import ResendEmailProvider

        actor = _admin_user_id(info)
        if email_id not in TEMPLATES:
            raise GraphQLError(
                f"Unknown email_id: {email_id}", extensions={"code": "BAD_INPUT"}
            )
        loc = "es" if str(locale).lower().startswith("es") else "en"
        try:
            user = get_user(actor)
        except SupabaseAdminError:
            user = None
        to = user.email if user else ""
        if not to:
            raise GraphQLError(
                "Could not resolve your email", extensions={"code": "NO_EMAIL"}
            )

        ctx = lifecycle._build_context(actor, {"days_inactive": 7}, loc)
        subject, html, text = render(email_id, ctx, loc)
        try:
            result = ResendEmailProvider().send(to, f"[TEST] {subject}", html, text)
        except ProviderError as e:
            raise GraphQLError(str(e), extensions={"code": "PROVIDER_ERROR"})
        if not result.success:
            raise GraphQLError(result.error, extensions={"code": "SEND_FAILED"})

        audit_record(
            actor_user_id=actor,
            action="beta.test_email",
            target_type="email",
            target_id=email_id,
            payload={"to": to, "locale": loc},
        )
        return f"Enviado a {to} ({email_id} · {loc})"

    @strawberry.mutation(name="adminSetAppConfig")
    def admin_set_app_config(
        self, info: Info, key: str, value_json: str
    ) -> AppConfigRow:
        actor = _admin_user_id(info)
        if key not in app_config.DEFAULTS:
            raise GraphQLError(
                f"Unknown config key: {key}", extensions={"code": "BAD_INPUT"}
            )
        try:
            value = json.loads(value_json)
        except json.JSONDecodeError:
            raise GraphQLError("value_json is not valid JSON", extensions={"code": "BAD_INPUT"})

        before = app_config.get(key)
        app_config.set(key, value)
        audit_record(
            actor_user_id=actor,
            action="config.set",
            target_type="app_config",
            target_id=key,
            payload={"key": key, "before": before, "after": value},
        )
        return AppConfigRow(key=key, value_json=json.dumps(value))

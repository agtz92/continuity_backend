"""Beta inactivity lifecycle: classify cohort members and drive the nudge /
reclaim sequence. Driven daily by the `run_beta_lifecycle` command.

Three tiers, by activity span (last - first significant event):
- ghost: no significant event since enrollment -> clock from beta_enrolled_at.
- brief: had activity but span < established_min_activity_days.
- established: span >= established_min_activity_days.

Each run picks the SINGLE furthest-due email per user (idempotent), so cold
start sends one email, not the whole retro sequence. Invariant: never reclaim
without a reclaim_warn email whose reclaim_warned_at is >= grace days old.

dry_run (app_config) is enforced inside lifecycle.deliver: in dry_run nothing
is sent and we apply NO side effects (warned_at / reclaim).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Optional

from django.db.models import Max, Min, Q
from django.utils import timezone

from core.notifications import lifecycle

# Sentinel actor for system-driven audit rows (no human actor).
SYSTEM_ACTOR = uuid.UUID(int=0)


@dataclass(frozen=True)
class Step:
    day: int
    email_id: str
    type: str  # "nudge" | "warn" | "reclaim"


def significant_events_q() -> Q:
    """Q over Activity for engagement signals. Excludes the Graveyard
    auto-stall (project_status_changed -> 'stalled'), which is system-generated
    and must NOT reset the inactivity clock. See docs/PROPOSAL.md §0."""
    from core.services import app_config

    sig = app_config.get_list("significant_event_kinds")
    return Q(kind__in=sig) & ~Q(kind="project_status_changed", new_value="stalled")


def _load_config() -> dict:
    from core.services import app_config

    return {
        "ghost_nudge_days": app_config.get_list("ghost_nudge_days"),
        "ghost_reclaim_day": app_config.get_int("ghost_reclaim_day"),
        "reengage_days": app_config.get_list("reengage_days"),
        "brief_reclaim_days": app_config.get_int("brief_reclaim_days"),
        "dormant_reclaim_days": app_config.get_int("dormant_reclaim_days"),
        "established_min_activity_days": app_config.get_int("established_min_activity_days"),
        "reclaim_warn_grace_days": app_config.get_int("reclaim_warn_grace_days"),
    }


def classify(user_id: uuid.UUID, beta_enrolled_at, now: dt.datetime, cfg: dict):
    """Return (tier, anchor, days_inactive, last_activity). anchor is None when
    a ghost has no beta_enrolled_at (shouldn't happen for a real beta member)."""
    from core.models import Activity

    agg = Activity.objects.filter(Q(user_id=user_id) & significant_events_q()).aggregate(
        first=Min("created"), last=Max("created")
    )
    first, last = agg["first"], agg["last"]
    if first is None:
        tier, anchor = "ghost", beta_enrolled_at
    else:
        span_days = (last - first).days
        tier = "established" if span_days >= cfg["established_min_activity_days"] else "brief"
        anchor = last
    if anchor is None:
        return tier, None, None, last
    days_inactive = (now - anchor).days
    return tier, anchor, days_inactive, last


def steps_for(tier: str, cfg: dict) -> list[Step]:
    if tier == "ghost":
        n = cfg["ghost_nudge_days"]
        return [
            Step(n[0], "inactivity_1", "nudge"),
            Step(n[1], "inactivity_2", "nudge"),
            Step(n[2], "inactivity_3", "warn"),
            Step(cfg["ghost_reclaim_day"], "inactivity_4", "reclaim"),
        ]
    r = cfg["reengage_days"]
    threshold = cfg["brief_reclaim_days"] if tier == "brief" else cfg["dormant_reclaim_days"]
    warn_day = threshold - cfg["reclaim_warn_grace_days"]
    return [
        Step(r[0], "reengage_1", "nudge"),
        Step(r[1], "reengage_2", "nudge"),
        Step(warn_day, "reclaim_warn", "warn"),
        Step(threshold, "reclaim_final", "reclaim"),
    ]


def _warn_step(steps: list[Step]) -> Optional[Step]:
    for s in steps:
        if s.type == "warn":
            return s
    return None


def process_profile(profile, now: Optional[dt.datetime] = None, cfg: Optional[dict] = None) -> str:
    """Evaluate one active beta member and take at most one action. Returns a
    short result code (for logging/tests)."""
    now = now or timezone.now()
    cfg = cfg or _load_config()

    tier, anchor, days_inactive, last = classify(
        profile.user_id, profile.beta_enrolled_at, now, cfg
    )
    if anchor is None:
        return "skip_no_anchor"

    steps = steps_for(tier, cfg)
    episode_key = "" if tier == "ghost" else anchor.date().isoformat()
    extra = {
        "days_inactive": days_inactive,
        "last_project_title": _last_project_title(profile.user_id),
    }

    due = [s for s in steps if days_inactive >= s.day]
    if not due:
        # User is active enough — clear any stale warn from a prior episode.
        if profile.reclaim_warned_at is not None:
            profile.reclaim_warned_at = None
            profile.save(update_fields=["reclaim_warned_at", "updated_at"])
        return "active_no_action"

    target = due[-1]  # furthest-due step

    if target.type == "nudge":
        return lifecycle.deliver(
            profile.user_id, target.email_id, episode_key=episode_key, extra_ctx=extra
        )

    if target.type == "warn":
        return _send_warn(profile, target, episode_key, now, extra)

    # target.type == "reclaim"
    warned = profile.reclaim_warned_at
    if warned is None:
        # Cold-start / never warned: send the warn first, never reclaim blind.
        warn = _warn_step(steps)
        if warn is None:
            return "no_warn_step"
        return _send_warn(profile, warn, episode_key, now, extra)
    grace = dt.timedelta(days=cfg["reclaim_warn_grace_days"])
    if (now - warned) < grace:
        return "awaiting_grace"
    return _do_reclaim(profile, target, episode_key, now, extra)


def _send_warn(profile, step: Step, episode_key: str, now, extra) -> str:
    result = lifecycle.deliver(
        profile.user_id, step.email_id, episode_key=episode_key, extra_ctx=extra
    )
    if result == lifecycle.SENT:  # real send only — dry_run applies no side effects
        profile.reclaim_warned_at = now
        profile.save(update_fields=["reclaim_warned_at", "updated_at"])
    return result


def _do_reclaim(profile, step: Step, episode_key: str, now, extra) -> str:
    from core.admin_api import audit
    from core.assistant.models import BetaStatus

    result = lifecycle.deliver(
        profile.user_id, step.email_id, episode_key=episode_key, extra_ctx=extra
    )
    if result != lifecycle.SENT:
        return result
    profile.beta_status = BetaStatus.RECLAIMED
    profile.is_billing_exempt = False
    profile.billing_exempt_reason = ""
    profile.reclaim_warned_at = None
    profile.save(
        update_fields=[
            "beta_status",
            "is_billing_exempt",
            "billing_exempt_reason",
            "reclaim_warned_at",
            "updated_at",
        ]
    )
    audit.record(
        actor_user_id=SYSTEM_ACTOR,
        action="beta.reclaimed",
        target_type="account_profile",
        target_id=profile.user_id,
        payload={"email_id": step.email_id, "via": "auto_inactivity"},
    )
    return "reclaimed"


def _last_project_title(user_id: uuid.UUID) -> str:
    from core.models import Project

    name = (
        Project.objects.filter(user_id=user_id)
        .order_by("-created")
        .values_list("name", flat=True)
        .first()
    )
    # Empty -> lifecycle._build_context supplies a locale-aware fallback.
    return name or ""


def run(now: Optional[dt.datetime] = None) -> dict[str, int]:
    """Process every active beta member. Returns a tally of result codes."""
    from core.assistant.models import AccountProfile, BetaStatus

    now = now or timezone.now()
    cfg = _load_config()
    counts: dict[str, int] = {}
    qs = AccountProfile.objects.filter(
        beta_cohort=True, beta_status=BetaStatus.ACTIVE
    )
    for profile in qs.iterator():
        result = process_profile(profile, now=now, cfg=cfg)
        counts[result] = counts.get(result, 0) + 1
    return counts

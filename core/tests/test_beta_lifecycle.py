"""Tests for the beta inactivity lifecycle (classification, nudges, reclaim,
dry_run safety, cold start, and the Graveyard auto-stall exclusion)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.utils import timezone

from core.admin_api.models import AdminAuditLog
from core.assistant.models import AccountProfile, BetaStatus
from core.models import Activity
from core.notifications import lifecycle
from core.notifications.models import EmailSend
from core.notifications.providers.base import DeliveryResult
from core.services import app_config, beta_lifecycle

NOW = timezone.now()


def _profile(enrolled_days_ago: int, **kw) -> AccountProfile:
    return AccountProfile.objects.create(
        user_id=uuid.uuid4(),
        beta_cohort=True,
        beta_status=BetaStatus.ACTIVE,
        beta_enrolled_at=NOW - dt.timedelta(days=enrolled_days_ago),
        is_billing_exempt=True,
        billing_exempt_reason="beta",
        **kw,
    )


def _activity(user_id, kind, days_ago, new_value=""):
    a = Activity.objects.create(user_id=user_id, kind=kind, new_value=new_value)
    Activity.objects.filter(id=a.id).update(created=NOW - dt.timedelta(days=days_ago))


def _go_live(monkeypatch, success=True):
    app_config.set("dry_run", False)
    monkeypatch.setattr(
        "core.admin_api.supabase_admin.get_user",
        lambda uid: type("U", (), {"email": "u@example.com"})(),
    )

    class _P:
        def send(self, to, subject, html, text="", **kw):
            return DeliveryResult(success=success, external_message_id="m1")

    monkeypatch.setattr(lifecycle, "ResendEmailProvider", _P)


# --- Classification / Graveyard exclusion -------------------------------------

@pytest.mark.django_db
def test_classify_ghost_when_no_significant_events():
    p = _profile(10)
    tier, anchor, days, _ = beta_lifecycle.classify(
        p.user_id, p.beta_enrolled_at, NOW, beta_lifecycle._load_config()
    )
    assert tier == "ghost"
    assert days == 10


@pytest.mark.django_db
def test_classify_established_vs_brief_by_span():
    est = _profile(60)
    _activity(est.user_id, "project_created", days_ago=50)
    _activity(est.user_id, "task_created", days_ago=10)  # span 40 >= 30
    tier, _, days, _ = beta_lifecycle.classify(
        est.user_id, est.beta_enrolled_at, NOW, beta_lifecycle._load_config()
    )
    assert tier == "established"
    assert days == 10

    brief = _profile(60)
    _activity(brief.user_id, "project_created", days_ago=20)
    _activity(brief.user_id, "task_created", days_ago=12)  # span 8 < 30
    tier2, _, _, _ = beta_lifecycle.classify(
        brief.user_id, brief.beta_enrolled_at, NOW, beta_lifecycle._load_config()
    )
    assert tier2 == "brief"


@pytest.mark.django_db
def test_auto_stall_event_is_excluded_from_significant():
    # Real engagement 40 days ago, then a SYSTEM auto-stall 2 days ago.
    p = _profile(60)
    _activity(p.user_id, "project_created", days_ago=40)
    _activity(p.user_id, "project_status_changed", days_ago=2, new_value="stalled")
    tier, _, days, _ = beta_lifecycle.classify(
        p.user_id, p.beta_enrolled_at, NOW, beta_lifecycle._load_config()
    )
    # The stall must NOT reset the clock: anchor stays at the real event (40d).
    assert days == 40
    # A user-driven kill (non-stalled) DOES count.
    _activity(p.user_id, "project_status_changed", days_ago=1, new_value="killed")
    _, _, days2, _ = beta_lifecycle.classify(
        p.user_id, p.beta_enrolled_at, NOW, beta_lifecycle._load_config()
    )
    assert days2 == 1


# --- Ghost path ---------------------------------------------------------------

@pytest.mark.django_db
def test_ghost_day3_previews_inactivity_1_in_dry_run():
    p = _profile(3)
    assert beta_lifecycle.process_profile(p, now=NOW) == lifecycle.DRY_RUN
    row = EmailSend.objects.get(user_id=p.user_id)
    assert row.email_id == "inactivity_1"
    assert row.dry_run is True


@pytest.mark.django_db
def test_ghost_day14_warn_sets_warned_at_live(monkeypatch):
    _go_live(monkeypatch)
    p = _profile(14)
    assert beta_lifecycle.process_profile(p, now=NOW) == lifecycle.SENT
    p.refresh_from_db()
    assert p.reclaim_warned_at is not None
    assert EmailSend.objects.filter(
        user_id=p.user_id, email_id="inactivity_3", dry_run=False
    ).exists()
    assert p.beta_status == BetaStatus.ACTIVE  # not reclaimed yet


@pytest.mark.django_db
def test_ghost_reclaim_waits_for_grace_then_reclaims(monkeypatch):
    _go_live(monkeypatch)
    # Past day 21, warned only 6 days ago (< grace 7) -> wait.
    p = _profile(21, reclaim_warned_at=NOW - dt.timedelta(days=6))
    assert beta_lifecycle.process_profile(p, now=NOW) == "awaiting_grace"
    p.refresh_from_db()
    assert p.beta_status == BetaStatus.ACTIVE
    assert p.is_billing_exempt is True

    # Warned 8 days ago -> reclaim fires.
    p.reclaim_warned_at = NOW - dt.timedelta(days=8)
    p.save()
    assert beta_lifecycle.process_profile(p, now=NOW) == "reclaimed"
    p.refresh_from_db()
    assert p.beta_status == BetaStatus.RECLAIMED
    assert p.is_billing_exempt is False
    assert p.billing_exempt_reason == ""
    assert AdminAuditLog.objects.filter(action="beta.reclaimed").exists()


@pytest.mark.django_db
def test_cold_start_past_21_warns_first_not_reclaim(monkeypatch):
    _go_live(monkeypatch)
    p = _profile(25)  # never warned
    assert beta_lifecycle.process_profile(p, now=NOW) == lifecycle.SENT
    p.refresh_from_db()
    assert p.reclaim_warned_at is not None  # warn was sent, not a blind reclaim
    assert p.beta_status == BetaStatus.ACTIVE
    assert EmailSend.objects.filter(user_id=p.user_id, email_id="inactivity_3").exists()
    assert not EmailSend.objects.filter(user_id=p.user_id, email_id="inactivity_4").exists()


# --- dry_run safety + episode reset ------------------------------------------

@pytest.mark.django_db
def test_dry_run_applies_no_side_effects():
    # Default config dry_run=True. Past-21 ghost, warned long ago.
    p = _profile(21, reclaim_warned_at=NOW - dt.timedelta(days=8))
    result = beta_lifecycle.process_profile(p, now=NOW)
    assert result == lifecycle.DRY_RUN
    p.refresh_from_db()
    # No reclaim happened; exemption + status untouched.
    assert p.beta_status == BetaStatus.ACTIVE
    assert p.is_billing_exempt is True
    assert EmailSend.objects.filter(
        user_id=p.user_id, email_id="inactivity_4", dry_run=True
    ).exists()


@pytest.mark.django_db
def test_lifecycle_start_floor_caps_inactivity():
    # Gradual launch: a ghost enrolled 25 days ago would normally cold-start at
    # the reclaim threshold. With the floor at "today", days_inactive = 0.
    app_config.set("lifecycle_start_at", NOW.date().isoformat())
    p = _profile(25)
    assert beta_lifecycle.process_profile(p, now=NOW) == "active_no_action"
    p.refresh_from_db()
    assert p.beta_status == BetaStatus.ACTIVE  # nothing reclaimed/warned


@pytest.mark.django_db
def test_active_user_clears_stale_warn(monkeypatch):
    _go_live(monkeypatch)
    # Enrolled 1 day ago (days_inactive=1 < first threshold) but has a stale warn.
    p = _profile(1, reclaim_warned_at=NOW - dt.timedelta(days=2))
    assert beta_lifecycle.process_profile(p, now=NOW) == "active_no_action"
    p.refresh_from_db()
    assert p.reclaim_warned_at is None

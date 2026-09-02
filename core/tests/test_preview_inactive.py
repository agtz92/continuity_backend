"""Tests for the `preview_inactive_followup` command — a read-only preview of
the inactivity follow-up audience. It must never send or write, must respect
the --days threshold, and must classify beta vs non-beta correctly."""

from __future__ import annotations

import datetime as dt
import uuid
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.admin_api import supabase_admin
from core.assistant.models import AccountProfile, BetaStatus
from core.models import Activity
from core.notifications.models import EmailSend

NOW = timezone.now()


def _profile(*, beta: bool, enrolled_days_ago: int = 30) -> AccountProfile:
    return AccountProfile.objects.create(
        user_id=uuid.uuid4(),
        beta_cohort=beta,
        beta_status=BetaStatus.ACTIVE,
        beta_enrolled_at=NOW - dt.timedelta(days=enrolled_days_ago),
    )


def _activity(user_id, kind, days_ago):
    a = Activity.objects.create(user_id=user_id, kind=kind)
    Activity.objects.filter(id=a.id).update(created=NOW - dt.timedelta(days=days_ago))


@pytest.fixture(autouse=True)
def _no_supabase(monkeypatch):
    """Force the local fallback path (no Supabase admin key in tests)."""
    def _raise():
        raise supabase_admin.SupabaseAdminError("no key in tests")

    monkeypatch.setattr(supabase_admin, "fetch_all_users", _raise)


def _run(**opts) -> str:
    out = StringIO()
    call_command("preview_inactive_followup", stdout=out, **opts)
    return out.getvalue()


@pytest.mark.django_db
def test_ghost_beta_inactive_15d_shows_day14_email():
    _profile(beta=True, enrolled_days_ago=15)  # ghost: no activity → clock from enrol
    out = _run(days=15)
    assert "1 users (1 beta, 0 no-beta)" in out
    # day-14 step for the ghost tier is inactivity_3.
    assert "inactivity_3" in out


@pytest.mark.django_db
def test_below_threshold_is_excluded():
    _profile(beta=True, enrolled_days_ago=5)
    out = _run(days=15)
    assert "0 users (0 beta, 0 no-beta)" in out


@pytest.mark.django_db
def test_non_beta_user_shows_no_template():
    p = _profile(beta=False, enrolled_days_ago=40)
    _activity(p.user_id, "task_created", days_ago=20)
    out = _run(days=15)
    assert "1 users (0 beta, 1 no-beta)" in out
    assert "(sin plantilla)" in out


@pytest.mark.django_db
def test_preview_sends_nothing_and_writes_nothing():
    _profile(beta=True, enrolled_days_ago=25)
    _run(days=15)
    # Read-only: no EmailSend rows (not even dry_run preview rows) are created.
    assert EmailSend.objects.count() == 0


@pytest.mark.django_db
def test_threshold_argument_is_respected():
    _profile(beta=True, enrolled_days_ago=10)
    assert "0 users" in _run(days=15)
    assert "1 users" in _run(days=7)

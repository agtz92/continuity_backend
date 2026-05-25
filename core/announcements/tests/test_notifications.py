"""Tests for the in-app notification service.

Covers both sources of notifications:

1. **Derived (quota-based)** — `quota_over` when the user is already
   over a cap, and `quota_will_exceed` when they're scheduled to
   downgrade and will end up over the cap of the future plan.
2. **Admin announcements** — published vs draft, audience filters
   (plan / user_ids), time-window filters.

Also asserts that billing-exempt accounts are never nagged with quota
warnings (since their plan is effectively comp'd).
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.utils import timezone

from core.announcements.models import Announcement, Severity, Status
from core.announcements.services import compute_user_notifications
from core.assistant.models import AccountProfile
from core.models import Idea, Project


# ---------- Fixtures ----------


@pytest.fixture
def free_user(db):
    uid = uuid.uuid4()
    AccountProfile.objects.create(user_id=uid, plan="free")
    return uid


@pytest.fixture
def pro_user(db):
    uid = uuid.uuid4()
    AccountProfile.objects.create(user_id=uid, plan="pro")
    return uid


@pytest.fixture
def exempt_user(db):
    uid = uuid.uuid4()
    AccountProfile.objects.create(user_id=uid, plan="free", is_billing_exempt=True)
    return uid


@pytest.fixture
def pro_scheduled_to_free(db):
    uid = uuid.uuid4()
    AccountProfile.objects.create(
        user_id=uid,
        plan="pro",
        cancel_at_period_end=True,
        plan_renews_at=timezone.now() + dt.timedelta(days=20),
    )
    return uid


def _make_projects(uid, n):
    for i in range(n):
        Project.objects.create(
            user_id=uid, name=f"P{i}", status="active", priority="medium"
        )


# ---------- Derived: quota_over ----------


class TestQuotaOver:
    @pytest.mark.django_db
    def test_no_overage_no_warnings(self, free_user):
        _make_projects(free_user, 2)
        items = compute_user_notifications(free_user)
        assert items == []

    @pytest.mark.django_db
    def test_overage_in_projects_emits_quota_over(self, free_user):
        _make_projects(free_user, 5)  # cap=3
        items = compute_user_notifications(free_user)
        quota_items = [i for i in items if i.kind == "quota_over"]
        assert len(quota_items) == 1
        n = quota_items[0]
        assert n.i18n_kind == "projects"
        assert n.i18n_vars["current"] == 5
        assert n.i18n_vars["cap"] == 3
        assert n.i18n_vars["over_by"] == 2
        assert n.dismissible is False  # must persist until resolved

    @pytest.mark.django_db
    def test_overage_in_ideas_also_emits(self, free_user):
        for i in range(35):  # cap=30
            Idea.objects.create(user_id=free_user, title=f"I{i}")
        items = compute_user_notifications(free_user)
        kinds = [n.i18n_kind for n in items if n.kind == "quota_over"]
        assert "ideas" in kinds


# ---------- Derived: quota_will_exceed ----------


class TestQuotaWillExceed:
    @pytest.mark.django_db
    def test_only_emits_when_cancellation_scheduled(self, pro_user):
        _make_projects(pro_user, 4)
        # Pro cap=25, free cap=3 → would exceed on free but NOT scheduled
        items = compute_user_notifications(pro_user)
        forecasts = [i for i in items if i.kind == "quota_will_exceed"]
        assert forecasts == []

    @pytest.mark.django_db
    def test_emits_when_pro_scheduled_to_downgrade(self, pro_scheduled_to_free):
        _make_projects(pro_scheduled_to_free, 4)
        items = compute_user_notifications(pro_scheduled_to_free)
        forecasts = [i for i in items if i.kind == "quota_will_exceed"]
        assert len(forecasts) == 1
        n = forecasts[0]
        assert n.i18n_kind == "projects"
        assert n.i18n_vars["future_plan"] == "free"
        assert n.i18n_vars["over_by"] == 1
        assert n.dismissible is True  # advisory, user can hide

    @pytest.mark.django_db
    def test_does_not_duplicate_when_already_quota_over(
        self, free_user, db
    ):
        # User is on free + cancel_scheduled + over the projects cap.
        # We should emit only `quota_over` (current), not also
        # `quota_will_exceed` (future) for the same kind.
        AccountProfile.objects.filter(user_id=free_user).update(
            cancel_at_period_end=True,
            plan_renews_at=timezone.now() + dt.timedelta(days=10),
        )
        _make_projects(free_user, 5)
        items = compute_user_notifications(free_user)
        kinds_for_projects = [
            i.kind for i in items if i.i18n_kind == "projects"
        ]
        assert kinds_for_projects == ["quota_over"]


# ---------- Exempt accounts ----------


class TestExempt:
    @pytest.mark.django_db
    def test_exempt_user_gets_no_quota_warnings(self, exempt_user):
        _make_projects(exempt_user, 50)  # way over any cap
        items = compute_user_notifications(exempt_user)
        derived = [
            i for i in items if i.kind in {"quota_over", "quota_will_exceed"}
        ]
        assert derived == []  # exempt = no nagging


# ---------- Announcements ----------


def _ann(
    *,
    title="A",
    body="",
    severity="info",
    status="published",
    plans=None,
    user_ids=None,
    starts_at=None,
    ends_at=None,
    dismissible=True,
):
    return Announcement.objects.create(
        title=title,
        body=body,
        severity=severity,
        status=status,
        audience_plans=plans or [],
        audience_user_ids=user_ids or [],
        starts_at=starts_at,
        ends_at=ends_at,
        dismissible=dismissible,
    )


class TestAnnouncements:
    @pytest.mark.django_db
    def test_published_announcement_visible_to_all(self, free_user):
        _ann(title="Hello world")
        items = compute_user_notifications(free_user)
        titles = [i.title for i in items if i.kind == "announcement"]
        assert titles == ["Hello world"]

    @pytest.mark.django_db
    def test_draft_announcement_hidden(self, free_user):
        _ann(title="Draft", status="draft")
        items = compute_user_notifications(free_user)
        assert [i for i in items if i.kind == "announcement"] == []

    @pytest.mark.django_db
    def test_archived_announcement_hidden(self, free_user):
        _ann(title="Old", status="archived")
        items = compute_user_notifications(free_user)
        assert [i for i in items if i.kind == "announcement"] == []

    @pytest.mark.django_db
    def test_audience_plan_filter_includes_match(self, free_user):
        _ann(title="Free-only", plans=["free"])
        items = compute_user_notifications(free_user)
        assert any(i.title == "Free-only" for i in items)

    @pytest.mark.django_db
    def test_audience_plan_filter_excludes_others(self, pro_user):
        _ann(title="Free-only", plans=["free"])
        items = compute_user_notifications(pro_user)
        assert not any(i.title == "Free-only" for i in items)

    @pytest.mark.django_db
    def test_audience_user_id_filter_includes(self, free_user):
        _ann(title="Just for you", user_ids=[str(free_user)])
        items = compute_user_notifications(free_user)
        assert any(i.title == "Just for you" for i in items)

    @pytest.mark.django_db
    def test_audience_user_id_filter_excludes_others(self, free_user, pro_user):
        _ann(title="For Pro", user_ids=[str(pro_user)])
        items = compute_user_notifications(free_user)
        assert not any(i.title == "For Pro" for i in items)

    @pytest.mark.django_db
    def test_starts_at_in_future_not_visible(self, free_user):
        _ann(title="Future", starts_at=timezone.now() + dt.timedelta(hours=1))
        items = compute_user_notifications(free_user)
        assert not any(i.title == "Future" for i in items)

    @pytest.mark.django_db
    def test_ends_at_in_past_not_visible(self, free_user):
        _ann(title="Past", ends_at=timezone.now() - dt.timedelta(hours=1))
        items = compute_user_notifications(free_user)
        assert not any(i.title == "Past" for i in items)

    @pytest.mark.django_db
    def test_dismissible_flag_propagated(self, free_user):
        _ann(title="Pinned", dismissible=False)
        items = compute_user_notifications(free_user)
        n = next(i for i in items if i.title == "Pinned")
        assert n.dismissible is False

    @pytest.mark.django_db
    def test_severity_propagated(self, free_user):
        _ann(title="Outage", severity="error")
        items = compute_user_notifications(free_user)
        n = next(i for i in items if i.title == "Outage")
        assert n.severity == "error"


# ---------- Ordering ----------


class TestOrdering:
    @pytest.mark.django_db
    def test_error_before_warn_before_info(self, free_user):
        _ann(title="Outage", severity="error")
        _make_projects(free_user, 5)  # quota_over warn
        _ann(title="News", severity="info")
        items = compute_user_notifications(free_user)
        severities = [i.severity for i in items]
        # Each severity bucket appears before the next.
        first_warn = severities.index("warn") if "warn" in severities else None
        first_info = severities.index("info") if "info" in severities else None
        assert severities.index("error") < (first_warn or 999)
        if first_warn is not None and first_info is not None:
            assert first_warn < first_info

    @pytest.mark.django_db
    def test_quota_over_before_quota_will_exceed_within_same_severity(
        self, free_user, db
    ):
        # Both quota_over (current) and quota_will_exceed (future) are warn.
        # Current overages should render first.
        AccountProfile.objects.filter(user_id=free_user).update(
            cancel_at_period_end=True,
            plan_renews_at=timezone.now() + dt.timedelta(days=10),
        )
        _make_projects(free_user, 5)  # quota_over for projects
        for i in range(35):
            Idea.objects.create(user_id=free_user, title=f"I{i}")
        items = compute_user_notifications(free_user)
        kinds = [i.kind for i in items if i.kind.startswith("quota_")]
        # quota_over comes before quota_will_exceed (same severity, different kind priority)
        assert kinds[0] == "quota_over"

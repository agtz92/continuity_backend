"""Tests for the system admin endpoints (jobs, stats)."""

import datetime as dt
import uuid

import pytest
from django.utils import timezone

from core.admin_api.models import AdminAuditLog
from core.assistant.models import AccountProfile
from core.models import Activity, Project
from core.notifications.models import (
    Notification,
    NotificationKind,
    NotificationStatus,
)


JOBS_QUERY = """
    query($status: String) {
        adminNotificationJobs(status: $status) {
            jobs { id status kind channel }
            page hasNext
        }
    }
"""

STATS_QUERY = """
    query {
        adminSystemStats {
            totalAccounts
            admins
            dau wau mau
            blogPostsPublished
            blogPostsDraft
            pagesPublished
            pendingJobs
            failedJobs
            planCounts { plan count }
            jobStatusCounts { status count }
        }
    }
"""

RETRY = """
    mutation($id: ID!) {
        adminNotificationJobRetry(id: $id) { id status error }
    }
"""


@pytest.mark.django_db
def test_jobs_requires_admin(execute_query, user_a):
    AccountProfile.objects.create(user_id=user_a, is_admin=False)
    result = execute_query(JOBS_QUERY, user_id=user_a, variable_values={"status": None})
    assert result.errors is not None


@pytest.mark.django_db
def test_jobs_listing_and_filter(execute_query, user_a, user_b):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    Notification.objects.create(
        user_id=user_b,
        channel="telegram",
        kind=NotificationKind.WEEKLY_DIGEST,
        dedupe_key="x",
        body="hi",
        status=NotificationStatus.PENDING,
    )
    Notification.objects.create(
        user_id=user_b,
        channel="telegram",
        kind=NotificationKind.MANUAL,
        dedupe_key="y",
        body="failed",
        status=NotificationStatus.FAILED,
        error="boom",
    )

    full = execute_query(JOBS_QUERY, user_id=user_a, variable_values={"status": None})
    assert full.errors is None, full.errors
    assert len(full.data["adminNotificationJobs"]["jobs"]) == 2

    filtered = execute_query(
        JOBS_QUERY, user_id=user_a, variable_values={"status": "failed"}
    )
    assert filtered.errors is None
    items = filtered.data["adminNotificationJobs"]["jobs"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"


@pytest.mark.django_db
def test_retry_resets_status_and_clears_error(execute_query, user_a, user_b):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    job = Notification.objects.create(
        user_id=user_b,
        channel="telegram",
        kind=NotificationKind.MANUAL,
        dedupe_key="z",
        body="x",
        status=NotificationStatus.FAILED,
        error="boom",
        attempts=2,
    )
    res = execute_query(
        RETRY, user_id=user_a, variable_values={"id": str(job.id)}
    )
    assert res.errors is None, res.errors
    assert res.data["adminNotificationJobRetry"]["status"] == "pending"
    job.refresh_from_db()
    assert job.status == NotificationStatus.PENDING
    assert job.error == ""
    log = AdminAuditLog.objects.filter(
        actor_user_id=user_a, action="notification.retry"
    ).first()
    assert log is not None


@pytest.mark.django_db
def test_retry_rejects_already_sent(execute_query, user_a, user_b):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    job = Notification.objects.create(
        user_id=user_b,
        channel="telegram",
        kind=NotificationKind.MANUAL,
        dedupe_key="zz",
        body="x",
        status=NotificationStatus.SENT,
    )
    res = execute_query(
        RETRY, user_id=user_a, variable_values={"id": str(job.id)}
    )
    assert res.errors is not None
    assert "BAD_INPUT" in str(res.errors[0].extensions)


@pytest.mark.django_db
def test_system_stats_aggregates(execute_query, user_a, user_b):
    AccountProfile.objects.create(user_id=user_a, is_admin=True, plan="admin")
    AccountProfile.objects.create(user_id=user_b, is_admin=False, plan="pro")
    AccountProfile.objects.create(user_id=uuid.uuid4(), is_admin=False, plan="free")

    # An activity from "today"
    project = Project.objects.create(user_id=user_b, name="P")
    Activity.objects.create(
        user_id=user_b,
        kind="note",
        entity_id=project.id,
        entity_title=project.name,
        project_id=project.id,
        note="hi",
    )

    Notification.objects.create(
        user_id=user_b,
        channel="telegram",
        kind=NotificationKind.WEEKLY_DIGEST,
        dedupe_key="dk",
        body="x",
        status=NotificationStatus.PENDING,
    )

    result = execute_query(STATS_QUERY, user_id=user_a)
    assert result.errors is None, result.errors
    stats = result.data["adminSystemStats"]
    assert stats["totalAccounts"] == 3
    assert stats["admins"] == 1
    assert stats["dau"] == 1
    assert stats["pendingJobs"] == 1
    plans = {row["plan"]: row["count"] for row in stats["planCounts"]}
    assert plans == {"admin": 1, "pro": 1, "free": 1}

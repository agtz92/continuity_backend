"""Permission gating on every admin GraphQL field.

These tests don't hit Supabase — they only verify the
authorization check fires before any side effect happens. Supabase
calls are mocked where needed.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from core.admin_api.models import AdminAuditLog
from core.admin_api.supabase_admin import SupabaseUser, SupabaseUserPage
from core.assistant.models import AccountProfile, Plan


ME_QUERY = "query { me { userId isAdmin } }"
ADMIN_USERS_QUERY = """
    query { adminUsers { users { userId email plan isAdmin } page hasNext } }
"""
SET_PLAN_MUTATION = """
    mutation($uid: ID!, $plan: String!) {
        adminSetUserPlan(userId: $uid, plan: $plan) {
            userId plan isAdmin
        }
    }
"""
SET_ADMIN_MUTATION = """
    mutation($uid: ID!, $val: Boolean!) {
        adminSetUserIsAdmin(userId: $uid, isAdmin: $val) {
            userId isAdmin
        }
    }
"""


@pytest.mark.django_db
def test_me_unauthenticated(execute_query):
    result = execute_query(ME_QUERY, user_id=None)
    assert result.errors is not None
    assert "UNAUTHENTICATED" in str(result.errors[0].extensions)


@pytest.mark.django_db
def test_me_without_profile_returns_not_admin(execute_query, user_a):
    result = execute_query(ME_QUERY, user_id=user_a)
    assert result.errors is None
    assert result.data["me"]["isAdmin"] is False


@pytest.mark.django_db
def test_me_with_admin_profile_returns_true(execute_query, user_a):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    result = execute_query(ME_QUERY, user_id=user_a)
    assert result.errors is None
    assert result.data["me"]["isAdmin"] is True


@pytest.mark.django_db
def test_admin_users_rejects_non_admin(execute_query, user_a):
    AccountProfile.objects.create(user_id=user_a, is_admin=False)
    result = execute_query(ADMIN_USERS_QUERY, user_id=user_a)
    assert result.errors is not None
    assert "FORBIDDEN" in str(result.errors[0].extensions)


@pytest.mark.django_db
def test_admin_users_rejects_unauthenticated(execute_query):
    result = execute_query(ADMIN_USERS_QUERY, user_id=None)
    assert result.errors is not None


@pytest.mark.django_db
def test_set_plan_rejects_non_admin(execute_query, user_a, user_b):
    AccountProfile.objects.create(user_id=user_a, is_admin=False)
    result = execute_query(
        SET_PLAN_MUTATION,
        user_id=user_a,
        variable_values={"uid": str(user_b), "plan": "pro"},
    )
    assert result.errors is not None
    assert "FORBIDDEN" in str(result.errors[0].extensions)
    # No write happened
    assert not AccountProfile.objects.filter(user_id=user_b).exists()


@pytest.mark.django_db
def test_set_plan_happy_path_writes_audit_log(execute_query, user_a, user_b):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    fake_user = SupabaseUser(
        id=user_b,
        email="target@example.com",
        created_at=None,
        last_sign_in_at=None,
        email_confirmed_at=None,
    )
    with patch(
        "core.admin_api.schema.supabase_get_user", return_value=fake_user
    ):
        result = execute_query(
            SET_PLAN_MUTATION,
            user_id=user_a,
            variable_values={"uid": str(user_b), "plan": "pro"},
        )
    assert result.errors is None, result.errors
    assert result.data["adminSetUserPlan"]["plan"] == "pro"
    target = AccountProfile.objects.get(user_id=user_b)
    assert target.plan == Plan.PRO.value

    # Audit log should have one entry
    log = AdminAuditLog.objects.filter(
        actor_user_id=user_a, action="user.set_plan"
    ).first()
    assert log is not None
    assert log.target_id == str(user_b)
    assert log.payload["after"] == "pro"


@pytest.mark.django_db
def test_set_plan_rejects_invalid_plan(execute_query, user_a, user_b):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    result = execute_query(
        SET_PLAN_MUTATION,
        user_id=user_a,
        variable_values={"uid": str(user_b), "plan": "wizard"},
    )
    assert result.errors is not None
    assert "BAD_INPUT" in str(result.errors[0].extensions)


@pytest.mark.django_db
def test_set_is_admin_refuses_self_demotion(execute_query, user_a):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    result = execute_query(
        SET_ADMIN_MUTATION,
        user_id=user_a,
        variable_values={"uid": str(user_a), "val": False},
    )
    assert result.errors is not None
    assert "BAD_INPUT" in str(result.errors[0].extensions)
    # Profile unchanged
    profile = AccountProfile.objects.get(user_id=user_a)
    assert profile.is_admin is True


@pytest.mark.django_db
def test_admin_users_calls_supabase_when_admin(execute_query, user_a, user_b):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    page = SupabaseUserPage(
        users=[
            SupabaseUser(
                id=user_b,
                email="someone@example.com",
                created_at=None,
                last_sign_in_at=None,
                email_confirmed_at=None,
            )
        ],
        total=1,
        page=1,
        per_page=25,
    )
    with patch(
        "core.admin_api.schema.supabase_list_users", return_value=page
    ):
        result = execute_query(ADMIN_USERS_QUERY, user_id=user_a)
    assert result.errors is None, result.errors
    users = result.data["adminUsers"]["users"]
    assert len(users) == 1
    assert users[0]["email"] == "someone@example.com"

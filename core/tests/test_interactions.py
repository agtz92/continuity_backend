"""Tests for per-user, per-source interaction metrics.

Covers four layers:

* **Service** — `record_interaction`, source classification, aggregation,
  the 30-day window, and the bulk helper.
* **Extension** — `InteractionTrackingExtension` counts successful mutations
  only, tagged by channel; ignores queries and failed mutations.
* **Integration** — a real mutation through the wired schema records one
  interaction; a real query records none.
* **Privacy** — the model stores only counts (no content-bearing fields).
* **Admin** — the new fields surface through `adminUser`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import RequestFactory
from django.utils import timezone

from core.interaction_tracking import InteractionTrackingExtension
from core.models import InteractionDay, InteractionSource
from core.schema import schema
from core.services import interactions as I

try:
    from graphql import OperationType
except Exception:  # pragma: no cover
    OperationType = None


RF = RequestFactory()


def _req(path: str = "/graphql/", client: str | None = None, user_id=None):
    extra = {}
    if client is not None:
        extra["HTTP_X_CONTINUITY_CLIENT"] = client
    req = RF.post(path, **extra)
    if user_id is not None:
        req.user_id = user_id
    return req


# --------------------------------------------------------------------------
# Service — source classification
# --------------------------------------------------------------------------


def test_source_web_from_header():
    assert I.source_from_request(_req(client="web")) == I.WEB


def test_source_mobile_from_header():
    assert I.source_from_request(_req(client="MOBILE")) == I.MOBILE  # case-insensitive


def test_source_connector_from_path_ignores_header():
    # The connector is identified by its endpoint, not a client-controlled header.
    assert I.source_from_request(_req(path="/mcp/", client="web")) == I.CONNECTOR


def test_source_unknown_when_no_header():
    assert I.source_from_request(_req()) == I.UNKNOWN


def test_source_unknown_for_garbage_header():
    assert I.source_from_request(_req(client="hacker")) == I.UNKNOWN


# --------------------------------------------------------------------------
# Service — recording + aggregation
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_increments():
    uid = uuid.uuid4()
    I.record_interaction(uid, I.WEB)
    I.record_interaction(uid, I.WEB)
    I.record_interaction(uid, I.CONNECTOR)
    by_source = I.interactions_by_source(uid)
    assert by_source == {I.WEB: 2, I.CONNECTOR: 1}
    assert I.interactions_total(uid) == 3


@pytest.mark.django_db
def test_record_invalid_source_bucketed_unknown():
    uid = uuid.uuid4()
    I.record_interaction(uid, "not-a-channel")
    assert I.interactions_by_source(uid) == {I.UNKNOWN: 1}


@pytest.mark.django_db
def test_record_noops_on_missing_user_or_zero_count():
    I.record_interaction(None, I.WEB)
    uid = uuid.uuid4()
    I.record_interaction(uid, I.WEB, count=0)
    assert InteractionDay.objects.count() == 0


@pytest.mark.django_db
def test_record_from_request_uses_path_and_user():
    uid = uuid.uuid4()
    I.record_from_request(_req(path="/mcp/", user_id=uid))
    assert I.interactions_by_source(uid) == {I.CONNECTOR: 1}


@pytest.mark.django_db
def test_thirty_day_window_excludes_old_rows():
    uid = uuid.uuid4()
    old = timezone.now().date() - dt.timedelta(days=40)
    InteractionDay.objects.create(user_id=uid, date=old, source=I.WEB, count=5)
    I.record_interaction(uid, I.WEB)  # today
    assert I.interactions_by_source(uid, days=30) == {I.WEB: 1}
    assert I.interactions_by_source(uid, days=60) == {I.WEB: 6}


@pytest.mark.django_db
def test_bulk_interactions_total():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    I.record_interaction(a, I.WEB)
    I.record_interaction(a, I.MOBILE)
    I.record_interaction(b, I.CONNECTOR)
    out = I.bulk_interactions_total([a, b, c])
    assert out.get(a) == 2
    assert out.get(b) == 1
    assert c not in out  # no rows → absent


@pytest.mark.django_db
def test_record_is_user_scoped():
    a, b = uuid.uuid4(), uuid.uuid4()
    I.record_interaction(a, I.WEB)
    assert I.interactions_total(a) == 1
    assert I.interactions_total(b) == 0


# --------------------------------------------------------------------------
# Extension — counts only successful mutations
# --------------------------------------------------------------------------


def _run_extension(ec):
    """Drive the extension's on_operation generator past its yield."""
    ext = InteractionTrackingExtension.__new__(InteractionTrackingExtension)
    ext.execution_context = ec
    gen = ext.on_operation()
    next(gen)
    try:
        next(gen)
    except StopIteration:
        pass


def _ec(op_type, *, errors=None, user_id=None, request=None):
    return SimpleNamespace(
        operation_type=op_type,
        result=SimpleNamespace(errors=errors),
        context=SimpleNamespace(user_id=user_id, request=request),
    )


@pytest.mark.django_db
def test_extension_counts_mutation_tagged_by_source():
    uid = uuid.uuid4()
    _run_extension(
        _ec(OperationType.MUTATION, user_id=uid, request=_req(client="web"))
    )
    assert I.interactions_by_source(uid) == {I.WEB: 1}


@pytest.mark.django_db
def test_extension_ignores_query():
    uid = uuid.uuid4()
    _run_extension(
        _ec(OperationType.QUERY, user_id=uid, request=_req(client="web"))
    )
    assert I.interactions_total(uid) == 0


@pytest.mark.django_db
def test_extension_ignores_failed_mutation():
    uid = uuid.uuid4()
    _run_extension(
        _ec(
            OperationType.MUTATION,
            errors=["boom"],
            user_id=uid,
            request=_req(client="web"),
        )
    )
    assert I.interactions_total(uid) == 0


@pytest.mark.django_db
def test_extension_noops_without_user():
    _run_extension(_ec(OperationType.MUTATION, request=_req(client="web")))
    assert InteractionDay.objects.count() == 0


# --------------------------------------------------------------------------
# Integration — real schema, real mutation
# --------------------------------------------------------------------------


CREATE_IDEA = "mutation($d: IdeaInput!){ createIdea(data: $d){ id } }"


@pytest.mark.django_db
def test_real_mutation_records_one_interaction():
    uid = uuid.uuid4()
    ctx = SimpleNamespace(user_id=uid, request=_req(client="web"))
    res = schema.execute_sync(
        CREATE_IDEA, context_value=ctx, variable_values={"d": {"title": "ship"}}
    )
    assert res.errors is None, res.errors
    assert I.interactions_by_source(uid) == {I.WEB: 1}


@pytest.mark.django_db
def test_real_query_records_nothing():
    uid = uuid.uuid4()
    ctx = SimpleNamespace(user_id=uid, request=_req(client="web"))
    res = schema.execute_sync("query{ __typename }", context_value=ctx)
    assert res.errors is None
    assert I.interactions_total(uid) == 0


# --------------------------------------------------------------------------
# Privacy — counts only, no content
# --------------------------------------------------------------------------


def test_model_stores_only_counts_no_content():
    field_names = {f.name for f in InteractionDay._meta.get_fields()}
    assert field_names == {"id", "user_id", "date", "source", "count", "updated_at"}
    for forbidden in (
        "content", "body", "text", "payload", "ip", "query", "message", "user_agent",
    ):
        assert forbidden not in field_names


# --------------------------------------------------------------------------
# Admin — fields surface through adminUser
# --------------------------------------------------------------------------


ADMIN_USER_Q = """
query($uid: ID!){
  adminUser(userId: $uid){
    interactions30dTotal
    interactionsBySource { label count }
  }
}
"""


@pytest.mark.django_db
def test_admin_user_detail_exposes_interactions():
    from core.admin_api.supabase_admin import SupabaseUser
    from core.assistant.models import AccountProfile

    admin_id = uuid.uuid4()
    target = uuid.uuid4()
    AccountProfile.objects.create(user_id=admin_id, is_admin=True)
    I.record_interaction(target, I.WEB)
    I.record_interaction(target, I.WEB)
    I.record_interaction(target, I.CONNECTOR)

    fake_user = SupabaseUser(
        id=target,
        email="t@example.com",
        created_at=None,
        last_sign_in_at=None,
        email_confirmed_at=None,
    )
    ctx = SimpleNamespace(user_id=admin_id, request=_req())
    with patch("core.admin_api.schema.supabase_get_user", return_value=fake_user):
        res = schema.execute_sync(
            ADMIN_USER_Q, context_value=ctx, variable_values={"uid": str(target)}
        )
    assert res.errors is None, res.errors
    detail = res.data["adminUser"]
    assert detail["interactions30dTotal"] == 3
    by_source = {row["label"]: row["count"] for row in detail["interactionsBySource"]}
    assert by_source["web"] == 2
    assert by_source["connector"] == 1
    assert by_source["mobile"] == 0


ADMIN_USERS_Q = """
query {
  adminUsers {
    users { userId interactions30d }
  }
}
"""


@pytest.mark.django_db
def test_admin_users_summary_exposes_interactions(execute_query):
    from core.admin_api.supabase_admin import SupabaseUser, SupabaseUserPage
    from core.assistant.models import AccountProfile

    admin_id = uuid.uuid4()
    target = uuid.uuid4()
    AccountProfile.objects.create(user_id=admin_id, is_admin=True)
    I.record_interaction(target, I.WEB)
    I.record_interaction(target, I.WEB)
    I.record_interaction(target, I.CONNECTOR)

    page = SupabaseUserPage(
        users=[
            SupabaseUser(
                id=target,
                email="x@example.com",
                created_at=None,
                last_sign_in_at=None,
                email_confirmed_at=None,
            )
        ],
        total=1,
        page=1,
        per_page=25,
    )
    with patch("core.admin_api.schema.supabase_list_users", return_value=page):
        res = execute_query(ADMIN_USERS_Q, user_id=admin_id)
    assert res.errors is None, res.errors
    users = res.data["adminUsers"]["users"]
    assert users[0]["interactions30d"] == 3

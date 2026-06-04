"""Tests for the Today layout preferences.

Covers the GraphQL surface (todayLayout query, updateTodayLayout and
resetTodayLayout mutations) plus the underlying service rules:

* lazy-create on first read
* canonical default order
* hide/order persistence and isolation between users
* validation of unknown ids and locked sections
* graceful handling of sections added to code after a user has saved
"""

import uuid

import pytest
from django.core.exceptions import ValidationError

from core.services import preferences as preferences_svc
from core.services.preferences import (
    NON_HIDEABLE_TODAY_IDS,
    TODAY_SECTION_IDS,
)


TODAY_LAYOUT_QUERY = """
    query { todayLayout { order hidden } }
"""

UPDATE_MUTATION = """
    mutation U($order: [String!], $hidden: [String!]) {
        updateTodayLayout(order: $order, hidden: $hidden) {
            order
            hidden
        }
    }
"""

RESET_MUTATION = """
    mutation { resetTodayLayout { order hidden } }
"""


# ---------------------------- service layer ---------------------------- #


@pytest.mark.django_db
def test_get_layout_lazy_creates_with_defaults(user_a):
    layout = preferences_svc.get_today_layout(user_a)
    assert layout["order"] == list(TODAY_SECTION_IDS)
    assert layout["hidden"] == []


@pytest.mark.django_db
def test_update_persists_order_and_hidden(user_a):
    new_order = list(reversed(TODAY_SECTION_IDS))
    preferences_svc.update_today_layout(
        user_a, order=new_order, hidden=["done-today", "sleeping"]
    )

    layout = preferences_svc.get_today_layout(user_a)
    assert layout["order"] == new_order
    assert layout["hidden"] == ["done-today", "sleeping"]


@pytest.mark.django_db
def test_unknown_section_id_raises(user_a):
    with pytest.raises(ValidationError):
        preferences_svc.update_today_layout(user_a, hidden=["not-a-section"])
    with pytest.raises(ValidationError):
        preferences_svc.update_today_layout(user_a, order=["bogus"])


@pytest.mark.django_db
def test_non_hideable_section_cannot_be_hidden(user_a):
    locked = next(iter(NON_HIDEABLE_TODAY_IDS))
    with pytest.raises(ValidationError):
        preferences_svc.update_today_layout(user_a, hidden=[locked])


@pytest.mark.django_db
def test_partial_update_does_not_clobber_other_field(user_a):
    preferences_svc.update_today_layout(user_a, hidden=["done-today"])
    preferences_svc.update_today_layout(
        user_a, order=list(reversed(TODAY_SECTION_IDS))
    )

    layout = preferences_svc.get_today_layout(user_a)
    assert layout["hidden"] == ["done-today"]
    assert layout["order"] == list(reversed(TODAY_SECTION_IDS))


@pytest.mark.django_db
def test_reset_wipes_layout(user_a):
    preferences_svc.update_today_layout(
        user_a,
        order=list(reversed(TODAY_SECTION_IDS)),
        hidden=["done-today"],
    )

    layout = preferences_svc.reset_today_layout(user_a)
    assert layout["order"] == list(TODAY_SECTION_IDS)
    assert layout["hidden"] == []


@pytest.mark.django_db
def test_missing_sections_appended_when_canonical_list_grows(user_a):
    # Simulate a user who saved before "launched-with-tasks" existed.
    partial = [s for s in TODAY_SECTION_IDS if s != "launched-with-tasks"]
    preferences_svc.update_today_layout(user_a, order=partial)

    layout = preferences_svc.get_today_layout(user_a)
    # The missing canonical id is appended at the end so it's visibly new.
    assert layout["order"][-1] == "launched-with-tasks"
    assert set(layout["order"]) == set(TODAY_SECTION_IDS)


@pytest.mark.django_db
def test_dedups_order_input(user_a):
    dup_order = ["today-focus", "today-focus", "done-today"]
    preferences_svc.update_today_layout(user_a, order=dup_order)

    layout = preferences_svc.get_today_layout(user_a)
    # Stored order keeps the first occurrence; missing canonical ids
    # are then appended.
    assert layout["order"][:2] == ["today-focus", "done-today"]
    assert len(layout["order"]) == len(TODAY_SECTION_IDS)


@pytest.mark.django_db
def test_users_are_isolated(user_a, user_b):
    preferences_svc.update_today_layout(user_a, hidden=["done-today"])
    preferences_svc.update_today_layout(user_b, hidden=["sleeping"])

    a = preferences_svc.get_today_layout(user_a)
    b = preferences_svc.get_today_layout(user_b)
    assert a["hidden"] == ["done-today"]
    assert b["hidden"] == ["sleeping"]


# ---------------------------- GraphQL layer ---------------------------- #


@pytest.mark.django_db
def test_query_returns_defaults_for_new_user(execute_query, user_a):
    result = execute_query(TODAY_LAYOUT_QUERY, user_id=user_a)
    assert result.errors is None
    assert result.data["todayLayout"]["order"] == list(TODAY_SECTION_IDS)
    assert result.data["todayLayout"]["hidden"] == []


@pytest.mark.django_db
def test_query_unauthenticated_errors(execute_query):
    result = execute_query(TODAY_LAYOUT_QUERY, user_id=None)
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "UNAUTHENTICATED"


@pytest.mark.django_db
def test_mutation_updates_and_query_reflects_it(execute_query, user_a):
    new_order = list(reversed(TODAY_SECTION_IDS))
    res = execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"order": new_order, "hidden": ["done-today"]},
    )
    assert res.errors is None
    assert res.data["updateTodayLayout"]["order"] == new_order
    assert res.data["updateTodayLayout"]["hidden"] == ["done-today"]

    follow_up = execute_query(TODAY_LAYOUT_QUERY, user_id=user_a)
    assert follow_up.data["todayLayout"]["order"] == new_order
    assert follow_up.data["todayLayout"]["hidden"] == ["done-today"]


@pytest.mark.django_db
def test_mutation_rejects_unknown_id(execute_query, user_a):
    res = execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"hidden": ["not-real"]},
    )
    assert res.errors is not None
    assert res.errors[0].extensions["code"] == "BAD_INPUT"


@pytest.mark.django_db
def test_mutation_rejects_locked_section(execute_query, user_a):
    locked = next(iter(NON_HIDEABLE_TODAY_IDS))
    res = execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"hidden": [locked]},
    )
    assert res.errors is not None
    assert res.errors[0].extensions["code"] == "BAD_INPUT"


@pytest.mark.django_db
def test_reset_mutation(execute_query, user_a):
    execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"hidden": ["done-today"]},
    )

    res = execute_query(RESET_MUTATION, user_id=user_a)
    assert res.errors is None
    assert res.data["resetTodayLayout"]["hidden"] == []
    assert res.data["resetTodayLayout"]["order"] == list(TODAY_SECTION_IDS)


@pytest.mark.django_db
def test_mutation_isolates_users(execute_query, user_a, user_b):
    execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"hidden": ["done-today"]},
    )

    res = execute_query(TODAY_LAYOUT_QUERY, user_id=user_b)
    assert res.data["todayLayout"]["hidden"] == []

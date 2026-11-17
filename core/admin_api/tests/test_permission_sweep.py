"""Sweep tests: every admin field rejects non-admins, and no user-facing
input can carry a privileged field.

The old sweep called each mutation with no arguments. Any mutation with a
required argument then died in GraphQL validation before its resolver ran,
so the test passed whether or not the resolver checked admin. These tests
build a structurally valid call for every `admin*` field (queries too) from
the schema itself, and require the error to be the auth error.

If one fails after adding a field:
- `admin*` field not FORBIDDEN → its resolver must call `_admin_user_id(info)`
  before anything else (`core/admin_api/permissions.py`).
- privileged field in a user input → the client must never be able to set
  it; move it to an admin-only input or set it on the server.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from graphql import (
    GraphQLEnumType,
    GraphQLField,
    GraphQLInputObjectType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLScalarType,
    Undefined,
    get_named_type,
)

from core.assistant.models import AccountProfile
from core.schema import schema

GQL = schema._schema

# Fields a client must never be able to set on its own account. Compared
# case-insensitively against input field and argument names.
PRIVILEGED_FIELDS = {
    "isadmin",
    "role",
    "plan",
    "userid",
    "isbillingexempt",
    "billingexemptuntil",
    "betacohort",
    "billingcustomerid",
    "billingtransactionid",
    "billingsource",
    "planrenewsat",
}

# Root fields that are not `admin*` but deliberately need no admin check.
NON_ADMIN_OK = {"me"}

_SCALAR_SAMPLES: dict[str, Any] = {
    "ID": "00000000-0000-0000-0000-000000000001",
    "UUID": "00000000-0000-0000-0000-000000000001",
    "String": "x",
    "Int": 1,
    "Float": 1.0,
    "Boolean": False,
    "DateTime": "2026-01-01T00:00:00+00:00",
    "Date": "2026-01-01",
    "Time": "00:00:00",
    "JSON": {},
    "Decimal": "1",
}


def _sample(type_) -> Any:
    """A valid variable value for a GraphQL input type (required parts only)."""
    if isinstance(type_, GraphQLNonNull):
        return _sample(type_.of_type)
    if isinstance(type_, GraphQLList):
        return []
    if isinstance(type_, GraphQLEnumType):
        return next(iter(type_.values))
    if isinstance(type_, GraphQLInputObjectType):
        return {
            name: _sample(field.type)
            for name, field in type_.fields.items()
            if isinstance(field.type, GraphQLNonNull) and field.default_value is Undefined
        }
    if isinstance(type_, GraphQLScalarType):
        if type_.name not in _SCALAR_SAMPLES:
            raise AssertionError(f"Add a sample for scalar {type_.name}")
        return _SCALAR_SAMPLES[type_.name]
    raise AssertionError(f"Unhandled input type {type_}")


def _document(op: str, name: str, field: GraphQLField) -> tuple[str, dict]:
    var_defs, call_args, variables = [], [], {}
    for i, (arg_name, arg) in enumerate(field.args.items()):
        if not isinstance(arg.type, GraphQLNonNull):
            continue  # optional: leave it out
        var = f"v{i}"
        var_defs.append(f"${var}: {arg.type}")
        call_args.append(f"{arg_name}: ${var}")
        variables[var] = _sample(arg.type)
    selection = "" if isinstance(get_named_type(field.type), (GraphQLScalarType, GraphQLEnumType)) else " { __typename }"
    defs = f"({', '.join(var_defs)})" if var_defs else ""
    args = f"({', '.join(call_args)})" if call_args else ""
    return f"{op} Sweep{defs} {{ {name}{args}{selection} }}", variables


def _admin_fields() -> list[tuple[str, str, GraphQLField]]:
    out = []
    for op, root in (("query", GQL.query_type), ("mutation", GQL.mutation_type)):
        for name, field in root.fields.items():
            if name.startswith("admin"):
                out.append((op, name, field))
    return out


def _codes(result) -> set[str]:
    return {(e.extensions or {}).get("code") for e in (result.errors or [])}


ADMIN_FIELDS = _admin_fields()


def test_sweep_finds_admin_fields():
    ops = {op for op, _, _ in ADMIN_FIELDS}
    assert ops == {"query", "mutation"}, "Sweep lost track of admin queries or mutations"
    assert len(ADMIN_FIELDS) > 40


@pytest.mark.django_db
@pytest.mark.parametrize("op,name,field", ADMIN_FIELDS, ids=[n for _, n, _ in ADMIN_FIELDS])
def test_admin_field_rejects_non_admin(execute_query, user_a, op, name, field):
    AccountProfile.objects.create(user_id=user_a, is_admin=False)
    doc, variables = _document(op, name, field)
    result = execute_query(doc, user_id=user_a, variable_values=variables)
    assert result.errors, f"{name} answered a non-admin: {result.data}"
    assert _codes(result) == {"FORBIDDEN"}, (
        f"{name} failed with {[e.message for e in result.errors]} instead of FORBIDDEN; "
        "either the call is malformed (fix the sweep) or the resolver does work "
        "before `_admin_user_id(info)`."
    )


@pytest.mark.django_db
@pytest.mark.parametrize("op,name,field", ADMIN_FIELDS, ids=[n for _, n, _ in ADMIN_FIELDS])
def test_admin_field_rejects_anonymous(execute_query, op, name, field):
    doc, variables = _document(op, name, field)
    result = execute_query(doc, user_id=None, variable_values=variables)
    assert result.errors, f"{name} answered an anonymous caller: {result.data}"
    assert _codes(result) <= {"UNAUTHENTICATED", "FORBIDDEN"}, [e.message for e in result.errors]


@pytest.mark.django_db
def test_sweep_call_reaches_resolver_for_admin(execute_query, user_a):
    """Control: the generated call is valid, so an admin gets past auth."""
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    field = GQL.query_type.fields["adminBugReportsUnreadCount"]
    doc, variables = _document("query", "adminBugReportsUnreadCount", field)
    result = execute_query(doc, user_id=user_a, variable_values=variables)
    assert result.errors is None, result.errors
    assert result.data == {"adminBugReportsUnreadCount": 0}


# ---------------------------------------------------------------------------
# Privileged fields: never settable from a user-facing field
# ---------------------------------------------------------------------------


def _input_names(type_, seen: set[str]) -> set[str]:
    """Every field name reachable inside an input type."""
    named = get_named_type(type_)
    if not isinstance(named, GraphQLInputObjectType) or named.name in seen:
        return set()
    seen.add(named.name)
    names = set()
    for fname, f in named.fields.items():
        names.add(fname)
        names |= _input_names(f.type, seen)
    return names


def test_user_facing_inputs_have_no_privileged_fields():
    offenders = []
    for root in (GQL.query_type, GQL.mutation_type):
        for name, field in root.fields.items():
            if name.startswith("admin") or name in NON_ADMIN_OK:
                continue
            names: set[str] = set()
            for arg_name, arg in field.args.items():
                names.add(arg_name)
                names |= _input_names(arg.type, set())
            bad = {n for n in names if n.lower() in PRIVILEGED_FIELDS}
            if bad:
                offenders.append((name, sorted(bad)))
    assert not offenders, f"User-facing fields accept privileged inputs: {offenders}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "doc",
    [
        'mutation { updateNotificationSettings(data: {locale: "en", isAdmin: true}) { locale } }',
        'mutation { updateProfile(firstName: "x", isAdmin: true) { firstName } }',
        'mutation { updateProfile(firstName: "x", plan: "studio") { firstName } }',
        'mutation { completeOnboarding(isAdmin: true) { status } }',
    ],
)
def test_extra_privileged_field_is_rejected_and_account_stays_normal(execute_query, user_a, doc):
    AccountProfile.objects.create(user_id=user_a, is_admin=False, plan="free")
    result = execute_query(doc, user_id=user_a)
    assert result.errors, "An unknown privileged field was accepted"
    profile = AccountProfile.objects.get(user_id=user_a)
    assert profile.is_admin is False
    assert profile.plan == "free"
    me = execute_query("query { me { isAdmin } }", user_id=user_a)
    assert me.data == {"me": {"isAdmin": False}}


@pytest.mark.django_db
def test_new_profile_is_never_admin(user_a):
    from core.assistant.quotas import get_or_create_profile

    assert get_or_create_profile(user_a).is_admin is False


# ---------------------------------------------------------------------------
# MFA: admin fields require a session that passed TOTP (JWT aal == "aal2")
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("op,name,field", ADMIN_FIELDS, ids=[n for _, n, _ in ADMIN_FIELDS])
def test_admin_field_requires_second_factor(execute_query, user_a, op, name, field):
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    doc, variables = _document(op, name, field)
    for aal in ("aal1", None):
        result = execute_query(doc, user_id=user_a, variable_values=variables, aal=aal)
        assert _codes(result) == {"MFA_REQUIRED"}, (name, aal, [e.message for e in result.errors or []])


@pytest.mark.django_db
def test_non_admin_without_mfa_still_gets_forbidden(execute_query, user_a):
    """A non-admin must not learn that the panel asks for a second factor."""
    AccountProfile.objects.create(user_id=user_a, is_admin=False)
    result = execute_query("query { adminBugReportsUnreadCount }", user_id=user_a, aal="aal1")
    assert _codes(result) == {"FORBIDDEN"}


@pytest.mark.django_db
def test_me_does_not_require_mfa(execute_query, user_a):
    """`me` decides whether to show the panel, so it must answer on aal1."""
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    result = execute_query("query { me { isAdmin } }", user_id=user_a, aal="aal1")
    assert result.data == {"me": {"isAdmin": True}}


@pytest.mark.django_db
def test_mfa_switch_off_lets_aal1_admin_in(execute_query, user_a, settings):
    settings.ADMIN_REQUIRE_MFA = False
    AccountProfile.objects.create(user_id=user_a, is_admin=True)
    result = execute_query("query { adminBugReportsUnreadCount }", user_id=user_a, aal="aal1")
    assert result.errors is None, result.errors

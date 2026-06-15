"""Security / scope tests for the MCP connector policy layer.

Two halves:

* **Desired scope (positive)** — the connector exposes exactly what we want
  per plan: free = read + adjust priority; pro+ = full CRUD.
* **Bypass attempts (negative)** — everything outside that scope is rejected
  *server-side*: plan escalation, cross-user reads/writes (IDOR), forged
  `user_id` in args, the narrow priority tool being used to smuggle a full
  update, admin/plan tools being reachable, and unknown tool names.

All enforcement is verified at `policy.mcp_call` (the `tools/call` gate) and
`policy.mcp_tools_for` (the `tools/list` filter). A final group locks the
*foundation* invariants of the shared tool layer the connector inherits.
"""

from __future__ import annotations

import uuid

import pytest

from core.assistant import tools
from core.mcp import policy
from core.models import Idea, Project, Task


# --------------------------------------------------------------------------
# A. Desired scope — positive
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_free_can_read(user_a, make_project):
    make_project(user_a, name="A1")
    out = policy.mcp_call("free", "list_projects", user_a, {})
    assert "error" not in out
    assert any(p["name"] == "A1" for p in out["projects"])


@pytest.mark.django_db
def test_free_can_set_priority(user_a, make_project):
    p = make_project(user_a, priority="low")
    out = policy.mcp_call(
        "free", "set_project_priority", user_a, {"id": str(p.id), "priority": "high"}
    )
    assert out.get("ok") is True
    p.refresh_from_db()
    assert p.priority == "high"


@pytest.mark.django_db
def test_pro_can_create(user_a):
    out = policy.mcp_call("pro", "create_task", user_a, {"title": "ship it"})
    assert "error" not in out
    assert Task.objects.filter(user_id=user_a, title="ship it").exists()


@pytest.mark.django_db
def test_pro_can_delete(user_a, make_project):
    p = make_project(user_a)
    out = policy.mcp_call("pro", "delete_project", user_a, {"id": str(p.id), "confirm": True})
    assert "error" not in out
    assert not Project.objects.filter(pk=p.id).exists()


def test_tools_list_free_is_read_plus_priority_only():
    names = {t.name for t in policy.mcp_tools_for("free")}
    # reads present
    assert {"list_projects", "get_dashboard_summary", "search"} <= names
    # the one allowed write
    assert "set_project_priority" in names
    # every other write absent
    assert "update_project" not in names
    assert "delete_project" not in names
    assert "create_task" not in names
    assert "create_idea" not in names


def test_tools_list_pro_includes_writes():
    names = {t.name for t in policy.mcp_tools_for("pro")}
    assert {"create_task", "update_project", "delete_project", "create_idea"} <= names


def test_basic_tier_matches_free():
    assert {t.name for t in policy.mcp_tools_for("basic")} == {
        t.name for t in policy.mcp_tools_for("free")
    }


# --------------------------------------------------------------------------
# B. Bypass attempts — negative
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_free_cannot_create(user_a):
    out = policy.mcp_call("free", "create_task", user_a, {"title": "nope"})
    assert "error" in out
    assert Task.objects.filter(user_id=user_a).count() == 0


@pytest.mark.django_db
def test_free_cannot_delete(user_a, make_project):
    p = make_project(user_a)
    out = policy.mcp_call("free", "delete_project", user_a, {"id": str(p.id), "confirm": True})
    assert "error" in out
    assert Project.objects.filter(pk=p.id).exists()  # untouched


@pytest.mark.django_db
def test_priority_tool_cannot_smuggle_full_update(user_a, make_project):
    """The narrow priority tool must not open the full update_project bundle.

    Even though `set_project_priority` is allowed on free, calling the full
    `update_project` (which could rename / change status) stays rejected.
    """
    p = make_project(user_a, name="orig", status="active", priority="low")
    out = policy.mcp_call(
        "free",
        "update_project",
        user_a,
        {"id": str(p.id), "name": "hacked", "status": "archived", "priority": "high"},
    )
    assert "error" in out
    p.refresh_from_db()
    assert p.name == "orig"
    assert p.status == "active"
    assert p.priority == "low"


@pytest.mark.django_db
def test_priority_tool_ignores_extra_fields(user_a, make_project):
    """Passing extra fields to the narrow tool changes only priority."""
    p = make_project(user_a, name="orig", status="active", priority="low")
    out = policy.mcp_call(
        "free",
        "set_project_priority",
        user_a,
        {"id": str(p.id), "priority": "critical", "name": "hacked", "status": "archived"},
    )
    assert out.get("ok") is True
    p.refresh_from_db()
    assert p.priority == "critical"
    assert p.name == "orig"      # extra field ignored
    assert p.status == "active"  # extra field ignored


@pytest.mark.django_db
def test_cross_user_read_blocked(user_a, user_b, make_project):
    p = make_project(user_b, name="B secret")
    out = policy.mcp_call("free", "get_project_detail", user_a, {"id": str(p.id)})
    assert "error" in out


@pytest.mark.django_db
def test_cross_user_priority_idor(user_a, user_b, make_project):
    p = make_project(user_b, priority="low")
    out = policy.mcp_call(
        "free", "set_project_priority", user_a, {"id": str(p.id), "priority": "critical"}
    )
    assert "error" in out
    p.refresh_from_db()
    assert p.priority == "low"  # B's project untouched


@pytest.mark.django_db
def test_cross_user_delete_idor(user_a, user_b, make_project):
    p = make_project(user_b)
    out = policy.mcp_call("pro", "delete_project", user_a, {"id": str(p.id), "confirm": True})
    assert "error" in out
    assert Project.objects.filter(pk=p.id).exists()  # B's project survives


@pytest.mark.django_db
def test_forged_user_id_in_args_is_ignored(user_a, user_b, make_project):
    """A forged `user_id` in args must not re-scope to another user."""
    pa = make_project(user_a, priority="low")
    pb = make_project(user_b, priority="low")

    # As A, try to touch B's project via B's id + a forged user_id arg.
    out = policy.mcp_call(
        "free",
        "set_project_priority",
        user_a,
        {"id": str(pb.id), "priority": "critical", "user_id": str(user_b)},
    )
    assert "error" in out
    pb.refresh_from_db()
    assert pb.priority == "low"  # B untouched despite forged user_id

    # A's own project is still editable — proves scope comes from the
    # server-supplied user_id param, not from args.
    out2 = policy.mcp_call(
        "free",
        "set_project_priority",
        user_a,
        {"id": str(pa.id), "priority": "high", "user_id": str(user_b)},
    )
    assert out2.get("ok") is True
    pa.refresh_from_db()
    assert pa.priority == "high"


def test_no_tool_can_change_plan_or_billing():
    """No connector tool can escalate plan or touch billing/subscription."""
    for t in tools.all_tools():
        low = t.name.lower()
        assert "plan" not in low
        assert "billing" not in low
        assert "subscription" not in low
    assert tools.get_tool("set_plan") is None


def test_no_admin_tools_exposed():
    for t in tools.all_tools():
        assert "admin" not in t.name.lower()


@pytest.mark.django_db
def test_unknown_tool_returns_error_not_crash(user_a):
    out = policy.mcp_call("pro", "drop_all_tables", user_a, {})
    assert "error" in out
    assert "Unknown tool" in out["error"]


def test_unknown_plan_defaults_to_most_restrictive():
    names = {t.name for t in policy.mcp_tools_for("totally-made-up-plan")}
    assert "list_projects" in names       # reads allowed
    assert "delete_project" not in names  # writes denied


def test_mcp_allows_is_consistent_with_tools_for():
    for plan in ("free", "basic", "pro", "admin"):
        advertised = {t.name for t in policy.mcp_tools_for(plan)}
        for name in advertised:
            assert policy.mcp_allows(plan, name), f"{name} advertised but not allowed on {plan}"
    # spot-check the gate directly
    assert not policy.mcp_allows("free", "delete_project")
    assert policy.mcp_allows("free", "set_project_priority")
    assert policy.mcp_allows("pro", "delete_project")


# --------------------------------------------------------------------------
# C. Foundation — the shared tool layer the connector inherits
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_inapp_call_blocks_free_writes(user_a):
    """The in-app assistant's own gate (`tools.call`) blocks free writes."""
    out = tools.call("delete_project", user_a, {"id": str(uuid.uuid4())}, plan="free")
    assert "error" in out


@pytest.mark.django_db
def test_channels_are_decoupled_for_priority(user_a, make_project):
    """The priority tool is connector-only on free: the in-app channel
    (`tools.call`, gated by `plan_required="pro"`) still denies it to free,
    while the connector (`policy.mcp_call`) allows it. Proves we did not
    loosen the in-app assistant when opening priority on the connector."""
    p = make_project(user_a, priority="low")

    # in-app: denied for free
    out = tools.call(
        "set_project_priority", user_a, {"id": str(p.id), "priority": "high"}, plan="free"
    )
    assert "error" in out
    p.refresh_from_db()
    assert p.priority == "low"

    # connector: allowed for free
    out2 = policy.mcp_call(
        "free", "set_project_priority", user_a, {"id": str(p.id), "priority": "high"}
    )
    assert out2.get("ok") is True
    p.refresh_from_db()
    assert p.priority == "high"


@pytest.mark.django_db
def test_inapp_call_cross_user_idor(user_a, user_b, make_project):
    p = make_project(user_b)
    out = tools.call("get_project_detail", user_a, {"id": str(p.id)}, plan="free")
    assert "error" in out


@pytest.mark.django_db
def test_every_mutating_tool_is_pro_gated_in_app():
    """Sanity: every connector-mutating tool is `plan_required="pro"` in the
    shared layer, so the in-app free tier never gets writes by accident."""
    for t in tools.all_tools():
        if t.mutates:
            assert t.plan_required == "pro", f"{t.name} mutates but is not pro-gated in-app"

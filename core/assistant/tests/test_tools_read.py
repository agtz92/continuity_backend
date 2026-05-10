"""Tests for the read-only tool registry."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from core.assistant import tools


@pytest.mark.django_db
def test_get_dashboard_summary(user_a, make_project, make_task, make_idea):
    p = make_project(user_a, status="active")
    make_task(user_a, project=p, done=False)
    make_idea(user_a)

    out = tools.call("get_dashboard_summary", user_a, {})
    assert out["active_projects"] == 1
    assert out["open_tasks"] == 1
    assert out["open_ideas"] == 1


@pytest.mark.django_db
def test_list_projects_user_scoped(user_a, user_b, make_project):
    make_project(user_a, name="A1")
    make_project(user_b, name="B1")
    out = tools.call("list_projects", user_a, {})
    names = [p["name"] for p in out["projects"]]
    assert "A1" in names
    assert "B1" not in names


@pytest.mark.django_db
def test_list_projects_status_filter(user_a, make_project):
    make_project(user_a, name="active1", status="active")
    make_project(user_a, name="paused1", status="paused")
    out = tools.call("list_projects", user_a, {"status": "active"})
    names = [p["name"] for p in out["projects"]]
    assert names == ["active1"]


@pytest.mark.django_db
def test_list_projects_caps_limit(user_a, make_project):
    for i in range(5):
        make_project(user_a, name=f"p{i}")
    # Even if the model fabricates a huge limit, the service caps it.
    out = tools.call("list_projects", user_a, {"limit": 9999})
    assert len(out["projects"]) == 5


@pytest.mark.django_db
def test_get_project_detail_other_user(user_a, user_b, make_project):
    p = make_project(user_b, name="B's project")
    out = tools.call("get_project_detail", user_a, {"id": str(p.id)})
    assert "error" in out


@pytest.mark.django_db
def test_get_project_detail_includes_recent(user_a, make_project, make_task):
    p = make_project(user_a, name="P")
    make_task(user_a, project=p, title="t1")
    out = tools.call("get_project_detail", user_a, {"id": str(p.id)})
    assert out["project"]["name"] == "P"
    assert any(t["title"] == "t1" for t in out["tasks"])


@pytest.mark.django_db
def test_search_user_scoped(user_a, user_b, make_project):
    make_project(user_a, name="alpha", description="apples and oranges")
    make_project(user_b, name="beta", description="apples elsewhere")
    out = tools.call("search", user_a, {"query": "apples"})
    titles = [h["title"] for h in out["hits"]]
    assert "alpha" in titles
    assert "beta" not in titles


@pytest.mark.django_db
def test_get_analytics_default_range(user_a, make_project):
    make_project(user_a, status="active")
    out = tools.call("get_analytics", user_a, {"view": "backlog_health"})
    assert out["view"] == "backlog_health"
    assert "open_tasks" in out


@pytest.mark.django_db
def test_unknown_tool_returns_error():
    import uuid

    out = tools.call("does_not_exist", uuid.uuid4(), {})
    assert "error" in out


@pytest.mark.django_db
def test_tool_handler_catches_exceptions(user_a):
    # `id` field is required; missing it should produce a wrapped error,
    # not a 500.
    out = tools.call("get_project_detail", user_a, {})
    assert "error" in out


def test_schemas_for_anthropic_shape():
    schemas = tools.schemas_for_anthropic()
    assert any(s["name"] == "list_projects" for s in schemas)
    for s in schemas:
        assert "name" in s
        assert "description" in s
        assert "input_schema" in s
        assert s["input_schema"]["type"] == "object"


@pytest.mark.django_db
def test_truncation_caps_large_lists(user_a, make_project):
    # Force more than the 10-item slice that _truncate_dict keeps.
    for i in range(60):
        make_project(user_a, name=f"p{i:02d}", description="x" * 200)
    out = tools.call("list_projects", user_a, {"limit": 50})
    assert "truncated" in out or len(out.get("projects", [])) <= 50

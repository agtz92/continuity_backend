"""Tests for the `dashboard` query.

The dashboard is the only query in the schema and it's the foundation
for every read in the frontend. We verify shape, ownership scoping,
and the `lastBackup` field.
"""

import pytest


DASHBOARD_QUERY = """
    query {
        dashboard {
            projects { id name status }
            tasks    { id title done projectId }
            ideas    { id title }
            activities { id kind projectId note }
            categories { id name color }
            lastBackup
        }
    }
"""


@pytest.mark.django_db
def test_dashboard_empty_for_new_user(execute_query, user_a):
    """A user with no data sees empty arrays and `lastBackup=None`."""
    result = execute_query(DASHBOARD_QUERY, user_id=user_a)

    assert result.errors is None
    dash = result.data["dashboard"]
    assert dash["projects"] == []
    assert dash["tasks"] == []
    assert dash["ideas"] == []
    assert dash["activities"] == []
    assert dash["categories"] == []
    assert dash["lastBackup"] is None


@pytest.mark.django_db
def test_dashboard_returns_owned_data(
    execute_query, user_a, project_factory, task_factory, idea_factory
):
    """A user sees their own projects/tasks/ideas in the dashboard."""
    project = project_factory(user_a, name="Mine")
    task_factory(user_a, project=project, title="My task")
    idea_factory(user_a, title="My idea")

    result = execute_query(DASHBOARD_QUERY, user_id=user_a)

    assert result.errors is None
    dash = result.data["dashboard"]
    assert [p["name"] for p in dash["projects"]] == ["Mine"]
    assert [t["title"] for t in dash["tasks"]] == ["My task"]
    assert dash["tasks"][0]["projectId"] == str(project.id)
    assert [i["title"] for i in dash["ideas"]] == ["My idea"]


@pytest.mark.django_db
def test_dashboard_isolates_users(
    execute_query, user_a, user_b, project_factory, task_factory, idea_factory
):
    """User A must NEVER see user B's data — and vice versa."""
    project_factory(user_a, name="A's project")
    project_factory(user_b, name="B's project")
    task_factory(user_a, title="A's task")
    task_factory(user_b, title="B's task")
    idea_factory(user_a, title="A's idea")
    idea_factory(user_b, title="B's idea")

    result_a = execute_query(DASHBOARD_QUERY, user_id=user_a)
    result_b = execute_query(DASHBOARD_QUERY, user_id=user_b)

    assert {p["name"] for p in result_a.data["dashboard"]["projects"]} == {"A's project"}
    assert {p["name"] for p in result_b.data["dashboard"]["projects"]} == {"B's project"}
    assert {t["title"] for t in result_a.data["dashboard"]["tasks"]} == {"A's task"}
    assert {t["title"] for t in result_b.data["dashboard"]["tasks"]} == {"B's task"}
    assert {i["title"] for i in result_a.data["dashboard"]["ideas"]} == {"A's idea"}
    assert {i["title"] for i in result_b.data["dashboard"]["ideas"]} == {"B's idea"}

"""Tests for the error contract.

These tests pin the exact error semantics the frontend relies on:

* Unauthenticated requests → `extensions.code == "UNAUTHENTICATED"`.
* Missing-or-foreign rows  → `extensions.code == "NOT_FOUND"`.
* Cross-user access       → `NOT_FOUND` (NOT a 403; we don't want to
  leak the existence of another user's row).

If any of these change, the frontend's `errorLink` and toast UX will
break — so these tests double as a contract.
"""

import pytest


def _first_error_code(result):
    assert result.errors, f"Expected an error, got data={result.data!r}"
    err = result.errors[0]
    return (err.extensions or {}).get("code")


# ---------- Unauthenticated ----------


@pytest.mark.django_db
def test_dashboard_query_requires_auth(execute_query):
    """Hitting `dashboard` with no user_id raises UNAUTHENTICATED."""
    result = execute_query("{ dashboard { lastBackup } }", user_id=None)
    assert _first_error_code(result) == "UNAUTHENTICATED"
    assert "Not authenticated" in result.errors[0].message


@pytest.mark.django_db
def test_create_project_requires_auth(execute_query):
    result = execute_query(
        "mutation($d: ProjectInput!) { createProject(data: $d) { id } }",
        user_id=None,
        variable_values={"data": {"name": "x"}},
    )
    assert _first_error_code(result) == "UNAUTHENTICATED"


@pytest.mark.django_db
def test_toggle_task_requires_auth(execute_query, user_a, task_factory):
    """Even when a task exists, no user_id → UNAUTHENTICATED, not NOT_FOUND."""
    task = task_factory(user_a)
    result = execute_query(
        "mutation($id: ID!) { toggleTask(id: $id) { id } }",
        user_id=None,
        variable_values={"id": str(task.id)},
    )
    assert _first_error_code(result) == "UNAUTHENTICATED"


# ---------- Not found ----------


@pytest.mark.django_db
def test_update_missing_project_is_not_found(execute_query, user_a):
    import uuid

    result = execute_query(
        "mutation($id: ID!, $d: ProjectInput!) { updateProject(id: $id, data: $d) { id } }",
        user_id=user_a,
        variable_values={"id": str(uuid.uuid4()), "data": {"name": "x"}},
    )
    assert _first_error_code(result) == "NOT_FOUND"
    assert "Project not found" in result.errors[0].message


@pytest.mark.django_db
def test_update_missing_task_is_not_found(execute_query, user_a):
    import uuid

    result = execute_query(
        "mutation($id: ID!, $d: TaskInput!) { updateTask(id: $id, data: $d) { id } }",
        user_id=user_a,
        variable_values={"id": str(uuid.uuid4()), "data": {"title": "x"}},
    )
    assert _first_error_code(result) == "NOT_FOUND"


@pytest.mark.django_db
def test_toggle_missing_task_is_not_found(execute_query, user_a):
    import uuid

    result = execute_query(
        "mutation($id: ID!) { toggleTask(id: $id) { id } }",
        user_id=user_a,
        variable_values={"id": str(uuid.uuid4())},
    )
    assert _first_error_code(result) == "NOT_FOUND"


@pytest.mark.django_db
def test_promote_missing_idea_is_not_found(execute_query, user_a):
    import uuid

    result = execute_query(
        "mutation($id: ID!) { promoteIdea(id: $id) { id } }",
        user_id=user_a,
        variable_values={"id": str(uuid.uuid4())},
    )
    assert _first_error_code(result) == "NOT_FOUND"


@pytest.mark.django_db
def test_create_task_with_unknown_project_is_not_found(execute_query, user_a):
    """Creating a task referencing a non-existent project surfaces NOT_FOUND."""
    import uuid

    result = execute_query(
        "mutation($d: TaskInput!) { createTask(data: $d) { id } }",
        user_id=user_a,
        variable_values={
            "data": {"title": "x", "projectId": str(uuid.uuid4())}
        },
    )
    assert _first_error_code(result) == "NOT_FOUND"


@pytest.mark.django_db
def test_add_update_to_unknown_project_is_not_found(execute_query, user_a):
    import uuid

    result = execute_query(
        "mutation($p: ID!, $n: String!) { addUpdate(projectId: $p, note: $n) { id } }",
        user_id=user_a,
        variable_values={"p": str(uuid.uuid4()), "n": "x"},
    )
    assert _first_error_code(result) == "NOT_FOUND"


# ---------- Cross-user isolation ----------


@pytest.mark.django_db
def test_user_b_cannot_update_user_a_project(
    execute_query, user_a, user_b, project_factory
):
    """B tries to rename A's project → NOT_FOUND (not FORBIDDEN, by design)."""
    project = project_factory(user_a, name="A's")
    result = execute_query(
        "mutation($id: ID!, $d: ProjectInput!) { updateProject(id: $id, data: $d) { id name } }",
        user_id=user_b,
        variable_values={"id": str(project.id), "data": {"name": "Hijacked"}},
    )
    assert _first_error_code(result) == "NOT_FOUND"
    project.refresh_from_db()
    assert project.name == "A's"  # unchanged


@pytest.mark.django_db
def test_user_b_cannot_toggle_user_a_task(
    execute_query, user_a, user_b, task_factory
):
    task = task_factory(user_a, done=False)
    result = execute_query(
        "mutation($id: ID!) { toggleTask(id: $id) { id done } }",
        user_id=user_b,
        variable_values={"id": str(task.id)},
    )
    assert _first_error_code(result) == "NOT_FOUND"
    task.refresh_from_db()
    assert task.done is False  # unchanged


@pytest.mark.django_db
def test_user_b_cannot_create_task_in_user_a_project(
    execute_query, user_a, user_b, project_factory
):
    project = project_factory(user_a)
    result = execute_query(
        "mutation($d: TaskInput!) { createTask(data: $d) { id } }",
        user_id=user_b,
        variable_values={
            "data": {"title": "Sneaky", "projectId": str(project.id)}
        },
    )
    assert _first_error_code(result) == "NOT_FOUND"


@pytest.mark.django_db
def test_delete_silently_succeeds_for_foreign_id(
    execute_query, user_a, user_b, project_factory
):
    """`deleteProject` is best-effort: filtering by user_id means a foreign id
    just deletes nothing and returns True. This test pins that behavior so
    nobody accidentally changes it to raise.
    """
    project = project_factory(user_a, name="A's")
    result = execute_query(
        "mutation($id: ID!) { deleteProject(id: $id) }",
        user_id=user_b,
        variable_values={"id": str(project.id)},
    )
    assert result.errors is None
    assert result.data["deleteProject"] is True
    # A's project is still there.
    project.refresh_from_db()
    assert project.name == "A's"

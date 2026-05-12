"""Tests for every GraphQL mutation in `core.schema`.

Each mutation has at least one happy-path test. For mutations with
non-trivial side effects (toggle_task creates an Activity, creating a
task touches the project's last_activity, etc.) we verify those side
effects too.
"""

import pytest

from core.models import (
    BackupMeta,
    Category,
    Idea,
    Activity,
    ActivityKind,
    Project,
    Task,
)


# ---------- Projects ----------

CREATE_PROJECT = """
    mutation($data: ProjectInput!) {
        createProject(data: $data) {
            id name description status priority
        }
    }
"""

UPDATE_PROJECT = """
    mutation($id: ID!, $data: ProjectInput!) {
        updateProject(id: $id, data: $data) { id name status priority }
    }
"""

DELETE_PROJECT = """
    mutation($id: ID!) { deleteProject(id: $id) }
"""


@pytest.mark.django_db
def test_create_project(execute_query, user_a):
    result = execute_query(
        CREATE_PROJECT,
        user_id=user_a,
        variable_values={"data": {"name": "New", "status": "active"}},
    )
    assert result.errors is None
    assert result.data["createProject"]["name"] == "New"
    assert Project.objects.filter(user_id=user_a, name="New").exists()


@pytest.mark.django_db
def test_update_project_changes_fields(execute_query, user_a, project_factory):
    project = project_factory(user_a, name="Old", status="idea")
    result = execute_query(
        UPDATE_PROJECT,
        user_id=user_a,
        variable_values={
            "id": str(project.id),
            "data": {"name": "Renamed", "status": "active"},
        },
    )
    assert result.errors is None
    assert result.data["updateProject"]["name"] == "Renamed"
    assert result.data["updateProject"]["status"] == "active"


@pytest.mark.django_db
def test_delete_project(execute_query, user_a, project_factory):
    project = project_factory(user_a)
    result = execute_query(
        DELETE_PROJECT,
        user_id=user_a,
        variable_values={"id": str(project.id)},
    )
    assert result.errors is None
    assert result.data["deleteProject"] is True
    assert not Project.objects.filter(pk=project.id).exists()


# ---------- Tasks ----------

CREATE_TASK = """
    mutation($data: TaskInput!) {
        createTask(data: $data) { id title done projectId }
    }
"""

UPDATE_TASK = """
    mutation($id: ID!, $data: TaskInput!) {
        updateTask(id: $id, data: $data) { id title done }
    }
"""

TOGGLE_TASK = """
    mutation($id: ID!) {
        toggleTask(id: $id) { id done }
    }
"""

DELETE_TASK = """
    mutation($id: ID!) { deleteTask(id: $id) }
"""


@pytest.mark.django_db
def test_create_task_updates_project_last_activity(
    execute_query, user_a, project_factory
):
    """Creating a task linked to a project bumps last_activity."""
    project = project_factory(user_a)
    original_activity = project.last_activity

    result = execute_query(
        CREATE_TASK,
        user_id=user_a,
        variable_values={
            "data": {"title": "T", "projectId": str(project.id)}
        },
    )
    assert result.errors is None
    project.refresh_from_db()
    assert project.last_activity > original_activity


@pytest.mark.django_db
def test_update_task(execute_query, user_a, task_factory):
    task = task_factory(user_a, title="Old")
    result = execute_query(
        UPDATE_TASK,
        user_id=user_a,
        variable_values={
            "id": str(task.id),
            "data": {"title": "New", "done": True},
        },
    )
    assert result.errors is None
    task.refresh_from_db()
    assert task.title == "New"
    assert task.done is True
    assert task.completed_at is not None  # set when done flips to True


@pytest.mark.django_db
def test_toggle_task_logs_task_completed_when_completing(
    execute_query, user_a, project_factory, task_factory
):
    """Toggling a task to done writes an Activity row with kind=task_completed."""
    project = project_factory(user_a)
    task = task_factory(user_a, project=project, title="Important")
    Activity.objects.all().delete()

    result = execute_query(
        TOGGLE_TASK,
        user_id=user_a,
        variable_values={"id": str(task.id)},
    )
    assert result.errors is None
    assert result.data["toggleTask"]["done"] is True
    row = Activity.objects.filter(
        user_id=user_a, kind=ActivityKind.TASK_COMPLETED
    ).first()
    assert row is not None
    assert row.entity_title == "Important"
    assert row.project_id == project.id


@pytest.mark.django_db
def test_toggle_task_logs_nothing_when_uncompleting(
    execute_query, user_a, project_factory, task_factory
):
    project = project_factory(user_a)
    task = task_factory(user_a, project=project, done=True)
    Activity.objects.all().delete()
    result = execute_query(
        TOGGLE_TASK,
        user_id=user_a,
        variable_values={"id": str(task.id)},
    )
    assert result.errors is None
    assert result.data["toggleTask"]["done"] is False
    assert not Activity.objects.filter(user_id=user_a).exists()


@pytest.mark.django_db
def test_delete_task(execute_query, user_a, task_factory):
    task = task_factory(user_a)
    result = execute_query(
        DELETE_TASK, user_id=user_a, variable_values={"id": str(task.id)}
    )
    assert result.errors is None
    assert not Task.objects.filter(pk=task.id).exists()


# ---------- Ideas ----------

CREATE_IDEA = """
    mutation($data: IdeaInput!) {
        createIdea(data: $data) { id title }
    }
"""

DELETE_IDEA = """
    mutation($id: ID!) { deleteIdea(id: $id) }
"""

PROMOTE_IDEA = """
    mutation($id: ID!) {
        promoteIdea(id: $id) { id name status }
    }
"""


@pytest.mark.django_db
def test_create_idea(execute_query, user_a):
    result = execute_query(
        CREATE_IDEA,
        user_id=user_a,
        variable_values={"data": {"title": "Spark"}},
    )
    assert result.errors is None
    assert Idea.objects.filter(user_id=user_a, title="Spark").exists()


@pytest.mark.django_db
def test_promote_idea_creates_project_and_deletes_idea(
    execute_query, user_a, idea_factory
):
    idea = idea_factory(user_a, title="Promote me", description="d", why="w")
    result = execute_query(
        PROMOTE_IDEA, user_id=user_a, variable_values={"id": str(idea.id)}
    )
    assert result.errors is None
    assert result.data["promoteIdea"]["name"] == "Promote me"
    assert result.data["promoteIdea"]["status"] == "idea"
    assert not Idea.objects.filter(pk=idea.id).exists()
    assert Project.objects.filter(user_id=user_a, name="Promote me").exists()


@pytest.mark.django_db
def test_delete_idea(execute_query, user_a, idea_factory):
    idea = idea_factory(user_a)
    result = execute_query(
        DELETE_IDEA, user_id=user_a, variable_values={"id": str(idea.id)}
    )
    assert result.errors is None
    assert not Idea.objects.filter(pk=idea.id).exists()


# ---------- Categories ----------

CREATE_CATEGORY = """
    mutation($data: CategoryInput!) {
        createCategory(data: $data) { id name color }
    }
"""

UPDATE_CATEGORY = """
    mutation($id: ID!, $data: CategoryInput!) {
        updateCategory(id: $id, data: $data) { id name color }
    }
"""

DELETE_CATEGORY = """
    mutation($id: ID!) { deleteCategory(id: $id) }
"""


@pytest.mark.django_db
def test_create_category(execute_query, user_a):
    result = execute_query(
        CREATE_CATEGORY,
        user_id=user_a,
        variable_values={"data": {"name": "Work", "color": "blue"}},
    )
    assert result.errors is None
    assert result.data["createCategory"]["color"] == "blue"


@pytest.mark.django_db
def test_create_category_is_idempotent_per_user(execute_query, user_a):
    """The schema uses get_or_create, so a duplicate name just returns the same row."""
    execute_query(
        CREATE_CATEGORY,
        user_id=user_a,
        variable_values={"data": {"name": "Dup", "color": "blue"}},
    )
    result = execute_query(
        CREATE_CATEGORY,
        user_id=user_a,
        variable_values={"data": {"name": "Dup", "color": "red"}},
    )
    assert result.errors is None
    # Only one category, color stays the original because get_or_create.
    assert Category.objects.filter(user_id=user_a, name="Dup").count() == 1


@pytest.mark.django_db
def test_update_category(execute_query, user_a, category_factory):
    cat = category_factory(user_a, name="Old", color="emerald")
    result = execute_query(
        UPDATE_CATEGORY,
        user_id=user_a,
        variable_values={
            "id": str(cat.id),
            "data": {"name": "New", "color": "purple"},
        },
    )
    assert result.errors is None
    cat.refresh_from_db()
    assert cat.name == "New"
    assert cat.color == "purple"


@pytest.mark.django_db
def test_delete_category(execute_query, user_a, category_factory):
    cat = category_factory(user_a)
    result = execute_query(
        DELETE_CATEGORY,
        user_id=user_a,
        variable_values={"id": str(cat.id)},
    )
    assert result.errors is None
    assert not Category.objects.filter(pk=cat.id).exists()


# ---------- Notes ----------

ADD_NOTE = """
    mutation($projectId: ID!, $note: String!) {
        addNote(projectId: $projectId, note: $note) {
            id kind projectId note
        }
    }
"""


@pytest.mark.django_db
def test_add_note_bumps_project_last_activity(
    execute_query, user_a, project_factory
):
    project = project_factory(user_a)
    original = project.last_activity

    result = execute_query(
        ADD_NOTE,
        user_id=user_a,
        variable_values={"projectId": str(project.id), "note": "Made progress"},
    )
    assert result.errors is None
    assert result.data["addNote"]["kind"] == "note"
    project.refresh_from_db()
    assert project.last_activity > original
    assert Activity.objects.filter(
        user_id=user_a, kind=ActivityKind.NOTE, project_id=project.id
    ).count() == 1


# ---------- Backup ----------

MARK_BACKUP = """
    mutation { markBackup }
"""


@pytest.mark.django_db
def test_mark_backup_creates_meta(execute_query, user_a):
    result = execute_query(MARK_BACKUP, user_id=user_a)
    assert result.errors is None
    assert BackupMeta.objects.filter(user_id=user_a).exists()


@pytest.mark.django_db
def test_mark_backup_updates_existing_meta(execute_query, user_a):
    """Calling markBackup twice updates the same row, doesn't create a duplicate."""
    execute_query(MARK_BACKUP, user_id=user_a)
    first = BackupMeta.objects.get(user_id=user_a).last_backup

    result = execute_query(MARK_BACKUP, user_id=user_a)
    assert result.errors is None
    assert BackupMeta.objects.filter(user_id=user_a).count() == 1
    second = BackupMeta.objects.get(user_id=user_a).last_backup
    assert second >= first

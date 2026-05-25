"""End-to-end tier quota tests.

These exercise `check_entity_quota` against real DB state, covering:

- Per-kind caps for Free / Pro / Studio / Admin (where Studio + Admin
  should be unlimited).
- The cross-kind block: if user is over the cap on `projects` they
  cannot create tasks/notes/etc. either.
- Archived/completed entities don't count toward open caps.
- Per-project caps (tasks_per_project, notes_per_project) are
  enforced separately from totals.
"""

from __future__ import annotations

import uuid

import pytest

from core.assistant.models import AccountProfile
from core.models import Category, Idea, Project, ProjectNote, Routine, Task
from core.quotas import (
    ENTITY_QUOTAS,
    EntityQuotaExceeded,
    check_entity_quota,
)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def free_user(db, user_id):
    AccountProfile.objects.create(user_id=user_id, plan="free")
    return user_id


@pytest.fixture
def pro_user(db, user_id):
    AccountProfile.objects.create(user_id=user_id, plan="pro")
    return user_id


@pytest.fixture
def studio_user(db, user_id):
    AccountProfile.objects.create(user_id=user_id, plan="studio")
    return user_id


@pytest.fixture
def admin_user(db, user_id):
    AccountProfile.objects.create(user_id=user_id, plan="admin")
    return user_id


def _make_projects(user_id, n, status="active"):
    for i in range(n):
        Project.objects.create(
            user_id=user_id,
            name=f"P{i}",
            status=status,
            priority="medium",
        )


def _make_tasks(user_id, n, project=None, done=False):
    for i in range(n):
        Task.objects.create(
            user_id=user_id,
            project=project,
            title=f"T{i}",
            done=done,
        )


# ---------- Per-kind caps ----------


class TestProjectQuota:
    @pytest.mark.django_db
    def test_free_can_create_up_to_3(self, free_user):
        _make_projects(free_user, 2)
        check_entity_quota(free_user, "projects")  # third still ok

    @pytest.mark.django_db
    def test_free_4th_rejected(self, free_user):
        _make_projects(free_user, 3)
        with pytest.raises(EntityQuotaExceeded) as exc:
            check_entity_quota(free_user, "projects")
        assert exc.value.kind == "projects"
        assert exc.value.cap == 3
        assert exc.value.current == 3

    @pytest.mark.django_db
    def test_archived_doesnt_count(self, free_user):
        _make_projects(free_user, 3, status="archived")
        # 3 archived + about to create the 1st active — allowed
        check_entity_quota(free_user, "projects")

    @pytest.mark.django_db
    def test_pro_allows_more(self, pro_user):
        _make_projects(pro_user, 20)
        check_entity_quota(pro_user, "projects")

    @pytest.mark.django_db
    def test_pro_rejected_at_25(self, pro_user):
        _make_projects(pro_user, 25)
        with pytest.raises(EntityQuotaExceeded):
            check_entity_quota(pro_user, "projects")

    @pytest.mark.django_db
    def test_studio_unlimited(self, studio_user):
        _make_projects(studio_user, 200)
        check_entity_quota(studio_user, "projects")  # no raise

    @pytest.mark.django_db
    def test_admin_unlimited(self, admin_user):
        _make_projects(admin_user, 500)
        check_entity_quota(admin_user, "projects")


class TestTaskQuota:
    @pytest.mark.django_db
    def test_completed_tasks_dont_count(self, free_user):
        _make_tasks(free_user, 100, done=True)
        check_entity_quota(free_user, "tasks_total")  # 0 open, cap=50

    @pytest.mark.django_db
    def test_open_tasks_count_against_cap(self, free_user):
        _make_tasks(free_user, 50, done=False)
        with pytest.raises(EntityQuotaExceeded) as exc:
            check_entity_quota(free_user, "tasks_total")
        assert exc.value.kind == "tasks_total"

    @pytest.mark.django_db
    def test_per_project_cap_independent_of_total(self, free_user):
        project = Project.objects.create(
            user_id=free_user, name="P", status="active", priority="medium"
        )
        _make_tasks(free_user, 20, project=project, done=False)
        with pytest.raises(EntityQuotaExceeded) as exc:
            check_entity_quota(free_user, "tasks_per_project", project_id=project.id)
        assert exc.value.kind == "tasks_per_project"
        assert exc.value.cap == 20

    @pytest.mark.django_db
    def test_per_project_cap_only_counts_that_project(self, free_user):
        p1 = Project.objects.create(
            user_id=free_user, name="A", status="active", priority="medium"
        )
        p2 = Project.objects.create(
            user_id=free_user, name="B", status="active", priority="medium"
        )
        _make_tasks(free_user, 19, project=p1, done=False)
        _make_tasks(free_user, 19, project=p2, done=False)
        # p2 still under its 20 cap
        check_entity_quota(free_user, "tasks_per_project", project_id=p2.id)


class TestRoutineQuota:
    @pytest.mark.django_db
    def test_archived_dont_count(self, free_user):
        for i in range(5):
            Routine.objects.create(
                user_id=free_user,
                title=f"R{i}",
                recurrence_type="once",
                start_date="2026-01-01",
                archived=True,
            )
        check_entity_quota(free_user, "routines")  # cap=2, but 0 active

    @pytest.mark.django_db
    def test_active_count(self, free_user):
        Routine.objects.create(
            user_id=free_user,
            title="R1",
            recurrence_type="once",
            start_date="2026-01-01",
        )
        Routine.objects.create(
            user_id=free_user,
            title="R2",
            recurrence_type="once",
            start_date="2026-01-01",
        )
        with pytest.raises(EntityQuotaExceeded):
            check_entity_quota(free_user, "routines")


class TestIdeasAndCategoriesQuota:
    @pytest.mark.django_db
    def test_ideas_cap_30_for_free(self, free_user):
        for i in range(30):
            Idea.objects.create(user_id=free_user, title=f"I{i}")
        with pytest.raises(EntityQuotaExceeded) as exc:
            check_entity_quota(free_user, "ideas")
        assert exc.value.cap == 30

    @pytest.mark.django_db
    def test_categories_cap_3_for_free(self, free_user):
        for i in range(3):
            Category.objects.create(user_id=free_user, name=f"C{i}")
        with pytest.raises(EntityQuotaExceeded):
            check_entity_quota(free_user, "categories")


# ---------- Cross-kind blocking ----------


class TestCrossKindBlock:
    """If user is over any 'blocking' kind, ALL creation should fail —
    not just the kind they're trying to create. Forces cleanup before
    new content can be added (e.g., after a downgrade from Pro to Free)."""

    @pytest.mark.django_db
    def test_overage_in_projects_blocks_creating_a_task(self, free_user):
        _make_projects(free_user, 5)  # over the 3 cap
        project = Project.objects.first()
        with pytest.raises(EntityQuotaExceeded) as exc:
            check_entity_quota(
                free_user, "tasks_total"
            )  # would otherwise be fine, 0 tasks
        # The error reports the original overage kind, not the kind being created.
        assert exc.value.kind == "projects"

    @pytest.mark.django_db
    def test_overage_in_projects_blocks_creating_a_note(self, free_user):
        _make_projects(free_user, 5)
        project = Project.objects.first()
        with pytest.raises(EntityQuotaExceeded) as exc:
            check_entity_quota(
                free_user, "notes_per_project", project_id=project.id
            )
        assert exc.value.kind == "projects"

    @pytest.mark.django_db
    def test_overage_in_ideas_blocks_creating_a_project(self, free_user):
        for i in range(31):
            Idea.objects.create(user_id=free_user, title=f"I{i}")
        with pytest.raises(EntityQuotaExceeded) as exc:
            check_entity_quota(free_user, "projects")
        assert exc.value.kind == "ideas"

    @pytest.mark.django_db
    def test_no_block_when_under_caps(self, free_user):
        _make_projects(free_user, 2)
        _make_tasks(free_user, 10)
        for i in range(5):
            Idea.objects.create(user_id=free_user, title=f"I{i}")
        # Under every cap → all creates succeed
        check_entity_quota(free_user, "projects")
        check_entity_quota(free_user, "tasks_total")
        check_entity_quota(free_user, "ideas")

    @pytest.mark.django_db
    def test_studio_no_cross_block(self, studio_user):
        # Studio has all caps unlimited; cross-block must be a no-op
        _make_projects(studio_user, 100)
        check_entity_quota(studio_user, "tasks_total")
        check_entity_quota(studio_user, "ideas")


# ---------- Plan-specific quota dict sanity ----------


class TestQuotaTable:
    """Light contract checks on ENTITY_QUOTAS so a typo in the table
    fails immediately instead of breaking limits silently."""

    def test_every_kind_has_every_plan(self):
        plans = {"free", "pro", "studio", "admin"}
        for kind, caps in ENTITY_QUOTAS.items():
            assert plans.issubset(set(caps.keys())), (
                f"{kind} missing plans: {plans - set(caps.keys())}"
            )

    def test_studio_and_admin_unlimited(self):
        for kind, caps in ENTITY_QUOTAS.items():
            assert caps["studio"] is None, f"{kind} studio not unlimited"
            assert caps["admin"] is None, f"{kind} admin not unlimited"

    def test_free_strictly_lower_than_pro(self):
        for kind, caps in ENTITY_QUOTAS.items():
            free = caps["free"]
            pro = caps["pro"]
            if free is None or pro is None:
                continue
            assert free <= pro, f"{kind}: free({free}) > pro({pro})"

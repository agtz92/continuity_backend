"""Entity quotas (projects, tasks, routines, ideas, categories, notes).

The assistant has its own usage quotas in `core.assistant.quotas` (daily
messages, monthly tokens, deep model cap). This module covers the *entity
counts* a user can own under their plan.

Both create-via-GraphQL and create-via-assistant-tools go through the
service-layer `create_*` helpers, so calling `check_entity_quota()` at the
top of each helper covers both paths in one shot.

`None` in a cap entry means unlimited.
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.db.models import Q

from .assistant.models import AccountProfile, Plan
from .models import (
    Category,
    Idea,
    NoteSection,
    Project,
    ProjectNote,
    QuickNote,
    Routine,
    Task,
)


# kind -> {plan -> cap (int or None for unlimited)}
ENTITY_QUOTAS: dict[str, dict[str, Optional[int]]] = {
    "projects": {
        Plan.FREE.value: 3,
        Plan.PRO.value: 25,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
    "tasks_per_project": {
        Plan.FREE.value: 20,
        Plan.PRO.value: 200,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
    "tasks_total": {
        Plan.FREE.value: 50,
        Plan.PRO.value: None,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
    "routines": {
        Plan.FREE.value: 2,
        Plan.PRO.value: 20,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
    "ideas": {
        Plan.FREE.value: 30,
        Plan.PRO.value: 500,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
    "categories": {
        Plan.FREE.value: 3,
        Plan.PRO.value: 15,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
    "notes_per_project": {
        Plan.FREE.value: 3,
        Plan.PRO.value: None,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
    "quick_notes": {
        Plan.FREE.value: 50,
        Plan.PRO.value: 1000,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
    "sections_per_note": {
        Plan.FREE.value: 20,
        Plan.PRO.value: None,
        Plan.STUDIO.value: None,
        Plan.ADMIN.value: None,
    },
}


class EntityQuotaExceeded(Exception):
    """Raised when a create_* operation would exceed the user's plan cap.

    The schema layer catches this and re-raises as a GraphQL error with
    extensions={"code": "QUOTA_EXCEEDED", ...} so the frontend can render
    an upgrade CTA.
    """

    def __init__(self, kind: str, current: int, cap: int, plan: str):
        super().__init__(
            f"Quota exceeded for '{kind}': {current}/{cap} on plan '{plan}'"
        )
        self.kind = kind
        self.current = current
        self.cap = cap
        self.plan = plan


def effective_plan(profile: AccountProfile) -> str:
    """The plan used for gating decisions.

    Today this just returns `profile.plan` — `is_billing_exempt` is
    intentionally orthogonal (plan dictates features, exempt dictates
    Stripe billing). Centralized so future logic (e.g. trial overrides)
    has one place to live.
    """
    return profile.plan


def _get_plan(user_id: uuid.UUID) -> str:
    profile = AccountProfile.objects.filter(user_id=user_id).only("plan").first()
    if profile is None:
        return Plan.FREE.value
    return effective_plan(profile)


def _count(kind: str, user_id: uuid.UUID, project_id: Optional[uuid.UUID]) -> int:
    if kind == "projects":
        # Terminal states (archived + killed) don't count toward the cap (D3).
        return (
            Project.objects.filter(user_id=user_id)
            .exclude(status__in=["archived", "killed"])
            .count()
        )
    if kind == "tasks_total":
        return Task.objects.filter(user_id=user_id, done=False).count()
    if kind == "tasks_per_project":
        if project_id is None:
            return 0
        return Task.objects.filter(
            user_id=user_id, project_id=project_id, done=False
        ).count()
    if kind == "routines":
        return Routine.objects.filter(user_id=user_id, archived=False).count()
    if kind == "ideas":
        return Idea.objects.filter(user_id=user_id).count()
    if kind == "categories":
        return Category.objects.filter(user_id=user_id).count()
    if kind == "notes_per_project":
        if project_id is None:
            return 0
        return ProjectNote.objects.filter(
            user_id=user_id, project_id=project_id
        ).count()
    if kind == "quick_notes":
        return QuickNote.objects.filter(user_id=user_id).count()
    if kind == "sections_per_note":
        # `project_id` carries the parent note id for this per-parent kind.
        if project_id is None:
            return 0
        return NoteSection.objects.filter(
            user_id=user_id, note_id=project_id
        ).count()
    raise ValueError(f"Unknown quota kind: {kind}")


# Kinds that, when exceeded, block ALL creation across the app — not just
# the kind itself. Rationale: if a user lands on Free with 40 projects from
# a paid trial, they shouldn't be able to keep adding tasks/ideas/notes to
# those projects and effectively get Pro behavior on the Free plan. They
# must archive down to the cap first, then resume creating.
_BLOCKING_KINDS = ["projects", "tasks_total", "routines", "ideas", "categories"]


def check_entity_quota(
    user_id: uuid.UUID,
    kind: str,
    project_id: Optional[uuid.UUID] = None,
) -> None:
    """Raise EntityQuotaExceeded if creating one more would exceed the cap.

    Two layers of checks:

    1. If the user is already over ANY blocking-kind cap, refuse creation
       (no matter what they're trying to create) so they're forced to
       clean up.
    2. If the kind being created would exceed its own cap, refuse.

    Call this at the top of every `create_*` service function. A cap of
    `None` means unlimited — return immediately without counting.
    """
    plan = _get_plan(user_id)

    # Layer 1: block on any other-kind overage.
    for other in _BLOCKING_KINDS:
        if other == kind:
            continue  # The kind being created is checked below by its own logic
        other_cap = ENTITY_QUOTAS.get(other, {}).get(plan)
        if other_cap is None:
            continue
        other_current = _count(other, user_id, project_id=None)
        if other_current > other_cap:
            raise EntityQuotaExceeded(
                kind=other, current=other_current, cap=other_cap, plan=plan
            )

    # Layer 2: this kind exceeds its own cap.
    cap = ENTITY_QUOTAS.get(kind, {}).get(plan)
    if cap is None:
        return
    current = _count(kind, user_id, project_id)
    if current >= cap:
        raise EntityQuotaExceeded(kind=kind, current=current, cap=cap, plan=plan)

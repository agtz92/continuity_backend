"""The mutations that advance onboarding actually run.

Every one of these was broken in production and no test noticed: after
`schema.py` was split, they still called `Query().onboarding_state(info)`,
and `Query` lives in `schema.py` — it was never in `schema_mutations.py`'s
namespace. Python only raises `NameError` when the line executes, so the
schema built fine, the whole suite stayed green, and the flow failed for
every new account.

These tests exercise the mutations end to end for exactly that reason: a
resolver that is never called is a resolver that is never checked.
"""

from __future__ import annotations

import uuid

import pytest

from core.schema import schema


class _Ctx:
    """Minimal context: the resolvers only read `user_id`."""

    def __init__(self, uid: uuid.UUID):
        self.user_id = str(uid)
        self.request = None


@pytest.fixture
def uid() -> uuid.UUID:
    return uuid.uuid4()


FIELDS = "status currentStep tourStatus plan isBillingExempt"


def _run(query: str, uid: uuid.UUID, **variables):
    result = schema.execute_sync(
        query, context_value=_Ctx(uid), variable_values=variables or None
    )
    assert result.errors is None, result.errors
    return result.data


@pytest.mark.django_db
class TestOnboardingMutations:
    def test_set_step_returns_the_state(self, uid):
        data = _run(
            f"mutation($s: Int!) {{ setOnboardingStep(step: $s) {{ {FIELDS} }} }}",
            uid,
            s=3,
        )
        assert data["setOnboardingStep"]["currentStep"] == 3

    def test_complete_returns_the_state(self, uid):
        data = _run(
            f"mutation {{ completeOnboarding(mode: \"finished\") {{ {FIELDS} }} }}",
            uid,
        )
        assert data["completeOnboarding"]["status"] == "completed"

    def test_skip_returns_the_state(self, uid):
        """"Skip setup" is a `completeOnboarding` with another mode."""
        data = _run(
            f"mutation {{ completeOnboarding(mode: \"skipped\") {{ {FIELDS} }} }}",
            uid,
        )
        assert data["completeOnboarding"]["status"] == "skipped"

    def test_mark_tour_returns_the_state(self, uid):
        data = _run(
            f"mutation {{ markTour(seen: true) {{ {FIELDS} }} }}", uid
        )
        assert data["markTour"]["tourStatus"]

    def test_query_and_mutation_agree(self, uid):
        """Both paths build the snapshot the same way — that's the point of
        sharing `build_onboarding_state` instead of duplicating it."""
        mutated = _run(
            f"mutation($s: Int!) {{ setOnboardingStep(step: $s) {{ {FIELDS} }} }}",
            uid,
            s=2,
        )["setOnboardingStep"]
        queried = _run(f"{{ onboardingState {{ {FIELDS} }} }}", uid)[
            "onboardingState"
        ]
        assert mutated == queried

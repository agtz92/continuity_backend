"""The public flag that keeps the landing and the signup gate in sync.

The failure this prevents is a landing that advertises beta spots while
`_apply_enrollment_decision` refuses to grant them, so the cases worth
covering are the ones where the two could disagree.
"""

from __future__ import annotations

import json
import uuid

import pytest

from core.assistant.models import AccountProfile, BetaStatus
from core.services import app_config

QUERY = """
{ publicBetaProgram { enrollmentOpen spotsLeft } }
"""


def _ask(client):
    res = client.post(
        "/public-graphql/",
        data=json.dumps({"query": QUERY}),
        content_type="application/json",
    )
    assert res.status_code == 200, res.content
    return res.json()["data"]["publicBetaProgram"]


def _beta_users(n: int) -> None:
    for _ in range(n):
        AccountProfile.objects.create(
            user_id=uuid.uuid4(),
            beta_cohort=True,
            beta_status=BetaStatus.ACTIVE,
        )


@pytest.mark.django_db
class TestPublicBetaProgram:
    def test_needs_no_auth(self, client):
        """The landing is static and anonymous; this has to answer without a JWT."""
        app_config.set("beta_enrollment_open", True)
        app_config.set("beta_spot_cap", 10)

        res = client.post(
            "/public-graphql/",
            data=json.dumps({"query": QUERY}),
            content_type="application/json",
        )

        assert res.status_code == 200
        assert "errors" not in res.json()

    def test_open_reports_remaining_spots(self, client):
        app_config.set("beta_enrollment_open", True)
        app_config.set("beta_spot_cap", 50)
        _beta_users(3)

        assert _ask(client) == {"enrollmentOpen": True, "spotsLeft": 47}

    def test_full_cohort_closes_the_site_even_while_open(self, client):
        """A full cohort has to close the messaging on its own.

        Otherwise the landing keeps offering spots until someone remembers
        to flip the switch — and signup silently declines every one of them.
        """
        app_config.set("beta_enrollment_open", True)
        app_config.set("beta_spot_cap", 2)
        _beta_users(2)

        assert _ask(client) == {"enrollmentOpen": False, "spotsLeft": 0}

    def test_closed_reports_no_spots_whatever_the_cap(self, client):
        app_config.set("beta_enrollment_open", False)
        app_config.set("beta_spot_cap", 50)

        assert _ask(client) == {"enrollmentOpen": False, "spotsLeft": 0}

    def test_reclaimed_spots_do_not_count_against_the_cap(self, client):
        """Only ACTIVE members occupy a spot, same rule as the signup path."""
        app_config.set("beta_enrollment_open", True)
        app_config.set("beta_spot_cap", 5)
        _beta_users(2)
        AccountProfile.objects.create(
            user_id=uuid.uuid4(),
            beta_cohort=True,
            beta_status=BetaStatus.RECLAIMED,
        )

        assert _ask(client)["spotsLeft"] == 3

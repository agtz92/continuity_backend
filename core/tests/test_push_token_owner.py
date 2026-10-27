"""A push token belongs to the last account that registered it on the device."""

from __future__ import annotations

import pytest

from core.notifications.models import ExpoPushToken

REGISTER = """
mutation R($t: String!, $d: String!) { registerPushToken(token: $t, deviceId: $d) }
"""


@pytest.mark.django_db
def test_registering_a_token_takes_it_from_the_previous_account(execute_query, user_a, user_b):
    token = "ExponentPushToken[same-phone]"
    assert not execute_query(REGISTER, user_a, {"t": token, "d": "dev-a"}).errors
    # A signed out without unregistering (expired session); B signs in on the same phone.
    assert not execute_query(REGISTER, user_b, {"t": token, "d": "dev-b"}).errors

    owners = list(ExpoPushToken.objects.filter(token=token).values_list("user_id", flat=True))
    assert owners == [user_b]

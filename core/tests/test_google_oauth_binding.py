"""Google OAuth (Tasks/Calendar): a consent link can't connect someone else's Google.

Before 2026-11-05 the unauthenticated callback stored tokens under the uid in
``state``. User B could send B's own consent link to A; when A approved, A's
Google refresh token landed on B's account. Now the callback only hands
code+state to the frontend, and ``completeGoogleOauth`` exchanges the code
only for the logged-in user the state was issued to.
"""

from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client
from django.utils import timezone

from core.models import GoogleOAuthCredential
from core.services import google_tasks as gt

pytestmark = pytest.mark.django_db

COMPLETE = "mutation($c: String!, $s: String!){ completeGoogleOauth(code: $c, state: $s) }"


@pytest.fixture(autouse=True)
def _google_settings(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = "test-client"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "test-secret"
    settings.GOOGLE_OAUTH_REDIRECT_URI = "https://api.test/api/google/oauth/callback"
    settings.GOOGLE_OAUTH_FRONTEND_BASE_URL = "https://app.test"


@pytest.fixture
def fake_google():
    """Stand-in for Google's token endpoint; records whether a code was exchanged."""
    flow = mock.Mock()
    flow.credentials = SimpleNamespace(
        refresh_token="victim-refresh-token",
        token="victim-access-token",
        expiry=None,
        scopes=gt.SCOPES,
    )
    with mock.patch.object(gt, "_flow", return_value=flow), mock.patch.object(
        gt, "_fetch_email", return_value="victim@gmail.com"
    ):
        yield flow


def _state_for(user_id, ret="/settings/plugins/google-tasks"):
    return gt._sign_state(
        {"uid": str(user_id), "ret": ret, "iat": int(timezone.now().timestamp())}
    )


# ---------- the attack ----------

def test_shared_consent_link_does_not_capture_victims_google(
    execute_query, user_a, user_b, fake_google
):
    attacker_state = _state_for(user_b)  # B started the flow...

    # ...A approves on Google, the callback bounces to the app...
    res = Client().get(
        "/api/google/oauth/callback", {"code": "victim-code", "state": attacker_state}
    )
    assert res.status_code == 302
    assert not GoogleOAuthCredential.objects.exists()  # callback stores nothing
    fake_google.fetch_token.assert_not_called()

    # ...and A's logged-in page tries to finish it.
    r = execute_query(COMPLETE, user_a, {"c": "victim-code", "s": attacker_state})

    assert r.errors and r.errors[0].extensions["code"] == "INVALID_OAUTH_STATE"
    fake_google.fetch_token.assert_not_called()  # the code is never spent
    assert not GoogleOAuthCredential.objects.filter(user_id=user_b).exists()
    assert not GoogleOAuthCredential.objects.exists()


def test_owner_completes_own_flow(execute_query, user_a, fake_google):
    state = _state_for(user_a)
    r = execute_query(COMPLETE, user_a, {"c": "good-code", "s": state})
    assert r.errors is None
    assert r.data["completeGoogleOauth"] is True
    fake_google.fetch_token.assert_called_once_with(code="good-code")
    cred = GoogleOAuthCredential.objects.get(user_id=user_a)
    assert cred.email == "victim@gmail.com"
    assert gt._decrypt(cred.refresh_token) == "victim-refresh-token"


def test_complete_requires_login(execute_query, user_a, fake_google):
    r = execute_query(COMPLETE, None, {"c": "x", "s": _state_for(user_a)})
    assert r.errors
    fake_google.fetch_token.assert_not_called()


# ---------- the callback hand-off ----------

def test_callback_hands_code_and_state_to_frontend(user_a, fake_google):
    state = _state_for(user_a)
    res = Client().get("/api/google/oauth/callback", {"code": "abc", "state": state})
    target = urlparse(res["Location"])
    assert f"{target.scheme}://{target.netloc}" == "https://app.test"
    assert target.path == "/settings/plugins/google-tasks"
    qs = parse_qs(target.query)
    assert qs["google_code"] == ["abc"] and qs["google_state"] == [state]


def test_callback_rejects_forged_state(fake_google):
    forged = _state_for("00000000-0000-0000-0000-000000000000")[:-4] + "AAAA"
    res = Client().get("/api/google/oauth/callback", {"code": "abc", "state": forged})
    assert res.status_code == 400


def test_callback_rejects_expired_state(user_a, fake_google):
    old = gt._sign_state(
        {"uid": str(user_a), "ret": "/x", "iat": int(timezone.now().timestamp()) - 3600}
    )
    res = Client().get("/api/google/oauth/callback", {"code": "abc", "state": old})
    assert res.status_code == 400


@pytest.mark.parametrize("ret", ["//evil.test/phish", "https://evil.test", "evil"])
def test_callback_never_redirects_off_site(user_a, ret, fake_google):
    res = Client().get(
        "/api/google/oauth/callback", {"code": "abc", "state": _state_for(user_a, ret)}
    )
    assert res["Location"].startswith("https://app.test/settings/plugins/google-tasks?")

from django.test import Client

from core.security_headers import ADMIN_POLICY, API_POLICY


def test_api_responses_get_strict_csp():
    resp = Client().get("/healthz")
    assert resp.status_code == 200
    assert resp["Content-Security-Policy"] == API_POLICY
    assert "frame-ancestors 'none'" in API_POLICY


def test_admin_gets_policy_that_allows_its_static_files():
    resp = Client().get("/admin/login/")
    assert resp["Content-Security-Policy"] == ADMIN_POLICY


def test_unsubscribe_page_keeps_inline_style_and_self_post():
    resp = Client().get("/email/unsubscribe/?t=bogus")
    csp = resp["Content-Security-Policy"]
    assert "style-src 'unsafe-inline'" in csp
    assert "form-action 'self'" in csp

"""Where each kind of subscriber gets sent to manage their plan.

The point of resolving this on the server is that web and mobile agree, so
the cases that matter are the ones where the two clients would otherwise have
drifted: a store purchase seen from the web, and a web purchase seen from the
phone.
"""

from __future__ import annotations

import uuid

import pytest

from core.assistant.models import AccountProfile, BillingSource, Plan
from core.billing.manage import manage_url_for


def _profile(**kwargs) -> AccountProfile:
    return AccountProfile(user_id=uuid.uuid4(), **kwargs)


class TestManageUrl:
    def test_apple_goes_to_the_app_store(self):
        p = _profile(plan=Plan.PRO.value, billing_source=BillingSource.APPLE.value)
        assert manage_url_for(p) == "https://apps.apple.com/account/subscriptions"

    def test_google_goes_to_play(self):
        p = _profile(plan=Plan.PRO.value, billing_source=BillingSource.GOOGLE.value)
        url = manage_url_for(p)
        assert url == "https://play.google.com/store/account/subscriptions"

    def test_store_urls_are_https_so_both_clients_can_open_them(self):
        """One string has to work in a browser and in a native app."""
        for source in (BillingSource.APPLE.value, BillingSource.GOOGLE.value):
            assert manage_url_for(_profile(billing_source=source)).startswith("https://")

    def test_web_goes_to_our_billing_page(self, settings):
        """The portal link is per-subscription; only the page's SDK can get it."""
        settings.BILLING_FRONTEND_BASE_URL = "https://continuu.it"
        p = _profile(plan=Plan.PRO.value, billing_source=BillingSource.WEB.value)
        assert manage_url_for(p) == "https://continuu.it/settings/billing"

    def test_web_base_url_trailing_slash_does_not_double_up(self, settings):
        settings.BILLING_FRONTEND_BASE_URL = "https://continuu.it/"
        p = _profile(billing_source=BillingSource.WEB.value)
        assert manage_url_for(p) == "https://continuu.it/settings/billing"

    def test_free_account_has_nothing_to_manage(self):
        assert manage_url_for(_profile(plan=Plan.FREE.value)) is None

    def test_exempt_account_has_nothing_to_manage(self):
        """A courtesy plan is not a subscription — an inert button is worse."""
        p = _profile(
            plan=Plan.PRO.value,
            billing_source=BillingSource.WEB.value,
            is_billing_exempt=True,
        )
        assert manage_url_for(p) is None

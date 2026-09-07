"""Where to send a subscriber to manage their plan.

One function, because the answer depends on who sold the plan and we did not
want that branch living in both clients. `/usage/` exposes it as `manage_url`.

**This resolves the destination, not the final link.** For the stores that is
the same thing — their subscription managers are fixed URLs. For the web it
is not: RevenueCat's customer portal link is per subscription, and the only
ways to get it are the Web SDK's `CustomerInfo.managementUrl` or a server call
to RevenueCat's API with a secret key. We hold no such integration on purpose
(the backend only ever *receives* from RevenueCat), so web subscribers are
sent to our own billing page, which owns the SDK and does that last hop.

That is a deliberate deviation from `docs/pagos-unificados/PLAN.md` §A6, which
assumed the server could hand back the portal URL directly.
"""

from __future__ import annotations

from django.conf import settings

from core.assistant.models import AccountProfile, BillingSource


#: Apple's and Google's subscription managers. The `https` forms are used
#: rather than `itms-apps://` and friends because one string has to work in a
#: browser and in a native app: on a phone these open the store's own screen,
#: and on a desktop they open the web equivalent. A custom scheme would just
#: fail to resolve on the web.
_STORE_MANAGE_URLS = {
    BillingSource.APPLE.value: "https://apps.apple.com/account/subscriptions",
    BillingSource.GOOGLE.value: "https://play.google.com/store/account/subscriptions",
}


def manage_url_for(profile: AccountProfile) -> str | None:
    """Where this person changes or cancels their plan, or None if nowhere.

    None means there is nothing to manage: free accounts, and billing-exempt
    ones whose plan is a courtesy rather than a subscription. Clients should
    show no management affordance at all in that case — an inert button is
    worse than no button.
    """
    source = profile.billing_source or ""
    if not source or profile.is_billing_exempt:
        return None

    store_url = _STORE_MANAGE_URLS.get(source)
    if store_url:
        return store_url

    # Web: our own billing page finishes the job with the SDK.
    base = (getattr(settings, "BILLING_FRONTEND_BASE_URL", "") or "").rstrip("/")
    return f"{base}/settings/billing" if base else None

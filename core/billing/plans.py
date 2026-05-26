"""Mapping between our Plan enum and Stripe price IDs."""

from __future__ import annotations

from django.conf import settings

from core.assistant.models import Plan


# (plan, billing_period) -> Stripe price id env value
def price_id_for(plan: str, period: str) -> str | None:
    """Returns the Stripe price id, or None if unconfigured.

    period is "monthly" or "annual".
    """
    key = {
        (Plan.PRO.value, "monthly"): "STRIPE_PRICE_PRO_MONTHLY",
        (Plan.PRO.value, "annual"): "STRIPE_PRICE_PRO_ANNUAL",
        (Plan.STUDIO.value, "monthly"): "STRIPE_PRICE_STUDIO_MONTHLY",
        (Plan.STUDIO.value, "annual"): "STRIPE_PRICE_STUDIO_ANNUAL",
    }.get((plan, period))
    if not key:
        return None
    val = getattr(settings, key, "")
    return val or None


def plan_for_price(price_id: str) -> str | None:
    """Reverse mapping: given a price id, infer which plan it represents.

    Used in webhook handlers when Stripe tells us a subscription's price.
    """
    mapping = {
        getattr(settings, "STRIPE_PRICE_PRO_MONTHLY", ""): Plan.PRO.value,
        getattr(settings, "STRIPE_PRICE_PRO_ANNUAL", ""): Plan.PRO.value,
        getattr(settings, "STRIPE_PRICE_STUDIO_MONTHLY", ""): Plan.STUDIO.value,
        getattr(settings, "STRIPE_PRICE_STUDIO_ANNUAL", ""): Plan.STUDIO.value,
    }
    return mapping.get(price_id)


def period_for_price(price_id: str) -> str | None:
    """Reverse mapping: given a price id, infer the billing period.

    Returns "monthly" or "annual", or None if the id doesn't match any
    configured price.
    """
    if not price_id:
        return None
    if price_id == getattr(settings, "STRIPE_PRICE_PRO_MONTHLY", ""):
        return "monthly"
    if price_id == getattr(settings, "STRIPE_PRICE_PRO_ANNUAL", ""):
        return "annual"
    if price_id == getattr(settings, "STRIPE_PRICE_STUDIO_MONTHLY", ""):
        return "monthly"
    if price_id == getattr(settings, "STRIPE_PRICE_STUDIO_ANNUAL", ""):
        return "annual"
    return None


def amount_cents_for_price(price_id: str) -> int:
    """Returns the configured monetary amount (cents) for a price id.

    Reads from Django settings (STRIPE_PRICE_*_AMOUNT_CENTS). Returns 0
    when the price id is unknown or the amount is unconfigured — callers
    should treat 0 as "no estimate available" and skip it in MRR math.
    """
    if not price_id:
        return 0
    mapping = {
        getattr(settings, "STRIPE_PRICE_PRO_MONTHLY", ""): "STRIPE_PRICE_PRO_MONTHLY_AMOUNT_CENTS",
        getattr(settings, "STRIPE_PRICE_PRO_ANNUAL", ""): "STRIPE_PRICE_PRO_ANNUAL_AMOUNT_CENTS",
        getattr(settings, "STRIPE_PRICE_STUDIO_MONTHLY", ""): "STRIPE_PRICE_STUDIO_MONTHLY_AMOUNT_CENTS",
        getattr(settings, "STRIPE_PRICE_STUDIO_ANNUAL", ""): "STRIPE_PRICE_STUDIO_ANNUAL_AMOUNT_CENTS",
    }
    key = mapping.get(price_id)
    if not key:
        return 0
    return int(getattr(settings, key, 0) or 0)


def monthly_cents_for_price(price_id: str) -> int:
    """Normalizes any price to its monthly-equivalent cents (annual ÷ 12)."""
    amount = amount_cents_for_price(price_id)
    if amount <= 0:
        return 0
    if period_for_price(price_id) == "annual":
        return amount // 12
    return amount


def is_stripe_test_mode() -> bool:
    """Detect test vs live mode from the secret key prefix.

    Used by the admin UI to build the right dashboard.stripe.com deep links
    (test mode urls include `/test/`). Returns False when no key is set.
    """
    key = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    return key.startswith("sk_test_")

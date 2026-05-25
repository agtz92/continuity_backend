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

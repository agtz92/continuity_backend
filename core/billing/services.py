"""Stripe checkout / portal / sync / retention services.

`create_checkout_session` and `create_portal_session` are called by
GraphQL mutations from the frontend. `sync_subscription_to_profile` is
called by the webhook handler when Stripe tells us a subscription state
changed. `apply_retention_coupon`, `cancel_subscription`, and
`downgrade_subscription` power the in-app cancellation/retention flow.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from django.conf import settings

from core.admin_api.audit import record as audit_record
from core.assistant.models import AccountProfile, Plan

from .plans import plan_for_price, price_id_for
from .stripe_client import get_stripe


logger = logging.getLogger(__name__)


class BillingConfigError(Exception):
    """Raised when Stripe is not configured for the requested operation."""


class NoActiveSubscriptionError(Exception):
    """Raised when an operation requires a live subscription and there isn't one."""


class RetentionAlreadyUsedError(Exception):
    """Raised when a user tries to claim a second retention offer."""


def _frontend_url(path: str) -> str:
    base = getattr(settings, "BILLING_FRONTEND_BASE_URL", "http://localhost:3000")
    return f"{base.rstrip('/')}{path}"


def _ensure_customer(profile: AccountProfile, email: str | None = None) -> str:
    """Return the Stripe customer id for this profile, creating one if needed."""
    if profile.stripe_customer_id:
        return profile.stripe_customer_id
    stripe = get_stripe()
    customer = stripe.Customer.create(
        email=email or None,
        metadata={"user_id": str(profile.user_id)},
    )
    profile.stripe_customer_id = customer["id"]
    profile.save(update_fields=["stripe_customer_id", "updated_at"])
    return customer["id"]


# Stripe `locale` parameter accepts a specific set of values. We normalize
# whatever the frontend sends to the closest supported one and fall back to
# "auto" (Stripe infers from browser) when we have nothing useful.
_STRIPE_SUPPORTED_LOCALES = {
    "auto", "bg", "cs", "da", "de", "el", "en", "en-GB", "es", "es-419",
    "et", "fi", "fil", "fr", "fr-CA", "hr", "hu", "id", "it", "ja", "ko",
    "lt", "lv", "ms", "mt", "nb", "nl", "pl", "pt", "pt-BR", "ro", "ru",
    "sk", "sl", "sv", "th", "tr", "vi", "zh", "zh-HK", "zh-TW",
}


def _normalize_locale(locale: str | None) -> str:
    if not locale:
        return "auto"
    raw = locale.strip()
    if raw in _STRIPE_SUPPORTED_LOCALES:
        return raw
    # Try the base language (e.g. "es-MX" -> "es")
    base = raw.split("-", 1)[0]
    if base in _STRIPE_SUPPORTED_LOCALES:
        return base
    return "auto"


def create_checkout_session(
    user_id: uuid.UUID,
    *,
    plan: str,
    period: str,
    email: str | None = None,
    locale: str | None = None,
) -> str:
    """Create a Stripe Checkout session for the given plan/period.

    Returns the hosted checkout URL.
    """
    if plan not in {Plan.PRO.value, Plan.STUDIO.value}:
        raise BillingConfigError(f"Plan '{plan}' is not purchasable")
    if period not in {"monthly", "annual"}:
        raise BillingConfigError(f"Period '{period}' is invalid")

    price = price_id_for(plan, period)
    if not price:
        raise BillingConfigError(
            f"Stripe price id missing for plan={plan}, period={period}"
        )

    profile, _ = AccountProfile.objects.get_or_create(user_id=user_id)
    customer_id = _ensure_customer(profile, email=email)

    stripe = get_stripe()
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=str(user_id),
        line_items=[{"price": price, "quantity": 1}],
        success_url=_frontend_url("/settings/billing?status=success"),
        cancel_url=_frontend_url("/settings/billing?status=cancelled"),
        allow_promotion_codes=True,
        locale=_normalize_locale(locale),
        metadata={"user_id": str(user_id), "plan": plan, "period": period},
        subscription_data={
            "metadata": {"user_id": str(user_id), "plan": plan, "period": period},
        },
    )
    return session["url"]


def create_portal_session(user_id: uuid.UUID, *, locale: str | None = None) -> str:
    """Create a Stripe customer portal session for managing the subscription."""
    profile = AccountProfile.objects.filter(user_id=user_id).first()
    if profile is None or not profile.stripe_customer_id:
        raise BillingConfigError("No Stripe customer for this account")
    stripe = get_stripe()
    session = stripe.billing_portal.Session.create(
        customer=profile.stripe_customer_id,
        return_url=_frontend_url("/settings/billing"),
        locale=_normalize_locale(locale),
    )
    return session["url"]


def sync_subscription_to_profile(
    *,
    user_id: Optional[uuid.UUID],
    customer_id: Optional[str],
    subscription_id: str,
    price_id: str,
    status: str,
    current_period_end: Optional[int],
    cancel_at_period_end: bool = False,
) -> None:
    """Apply a Stripe subscription event to AccountProfile.

    Respects `is_billing_exempt`: exempt accounts are never downgraded,
    only logged. This protects staff-comp users from churn caused by
    stale subscription cleanup.
    """
    import datetime as dt

    profile = None
    if user_id is not None:
        profile = AccountProfile.objects.filter(user_id=user_id).first()
    if profile is None and customer_id:
        profile = AccountProfile.objects.filter(stripe_customer_id=customer_id).first()
    if profile is None:
        logger.warning(
            "sync_subscription_to_profile: no profile for user_id=%s customer_id=%s",
            user_id,
            customer_id,
        )
        return

    target_plan = plan_for_price(price_id) or Plan.FREE.value
    is_active = status in {"active", "trialing", "past_due"}
    is_terminal = status in {
        "canceled",
        "unpaid",
        "incomplete_expired",
    }
    # `incomplete` is intentionally NOT terminal — it's a checkout in
    # progress (or one that failed payment). Treating it as a downgrade
    # blows away the user's real subscription if they start a second
    # checkout while still on the first plan.

    # Only act when the event concerns the user's *current* subscription.
    # Events about a different (stale or in-flight) subscription must not
    # mutate the active plan — otherwise a failed upgrade checkout would
    # silently downgrade the user to free.
    is_current_sub = (
        not profile.stripe_subscription_id
        or profile.stripe_subscription_id == subscription_id
    )

    if not is_active:
        if not is_terminal:
            logger.info(
                "Ignoring non-terminal event for sub %s (status=%s)",
                subscription_id,
                status,
            )
            return
        if not is_current_sub:
            logger.info(
                "Ignoring terminal event for stale sub %s (active sub is %s)",
                subscription_id,
                profile.stripe_subscription_id,
            )
            return
        if profile.is_billing_exempt:
            logger.info(
                "Skipping downgrade for exempt user %s (subscription %s status=%s)",
                profile.user_id,
                subscription_id,
                status,
            )
            return
        profile.plan = Plan.FREE.value
        profile.stripe_subscription_id = ""
        profile.stripe_price_id = ""
        profile.plan_renews_at = None
        profile.cancel_at_period_end = False
        profile.save(
            update_fields=[
                "plan",
                "stripe_subscription_id",
                "stripe_price_id",
                "plan_renews_at",
                "cancel_at_period_end",
                "updated_at",
            ]
        )
        return

    profile.plan = target_plan
    profile.stripe_subscription_id = subscription_id
    profile.stripe_price_id = price_id or ""
    profile.cancel_at_period_end = cancel_at_period_end
    if current_period_end:
        profile.plan_renews_at = dt.datetime.fromtimestamp(
            current_period_end, tz=dt.timezone.utc
        )
    profile.save(
        update_fields=[
            "plan",
            "stripe_subscription_id",
            "stripe_price_id",
            "plan_renews_at",
            "cancel_at_period_end",
            "updated_at",
        ]
    )


# ---------- Retention / cancel / downgrade ----------


# Mapping of cancellation reason → retention coupon env var name.
# The coupon IDs come from Stripe Dashboard (Products → Coupons).
_REASON_TO_COUPON_ENV = {
    "too_expensive": "STRIPE_COUPON_RETENTION_30_3M",
    "not_used": "STRIPE_COUPON_RETENTION_25_3M",
    "missing_features": "STRIPE_COUPON_RETENTION_25_3M",
    "switching": "STRIPE_COUPON_RETENTION_20_3M",
    "trial_only": "STRIPE_COUPON_RETENTION_30_3M",
    "other": "STRIPE_COUPON_RETENTION_20_3M",
}


def coupon_for_reason(reason: str) -> Optional[str]:
    """Return the configured Stripe coupon id for the given cancel reason.

    None if no coupon is configured (env var empty or reason unknown).
    """
    env_name = _REASON_TO_COUPON_ENV.get(reason)
    if not env_name:
        return None
    val = getattr(settings, env_name, "")
    return val or None


def _require_active_sub(profile: AccountProfile) -> str:
    if not profile.stripe_subscription_id:
        raise NoActiveSubscriptionError(
            "This account has no active Stripe subscription"
        )
    return profile.stripe_subscription_id


def apply_retention_coupon(
    user_id: uuid.UUID,
    *,
    reason: str,
    feedback_text: str = "",
) -> dict:
    """Apply the retention coupon for the given reason to the user's sub.

    Returns a small dict with details for the frontend. Idempotent only in
    the sense that once `had_retention_offer=True`, subsequent calls raise.
    """
    profile = AccountProfile.objects.filter(user_id=user_id).first()
    if profile is None:
        raise NoActiveSubscriptionError("No profile for this user")
    if profile.had_retention_offer:
        raise RetentionAlreadyUsedError(
            "A retention offer has already been applied to this account"
        )
    sub_id = _require_active_sub(profile)
    coupon_id = coupon_for_reason(reason)
    if not coupon_id:
        raise BillingConfigError(
            f"No retention coupon configured for reason '{reason}'"
        )

    stripe = get_stripe()
    # Stripe applies the coupon as a discount on the next invoice(s).
    # `discounts=[{coupon: ...}]` replaces any existing discounts.
    stripe.Subscription.modify(
        sub_id,
        discounts=[{"coupon": coupon_id}],
    )

    profile.had_retention_offer = True
    profile.save(update_fields=["had_retention_offer", "updated_at"])

    audit_record(
        actor_user_id=user_id,
        action="billing.retention_offer_accepted",
        target_type="subscription",
        target_id=sub_id,
        payload={
            "reason": reason,
            "feedback_text": feedback_text,
            "coupon": coupon_id,
        },
    )
    return {"coupon": coupon_id, "subscription_id": sub_id}


def cancel_subscription(
    user_id: uuid.UUID,
    *,
    reason: str,
    feedback_text: str = "",
) -> dict:
    """Schedule the user's subscription to cancel at the end of the current
    billing period. Stripe will fire `customer.subscription.updated` with
    `cancel_at_period_end=True`, and `customer.subscription.deleted` once
    the period actually ends — at which point the webhook downgrades the
    profile to free.

    The audit log captures `reason` and `feedback_text` so we can analyze
    why people are leaving.
    """
    profile = AccountProfile.objects.filter(user_id=user_id).first()
    if profile is None:
        raise NoActiveSubscriptionError("No profile for this user")
    sub_id = _require_active_sub(profile)

    stripe = get_stripe()
    sub = stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
    period_end = sub.get("current_period_end")

    # Reflect immediately so the UI shows "cancellation scheduled" without
    # waiting on the webhook.
    profile.cancel_at_period_end = True
    profile.save(update_fields=["cancel_at_period_end", "updated_at"])

    audit_record(
        actor_user_id=user_id,
        action="billing.subscription_cancelled",
        target_type="subscription",
        target_id=sub_id,
        payload={
            "reason": reason,
            "feedback_text": feedback_text,
            "current_period_end": period_end,
            "from_plan": profile.plan,
        },
    )
    return {
        "subscription_id": sub_id,
        "current_period_end": period_end,
    }


def reactivate_subscription(user_id: uuid.UUID) -> dict:
    """Undo a `cancel_at_period_end` schedule. The user keeps their plan
    and Stripe will charge as normal at the next renewal."""
    profile = AccountProfile.objects.filter(user_id=user_id).first()
    if profile is None:
        raise NoActiveSubscriptionError("No profile for this user")
    sub_id = _require_active_sub(profile)

    stripe = get_stripe()
    stripe.Subscription.modify(sub_id, cancel_at_period_end=False)

    profile.cancel_at_period_end = False
    profile.save(update_fields=["cancel_at_period_end", "updated_at"])

    audit_record(
        actor_user_id=user_id,
        action="billing.subscription_reactivated",
        target_type="subscription",
        target_id=sub_id,
        payload={"plan": profile.plan},
    )
    return {"subscription_id": sub_id}


def downgrade_subscription(
    user_id: uuid.UUID,
    *,
    target_plan: str,
    period: str = "monthly",
) -> dict:
    """Switch the user's subscription to a cheaper plan, prorating immediately.

    Used by the retention flow when a Studio user picks "downgrade to Pro
    instead of cancelling". Same Stripe primitive as the portal's switch-plan.
    """
    profile = AccountProfile.objects.filter(user_id=user_id).first()
    if profile is None:
        raise NoActiveSubscriptionError("No profile for this user")
    sub_id = _require_active_sub(profile)

    new_price = price_id_for(target_plan, period)
    if not new_price:
        raise BillingConfigError(
            f"No Stripe price configured for {target_plan}/{period}"
        )

    stripe = get_stripe()
    sub = stripe.Subscription.retrieve(sub_id)
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        raise NoActiveSubscriptionError("Subscription has no items")
    item_id = items[0]["id"]
    from_plan = profile.plan

    stripe.Subscription.modify(
        sub_id,
        items=[{"id": item_id, "price": new_price}],
        proration_behavior="create_prorations",
    )

    # Reflect the change locally so the UI updates instantly. The webhook
    # `customer.subscription.updated` will arrive shortly after and confirm.
    profile.plan = target_plan
    profile.stripe_price_id = new_price
    profile.save(
        update_fields=["plan", "stripe_price_id", "updated_at"]
    )

    audit_record(
        actor_user_id=user_id,
        action="billing.subscription_downgraded",
        target_type="subscription",
        target_id=sub_id,
        payload={
            "from_plan": from_plan,
            "to_plan": target_plan,
            "period": period,
        },
    )
    return {
        "subscription_id": sub_id,
        "from_plan": from_plan,
        "to_plan": target_plan,
    }

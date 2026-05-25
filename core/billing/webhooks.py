"""Stripe webhook receiver.

Configure the webhook endpoint in Stripe Dashboard pointing to
`/api/billing/webhook/` and copy the signing secret to STRIPE_WEBHOOK_SECRET.

Handled events:
- checkout.session.completed
- customer.subscription.updated
- customer.subscription.deleted
"""

from __future__ import annotations

import json
import logging
import uuid

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import sync_subscription_to_profile
from .stripe_client import get_stripe


logger = logging.getLogger(__name__)


def _user_id_from_metadata(obj: dict) -> uuid.UUID | None:
    md = obj.get("metadata") or {}
    raw = md.get("user_id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        return None


def _handle_checkout_completed(session: dict) -> None:
    """Initial subscription created — full sync from the subscription object."""
    subscription_id = session.get("subscription")
    if not subscription_id:
        return
    stripe = get_stripe()
    sub = stripe.Subscription.retrieve(subscription_id)
    _handle_subscription_event(sub)


def _handle_subscription_event(sub: dict) -> None:
    items = (sub.get("items") or {}).get("data") or []
    price_id = items[0]["price"]["id"] if items else ""
    user_id = _user_id_from_metadata(sub)
    sync_subscription_to_profile(
        user_id=user_id,
        customer_id=sub.get("customer"),
        subscription_id=sub.get("id", ""),
        price_id=price_id,
        status=sub.get("status", ""),
        current_period_end=sub.get("current_period_end"),
        cancel_at_period_end=bool(sub.get("cancel_at_period_end")),
    )


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return HttpResponseBadRequest("webhook secret not configured")

    stripe = get_stripe()
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except ValueError:
        return HttpResponseBadRequest("invalid payload")
    except stripe.error.SignatureVerificationError:
        return HttpResponseBadRequest("invalid signature")

    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(obj)
        elif event_type in {
            "customer.subscription.updated",
            "customer.subscription.created",
            "customer.subscription.deleted",
        }:
            _handle_subscription_event(obj)
        else:
            logger.debug("Unhandled Stripe event: %s", event_type)
    except Exception:
        # Don't ack on internal failure — Stripe will retry.
        logger.exception("Stripe webhook handler failed for %s", event_type)
        return HttpResponse(status=500)

    return HttpResponse(status=200)

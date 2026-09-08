"""App Store / Google Play subscription notifications, received via RevenueCat.

Configure the endpoint in RevenueCat → Integrations → Webhooks pointing at
`/api/billing/store-webhook/`, and copy the shared secret you set there into
`REVENUECAT_WEBHOOK_AUTH`. RevenueCat sends it verbatim in the
`Authorization` header of every delivery.

Why RevenueCat and not the stores directly: Apple's App Store Server
Notifications v2 arrive as signed JWS that must be verified against Apple's
certificate chain, and Google Play publishes to a Pub/Sub topic you have to
own and subscribe to. Both pipelines have to be built, monitored and kept up
to date separately. RevenueCat normalizes them into one JSON shape and one
delivery mechanism. The rationale and the alternative are written up in
`docs/integracion-pagos-web-y-movil.md`.

The store is authoritative about *payment*; this endpoint is authoritative
about *entitlement*. The mobile client never grants itself a plan from a
local receipt — it asks the backend, which only knows what arrived here.

Sandbox and production events arrive at this same endpoint, so
`BILLING_TEST_MODE` decides whether a test purchase may actually move
someone's plan. It is off in production: sandbox events get recorded and
nothing else.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import logging
import uuid
from typing import Optional

from django.conf import settings
from django.db import IntegrityError
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.assistant.models import Plan

from .entitlements import Entitlement, EntitlementStatus, apply_entitlement
from .models import StoreWebhookEvent
from .catalog import plan_for_product, source_for_store


logger = logging.getLogger(__name__)


# --- Event type → lifecycle -------------------------------------------------
#
# The subtlety worth knowing: "cancelled" does not mean "access ends now".
# On both stores it means auto-renew was switched off, and the user keeps
# what they paid for until the period runs out. Only EXPIRATION (or a refund)
# actually revokes. Treating CANCELLATION as terminal would cut people off
# mid-period, which is both wrong and a support ticket.

#: Access continues. Includes BILLING_ISSUE: the store is retrying the charge
#: and the subscription is in its grace period — pulling the plan there would
#: punish a user whose card just expired.
_ACTIVE_EVENTS = {
    "INITIAL_PURCHASE",
    "RENEWAL",
    "PRODUCT_CHANGE",
    "UNCANCELLATION",
    "SUBSCRIPTION_EXTENDED",
    "BILLING_ISSUE",
    "NON_RENEWING_PURCHASE",
}

#: Access is over.
_TERMINAL_EVENTS = {
    "EXPIRATION",
    "REFUND",
    "SUBSCRIPTION_PAUSED",
}

#: Recorded but not acted on. TRANSFER moves an entitlement between accounts
#: and needs a human decision about who keeps it, so it is deliberately not
#: automated.
_IGNORED_EVENTS = {"TEST", "TRANSFER", "INVOICE_ISSUANCE", "TEMPORARY_ENTITLEMENT_GRANT"}

#: `cancel_reason` values that mean the money went back — access ends at once
#: rather than at the end of the period.
_REFUND_REASONS = {"CUSTOMER_SUPPORT", "REFUND", "DEVELOPER_INITIATED"}


#: Outcomes that a redelivery is allowed to reprocess. The row marks
#: *processed*, not merely *seen*.
#:
#: `unusable` is here because it never means "this event is bad" — it means
#: "we couldn't use it with the configuration we had at the time": a store we
#: don't map, or a product id missing from `STORE_PRODUCT_*`. Those are our
#: bugs, and once fixed the purchase has to be recoverable by replaying the
#: event. It was not, and a real purchase was stranded because of it: the
#: product settings were unset, the event was dropped, and there was no way
#: back short of charging the customer again.
#:
#: Note we answer 200 to unusable events, so the stores never retry them on
#: their own — this only matters for a deliberate replay.
_RETRIABLE_OUTCOMES = {"", "error", "unusable"}


def _authorized(request) -> bool:
    """Constant-time check of the shared secret RevenueCat echoes back."""
    expected = getattr(settings, "REVENUECAT_WEBHOOK_AUTH", "") or ""
    if not expected:
        return False
    provided = request.META.get("HTTP_AUTHORIZATION", "") or ""
    return hmac.compare_digest(provided, expected)


def _accepts_sandbox() -> bool:
    """Whether this deployment may act on test purchases.

    RevenueCat delivers sandbox and production events to the *same* endpoint,
    so without this a test purchase would promote a real account on the real
    database — the tester's own, usually, which is why it goes unnoticed until
    the audit log looks wrong. `BILLING_TEST_MODE` is what separates them: on
    in local and staging, off in production.

    Sandbox events are still recorded either way; only applying them is
    gated. That matters because the stored payload is how we answer questions
    about a channel's event shape (see `docs/pagos-unificados/PLAN.md` §1).
    """
    return bool(getattr(settings, "BILLING_TEST_MODE", False))


def _is_sandbox(event: dict) -> bool:
    """True only when the event says outright that it is a test purchase.

    A missing or unrecognized `environment` counts as production on purpose:
    dropping a real purchase is far worse than applying a sandbox one, so the
    ambiguous case fails towards granting.
    """
    return (event.get("environment") or "").upper() == "SANDBOX"


def _parse_user_id(app_user_id: str) -> Optional[uuid.UUID]:
    """Our user uuid, as registered with the store SDK at login.

    Anonymous ids (RevenueCat's `$RCAnonymousID:…`, used before the user logs
    in) resolve to None — those purchases can't be attributed until the app
    calls `logIn` and RevenueCat sends a TRANSFER.
    """
    if not app_user_id or app_user_id.startswith("$RCAnonymousID"):
        return None
    try:
        return uuid.UUID(app_user_id)
    except (ValueError, TypeError, AttributeError):
        return None


def _ms_to_datetime(value) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromtimestamp(int(value) / 1000, tz=dt.timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _classify(event: dict) -> EntitlementStatus:
    """Map a RevenueCat event onto the shared lifecycle vocabulary."""
    event_type = (event.get("type") or "").upper()
    if event_type in _IGNORED_EVENTS:
        return EntitlementStatus.IGNORE
    if event_type in _TERMINAL_EVENTS:
        return EntitlementStatus.TERMINAL
    if event_type == "CANCELLATION":
        # Refunds revoke now; a plain cancellation runs to the period end.
        reason = (event.get("cancel_reason") or "").upper()
        return (
            EntitlementStatus.TERMINAL
            if reason in _REFUND_REASONS
            else EntitlementStatus.ACTIVE
        )
    if event_type in _ACTIVE_EVENTS:
        return EntitlementStatus.ACTIVE
    logger.info("Unmapped store event type %r — ignoring", event_type)
    return EntitlementStatus.IGNORE


def _to_entitlement(event: dict) -> Optional[Entitlement]:
    """Build the normalized claim, or None if the event isn't usable."""
    product_id = event.get("product_id") or ""
    source = source_for_store(event.get("store") or "")
    if not source:
        logger.warning("Store event with unknown store %r", event.get("store"))
        return None

    status = _classify(event)
    plan = plan_for_product(product_id)
    if status is EntitlementStatus.ACTIVE and not plan:
        # An active purchase of something we don't recognize. Refusing to
        # guess is the point: granting a default plan here would let a
        # mispriced or stale product hand out Studio.
        logger.error(
            "Active store event for unmapped product %r — check STORE_PRODUCT_* settings",
            product_id,
        )
        return None

    # `expiration_at_ms` is when access lapses if nothing renews. On a
    # cancellation it is still in the future, which is exactly what makes
    # "cancelled but active until then" representable.
    return Entitlement(
        source=source,
        status=status,
        external_id=(
            event.get("original_transaction_id")
            or event.get("transaction_id")
            or event.get("id")
            or ""
        ),
        user_id=_parse_user_id(event.get("app_user_id") or ""),
        plan=plan or Plan.FREE.value,
        product_id=product_id,
        period_end=_ms_to_datetime(event.get("expiration_at_ms")),
        cancel_at_period_end=(event.get("type") or "").upper() == "CANCELLATION",
    )


@csrf_exempt
@require_POST
def store_webhook(request):
    """Receive one store notification and apply it to the user's entitlement.

    Returns 200 for anything successfully processed *or* deliberately
    ignored — a non-200 makes RevenueCat retry, and retrying an event we
    chose not to act on just generates noise. Genuine failures return 500 so
    the delivery is retried.
    """
    if not _authorized(request):
        # Deliberately terse: a detailed error tells a prober what to fix.
        logger.warning("Rejected store webhook with bad or missing auth header")
        return HttpResponse("unauthorized", status=401)

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("invalid payload")

    event = body.get("event") or {}
    event_id = event.get("id") or ""
    if not event_id:
        return HttpResponseBadRequest("missing event id")

    event_type = (event.get("type") or "").upper()
    source = source_for_store(event.get("store") or "") or ""

    # Insert-first deduplication: the primary key does the work, so two
    # concurrent deliveries of the same event can't both get through.
    # A row whose outcome is empty or "error" was received but never applied
    # (we crashed mid-flight), so a redelivery is allowed to retry it — the
    # row marks *processed*, not merely *seen*.
    try:
        row, created = StoreWebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                "event_type": event_type,
                "source": source,
                "app_user_id": event.get("app_user_id") or "",
                "product_id": event.get("product_id") or "",
                "payload": body,
            },
        )
    except IntegrityError:
        # Lost a race against a concurrent delivery of the same event; the
        # winner is processing it.
        logger.info("Concurrent duplicate for store event %s (%s)", event_id, event_type)
        return JsonResponse({"status": "duplicate"})

    if not created and row.outcome not in _RETRIABLE_OUTCOMES:
        logger.info("Duplicate store event %s (%s) — already applied", event_id, event_type)
        return JsonResponse({"status": "duplicate"})

    # Recorded above, deliberately not applied here: a test purchase must not
    # move anyone's plan on a production database.
    if _is_sandbox(event) and not _accepts_sandbox():
        row.outcome = "sandbox_ignored"
        row.save(update_fields=["outcome"])
        logger.info(
            "Sandbox store event %s (%s, %s) recorded but not applied "
            "(BILLING_TEST_MODE is off)",
            event_id,
            event_type,
            source,
        )
        return JsonResponse({"status": "sandbox_ignored"})

    try:
        ent = _to_entitlement(event)
        if ent is None:
            row.outcome = "unusable"
            row.save(update_fields=["outcome"])
            return JsonResponse({"status": "ignored"})

        outcome = apply_entitlement(ent)
        row.outcome = outcome.action
        row.save(update_fields=["outcome"])
        logger.info(
            "Store event %s (%s, %s) → %s", event_id, event_type, source, outcome.action
        )
    except Exception:
        # Mark the row failed rather than deleting it — the raw payload is
        # the only copy we have of what the store told us. `outcome="error"`
        # is in the retriable set above, so the redelivery that follows our
        # 500 will process it properly once the cause is fixed.
        row.outcome = "error"
        row.save(update_fields=["outcome"])
        logger.exception("Store webhook handler failed for %s (%s)", event_id, event_type)
        return HttpResponse(status=500)

    return JsonResponse({"status": "ok"})

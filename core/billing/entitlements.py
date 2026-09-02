"""Single write point for "which paid plan does this user have, and who sold it".

Every payment channel — the web, the App Store, Google Play — translates its
own event shape into an `Entitlement` and hands it to `apply_entitlement()`.
Nothing else is allowed to write `plan`, `billing_source`, `plan_renews_at`,
or the `billing_*` id columns of `AccountProfile`.

Why this exists
---------------
Before, `sync_subscription_to_profile()` wrote the plan straight from Stripe
events. With a single gateway that was merely fragile: the terminal branch
checked that the event concerned the user's *current* subscription, but the
active branch did not, so a late `customer.subscription.updated` from an old
subscription could repoint the plan at the wrong one.

With several issuers writing the same row that stops being a corner case, so
the guard lives here instead — symmetric for every branch and every source:

1. **An event never silently overwrites another source's live entitlement.**
   A stale web event cannot demote an App Store subscriber, and vice versa.
2. **Conflicts resolve deterministically**, never by arrival order: the
   entitlement that runs longest wins, and the loser is written to the audit
   log so it can be refunded.
3. **`is_billing_exempt` is honored in exactly one place** — the revoke path —
   instead of being re-checked by each caller.

See `docs/integracion-pagos-web-y-movil.md` for the model and
`docs/pagos-unificados/PLAN.md` for the migration in progress.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.admin_api.audit import record as audit_record
from core.assistant.models import STORE_SOURCES, AccountProfile, Plan


logger = logging.getLogger(__name__)


class EntitlementStatus(Enum):
    """Normalized lifecycle state, shared by every payment channel.

    Each channel maps its own vocabulary onto these three: Stripe's
    `active`/`trialing`/`past_due`, Apple's `RENEWAL`/`PRODUCT_CHANGE`, and
    Google's `SUBSCRIPTION_RENEWED` all collapse to `ACTIVE`.
    """

    #: User is entitled to the paid plan right now (includes trials and the
    #: grace period of a failed payment — access continues while the store
    #: retries).
    ACTIVE = "active"
    #: Entitlement is over: cancelled, expired, refunded, or revoked.
    TERMINAL = "terminal"
    #: In-flight or uninteresting (Stripe's `incomplete`, a test notification).
    #: Explicitly *not* terminal: treating a half-finished checkout as a
    #: downgrade wipes out the subscription the user already has.
    IGNORE = "ignore"


@dataclass(frozen=True)
class Entitlement:
    """One channel's claim about what a user is entitled to.

    Attributes:
        user_id: Our user. May be None for events that only carry a customer
            or transaction id — `apply_entitlement` falls back to those.
        source: Which channel is speaking (`BillingSource` value).
        status: Normalized lifecycle state.
        external_id: Stable per-subscription id *within that source*. Apple:
            original transaction id. Google: purchase token. Used to tell "the
            current subscription" apart from a stale or parallel one.
        plan: Target plan while ACTIVE. Ignored when TERMINAL.
        product_id: Product identifier of the plan, in the issuer's catalog.
        period_end: When access lapses if nothing renews. Drives both
            `plan_renews_at` and conflict resolution.
        cancel_at_period_end: Renewal is off but access continues until
            `period_end`.
        customer_id: Customer identifier at the issuer, for profile lookup.
    """

    source: str
    status: EntitlementStatus
    external_id: str
    user_id: Optional[uuid.UUID] = None
    plan: str = Plan.FREE.value
    product_id: str = ""
    period_end: Optional[dt.datetime] = None
    cancel_at_period_end: bool = False
    customer_id: Optional[str] = None


@dataclass(frozen=True)
class EntitlementOutcome:
    """What `apply_entitlement` did. Returned for logging and tests.

    Attributes:
        action: One of `granted`, `revoked`, `ignored_stale`,
            `ignored_non_terminal`, `skipped_exempt`, `conflict_kept_existing`,
            `no_profile`.
        plan: The plan on the profile after the call (unchanged if no write).
        source: The billing source on the profile after the call.
        detail: Human-readable reason, for logs.
    """

    action: str
    plan: str = ""
    source: str = ""
    detail: str = ""


def _find_profile(ent: Entitlement) -> Optional[AccountProfile]:
    """Resolve the profile from user id, customer id, or transaction id.

    Webhooks may arrive with only the transaction id if the app-level user
    mapping was dropped, so we keep a third lookup path.
    """
    if ent.user_id is not None:
        profile = AccountProfile.objects.filter(user_id=ent.user_id).first()
        if profile is not None:
            return profile
    if ent.customer_id:
        profile = AccountProfile.objects.filter(
            billing_customer_id=ent.customer_id
        ).first()
        if profile is not None:
            return profile
    if ent.external_id:
        return AccountProfile.objects.filter(
            billing_transaction_id=ent.external_id
        ).first()
    return None


def _has_live_entitlement(profile: AccountProfile) -> bool:
    """True when the profile currently holds a paid entitlement someone sold.

    Keyed on the transaction id rather than on `billing_source`: a row with a
    live subscription must be protected even if the source column is somehow
    blank, and that is the safer way round.

    Deliberately ignores `is_billing_exempt` and `is_admin`: those grant a
    plan without anyone paying, so they are not an entitlement another source
    could be in conflict with.
    """
    return bool(profile.billing_transaction_id) and profile.plan in {
        Plan.PRO.value,
        Plan.STUDIO.value,
    }


def _is_later(a: Optional[dt.datetime], b: Optional[dt.datetime]) -> bool:
    """True when `a` runs at least as long as `b`.

    A missing end date is treated as "runs forever": a channel that doesn't
    tell us when access lapses should not lose a tiebreak to one that does.
    """
    if a is None:
        return True
    if b is None:
        return False
    return a >= b


def apply_entitlement(ent: Entitlement) -> EntitlementOutcome:
    """Apply one channel's claim to `AccountProfile`. The only writer.

    Args:
        ent: The normalized claim. Callers translate their own event shape
            into this; they must not touch the profile themselves.

    Returns:
        `EntitlementOutcome` describing the decision. Callers should log it
        but generally have nothing to do with it — the point of the return
        value is that the decision is testable.
    """
    if ent.status is EntitlementStatus.IGNORE:
        return EntitlementOutcome(
            action="ignored_non_terminal",
            detail=f"{ent.source}:{ent.external_id} reported a non-actionable state",
        )

    profile = _find_profile(ent)
    if profile is None:
        logger.warning(
            "apply_entitlement: no profile for source=%s user_id=%s customer_id=%s ext=%s",
            ent.source,
            ent.user_id,
            ent.customer_id,
            ent.external_id,
        )
        return EntitlementOutcome(action="no_profile")

    current_source = profile.billing_source
    current_external = profile.billing_transaction_id
    # "This event is about the entitlement we already track" — we track
    # nothing yet, or it is the same issuer and the same subscription.
    is_current = (not current_external) or (
        current_source == ent.source and current_external == ent.external_id
    )

    if ent.status is EntitlementStatus.TERMINAL:
        return _revoke(profile, ent, is_current=is_current)
    return _grant(profile, ent, is_current=is_current)


def _grant(
    profile: AccountProfile, ent: Entitlement, *, is_current: bool
) -> EntitlementOutcome:
    """Write an active entitlement, refusing to clobber a competing live one."""
    if (
        is_current
        and ent.source in STORE_SOURCES
        and ent.period_end is not None
        and profile.plan_renews_at is not None
        and ent.period_end < profile.plan_renews_at
    ):
        # An out-of-order redelivery of an older renewal. Store subscriptions
        # only ever extend, so an event that ends *earlier* than what we have
        # is describing the past, and applying it would shorten the user's
        # access. Deliberately store-only: on Stripe, switching annual→monthly
        # legitimately moves the period end backwards.
        logger.info(
            "Ignoring out-of-order store event %s:%s (ends %s, current ends %s)",
            ent.source,
            ent.external_id,
            ent.period_end,
            profile.plan_renews_at,
        )
        return EntitlementOutcome(
            action="ignored_stale",
            plan=profile.plan,
            source=profile.billing_source,
            detail="event describes an earlier period than the one on file",
        )

    if not is_current and _has_live_entitlement(profile):
        # Two entitlements claim the same user. This is a real billing
        # incident (the user is probably being charged twice), so it never
        # resolves by arrival order — the longer-running one wins and the
        # other is recorded for a refund.
        incumbent_end = profile.plan_renews_at
        if _is_later(incumbent_end, ent.period_end):
            audit_record(
                actor_user_id=profile.user_id,
                action="billing.entitlement_conflict",
                target_type="subscription",
                target_id=ent.external_id,
                payload={
                    "kept": {
                        "source": profile.billing_source,
                        "external_id": profile.billing_transaction_id,
                        "plan": profile.plan,
                        "period_end": incumbent_end.isoformat() if incumbent_end else None,
                    },
                    "rejected": {
                        "source": ent.source,
                        "external_id": ent.external_id,
                        "plan": ent.plan,
                        "period_end": ent.period_end.isoformat() if ent.period_end else None,
                    },
                    "resolution": "kept_existing_runs_longer",
                },
            )
            logger.error(
                "Entitlement conflict for user %s: kept %s:%s, rejected %s:%s",
                profile.user_id,
                profile.billing_source,
                profile.billing_transaction_id,
                ent.source,
                ent.external_id,
            )
            return EntitlementOutcome(
                action="conflict_kept_existing",
                plan=profile.plan,
                source=profile.billing_source,
                detail="incoming entitlement ends sooner than the current one",
            )
        # The incoming one runs longer: it takes over, but the displaced
        # subscription still needs cancelling by a human.
        audit_record(
            actor_user_id=profile.user_id,
            action="billing.entitlement_conflict",
            target_type="subscription",
            target_id=ent.external_id,
            payload={
                "kept": {
                    "source": ent.source,
                    "external_id": ent.external_id,
                    "plan": ent.plan,
                    "period_end": ent.period_end.isoformat() if ent.period_end else None,
                },
                "displaced": {
                    "source": profile.billing_source,
                    "external_id": profile.billing_transaction_id,
                    "plan": profile.plan,
                    "period_end": incumbent_end.isoformat() if incumbent_end else None,
                },
                "resolution": "took_over_runs_longer",
                "action_required": "cancel and refund the displaced subscription",
            },
        )
        logger.error(
            "Entitlement conflict for user %s: %s:%s took over from %s:%s",
            profile.user_id,
            ent.source,
            ent.external_id,
            profile.billing_source,
            profile.billing_transaction_id,
        )

    profile.plan = ent.plan
    profile.billing_source = ent.source
    profile.cancel_at_period_end = ent.cancel_at_period_end
    profile.plan_renews_at = ent.period_end or profile.plan_renews_at
    profile.billing_transaction_id = ent.external_id
    profile.billing_product_id = ent.product_id or ""
    if ent.customer_id:
        profile.billing_customer_id = ent.customer_id

    profile.save(
        update_fields=[
            "plan",
            "billing_source",
            "billing_customer_id",
            "billing_transaction_id",
            "billing_product_id",
            "plan_renews_at",
            "cancel_at_period_end",
            "updated_at",
        ]
    )
    return EntitlementOutcome(
        action="granted", plan=profile.plan, source=profile.billing_source
    )


def _revoke(
    profile: AccountProfile, ent: Entitlement, *, is_current: bool
) -> EntitlementOutcome:
    """Drop to free, unless the event is stale or the user is exempt."""
    if not is_current:
        logger.info(
            "Ignoring terminal event for stale entitlement %s:%s (current is %s:%s)",
            ent.source,
            ent.external_id,
            profile.billing_source,
            profile.billing_transaction_id,
        )
        return EntitlementOutcome(
            action="ignored_stale",
            plan=profile.plan,
            source=profile.billing_source,
            detail="terminal event for a subscription that is not the current one",
        )

    if profile.is_billing_exempt:
        # Comp / beta / partner accounts keep their plan even when a
        # subscription behind them lapses. Their plan is granted by the
        # exemption, not bought.
        logger.info(
            "Skipping revoke for exempt user %s (%s:%s)",
            profile.user_id,
            ent.source,
            ent.external_id,
        )
        return EntitlementOutcome(
            action="skipped_exempt",
            plan=profile.plan,
            source=profile.billing_source,
            detail="account is billing-exempt",
        )

    profile.plan = Plan.FREE.value
    profile.billing_source = ""
    profile.billing_transaction_id = ""
    profile.billing_product_id = ""
    profile.plan_renews_at = None
    profile.cancel_at_period_end = False
    # `billing_customer_id` deliberately survives: the customer record still
    # exists at the issuer, and keeping it lets a later re-subscription land
    # on the same customer instead of creating a duplicate.
    profile.save(
        update_fields=[
            "plan",
            "billing_source",
            "billing_transaction_id",
            "billing_product_id",
            "plan_renews_at",
            "cancel_at_period_end",
            "updated_at",
        ]
    )
    return EntitlementOutcome(action="revoked", plan=Plan.FREE.value, source="")

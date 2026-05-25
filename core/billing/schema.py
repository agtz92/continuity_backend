"""GraphQL surface for billing operations.

Exposes:
- createCheckoutSession(plan, period) → CheckoutSession{ url }
- createPortalSession() → PortalSession{ url }

Both are mutations that return a URL the frontend redirects the user to.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from .services import (
    BillingConfigError,
    NoActiveSubscriptionError,
    RetentionAlreadyUsedError,
    apply_retention_coupon,
    cancel_subscription,
    coupon_for_reason,
    create_checkout_session,
    create_portal_session,
    downgrade_subscription,
    reactivate_subscription,
)


@strawberry.enum
class BillingPeriod(Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


@strawberry.enum
class PurchasablePlan(Enum):
    PRO = "pro"
    STUDIO = "studio"


@strawberry.enum
class CancellationReason(Enum):
    TOO_EXPENSIVE = "too_expensive"
    NOT_USED = "not_used"
    MISSING_FEATURES = "missing_features"
    SWITCHING = "switching"
    TRIAL_ONLY = "trial_only"
    OTHER = "other"


@strawberry.type
class CheckoutSession:
    url: str


@strawberry.type
class PortalSession:
    url: str


@strawberry.type
class RetentionOfferResult:
    applied: bool
    coupon_id: Optional[str]
    reason: str


@strawberry.type
class CancelSubscriptionResult:
    scheduled: bool
    current_period_end: Optional[int]


@strawberry.type
class DowngradeResult:
    success: bool
    from_plan: str
    to_plan: str


@strawberry.type
class ReactivateResult:
    success: bool


def _uid(info: Info):
    user_id = getattr(info.context, "user_id", None)
    if not user_id:
        raise GraphQLError(
            "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
        )
    return user_id


@strawberry.type
class BillingMutation:
    @strawberry.mutation
    def create_checkout_session(
        self,
        info: Info,
        plan: PurchasablePlan,
        period: BillingPeriod,
        locale: Optional[str] = None,
    ) -> CheckoutSession:
        uid = _uid(info)
        try:
            url = create_checkout_session(
                uid, plan=plan.value, period=period.value, locale=locale
            )
        except BillingConfigError as e:
            raise GraphQLError(
                str(e), extensions={"code": "BILLING_NOT_CONFIGURED"}
            )
        return CheckoutSession(url=url)

    @strawberry.mutation
    def create_portal_session(
        self, info: Info, locale: Optional[str] = None
    ) -> PortalSession:
        uid = _uid(info)
        try:
            url = create_portal_session(uid, locale=locale)
        except BillingConfigError as e:
            raise GraphQLError(
                str(e), extensions={"code": "BILLING_NOT_CONFIGURED"}
            )
        return PortalSession(url=url)

    @strawberry.mutation
    def apply_retention_offer(
        self,
        info: Info,
        reason: CancellationReason,
        feedback_text: Optional[str] = None,
    ) -> RetentionOfferResult:
        uid = _uid(info)
        try:
            result = apply_retention_coupon(
                uid,
                reason=reason.value,
                feedback_text=feedback_text or "",
            )
        except RetentionAlreadyUsedError as e:
            raise GraphQLError(
                str(e), extensions={"code": "RETENTION_ALREADY_USED"}
            )
        except NoActiveSubscriptionError as e:
            raise GraphQLError(
                str(e), extensions={"code": "NO_ACTIVE_SUBSCRIPTION"}
            )
        except BillingConfigError as e:
            raise GraphQLError(
                str(e), extensions={"code": "BILLING_NOT_CONFIGURED"}
            )
        return RetentionOfferResult(
            applied=True, coupon_id=result.get("coupon"), reason=reason.value
        )

    @strawberry.mutation
    def cancel_subscription(
        self,
        info: Info,
        reason: CancellationReason,
        feedback_text: Optional[str] = None,
    ) -> CancelSubscriptionResult:
        uid = _uid(info)
        try:
            result = cancel_subscription(
                uid,
                reason=reason.value,
                feedback_text=feedback_text or "",
            )
        except NoActiveSubscriptionError as e:
            raise GraphQLError(
                str(e), extensions={"code": "NO_ACTIVE_SUBSCRIPTION"}
            )
        return CancelSubscriptionResult(
            scheduled=True,
            current_period_end=result.get("current_period_end"),
        )

    @strawberry.mutation
    def reactivate_subscription(self, info: Info) -> ReactivateResult:
        uid = _uid(info)
        try:
            reactivate_subscription(uid)
        except NoActiveSubscriptionError as e:
            raise GraphQLError(
                str(e), extensions={"code": "NO_ACTIVE_SUBSCRIPTION"}
            )
        return ReactivateResult(success=True)

    @strawberry.mutation
    def downgrade_to_plan(
        self,
        info: Info,
        plan: PurchasablePlan,
        period: BillingPeriod,
    ) -> DowngradeResult:
        uid = _uid(info)
        try:
            result = downgrade_subscription(
                uid,
                target_plan=plan.value,
                period=period.value,
            )
        except NoActiveSubscriptionError as e:
            raise GraphQLError(
                str(e), extensions={"code": "NO_ACTIVE_SUBSCRIPTION"}
            )
        except BillingConfigError as e:
            raise GraphQLError(
                str(e), extensions={"code": "BILLING_NOT_CONFIGURED"}
            )
        return DowngradeResult(
            success=True,
            from_plan=result["from_plan"],
            to_plan=result["to_plan"],
        )

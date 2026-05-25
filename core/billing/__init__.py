"""Stripe billing — checkout sessions, customer portal, webhook sync.

Plan/feature gating lives in `core.assistant.quotas` (AI usage) and
`core.quotas` (entity counts). This package is purely about money:
turning a paid signup into an `AccountProfile.plan` change.

Webhook handling respects `is_billing_exempt` — staff-comp accounts never
get downgraded by Stripe events, even if a stale subscription deletes.
"""

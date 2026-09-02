"""Billing — one entitlement layer fed by RevenueCat for all three channels.

Web, App Store and Google Play all sell through RevenueCat, which delivers
every subscription event to a single webhook. Those events are translated into
an `Entitlement` and applied by `entitlements.apply_entitlement()`, the only
thing allowed to decide which paid plan an account has.

Stripe is not an issuer here. It remains the card processor underneath Web
Billing — which is why a card fee shows up in the net-revenue maths in
`catalog.py` — but we hold no Stripe integration of our own.

- `entitlements.py` — the single write point, and every rule about staleness,
  cross-channel conflicts and billing exemption.
- `store_webhooks.py` — receives and deduplicates RevenueCat deliveries.
- `catalog.py` — product ids, prices (shared across channels, which is what
  makes price parity structural) and per-channel fees.
- `models.py` — durable log of received events, for idempotency and
  reconciliation.

See `docs/integracion-pagos-web-y-movil.md`.
"""

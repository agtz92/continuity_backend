"""Durable log of store webhook deliveries.

Two jobs that a hosted checkout would have handled for us and a webhook
pipeline does not:

1. **Idempotency.** Apple and Google (and RevenueCat in front of them) retry
   aggressively and can deliver the same notification many times. The app
   cache can't be used for this — it's `LocMemCache`, so it is per-process
   and every gunicorn worker would have its own idea of what it had seen.
2. **Reconciliation.** When a user says "I paid on my iPhone and the app
   says Free", this table is the only place the raw notification survives.
   Apple and Google keep their own console history, but correlating it with
   our decision needs the outcome we recorded at the time.

See `docs/integracion-pagos-web-y-movil.md`.
"""

from __future__ import annotations

from django.db import models


class StoreWebhookEvent(models.Model):
    """One notification received from a store (via RevenueCat).

    The store's own event id is the primary key: inserting twice raises
    `IntegrityError`, which is exactly the deduplication signal we want.
    """

    event_id = models.CharField(max_length=255, primary_key=True)
    event_type = models.CharField(max_length=64, db_index=True)
    #: `BillingSource` value derived from the payload's `store` field.
    source = models.CharField(max_length=16, blank=True, default="")
    #: The id the mobile app registered with the store SDK. Should be our
    #: user uuid; kept as text so a malformed one is still recorded.
    app_user_id = models.CharField(max_length=255, blank=True, default="")
    product_id = models.CharField(max_length=255, blank=True, default="")
    #: `EntitlementOutcome.action` — what we decided to do about it.
    outcome = models.CharField(max_length=32, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["app_user_id", "-received_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - admin convenience
        return f"{self.event_type} {self.event_id}"

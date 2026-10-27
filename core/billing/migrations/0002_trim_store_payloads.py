"""Trim stored webhook bodies to the billing fields.

Ingest now keeps only `BILLING_EVENT_FIELDS`; this brings the rows stored
before that in line (subscriber_attributes, aliases, app_user_id inside the
payload). Rows already redacted by account deletion or emptied by retention
keep their shape.
"""

from django.db import migrations

# Frozen copy: a migration must not depend on code that can change later.
FIELDS = {
    "id", "type", "store", "environment", "product_id", "new_product_id",
    "entitlement_ids", "period_type", "purchased_at_ms", "expiration_at_ms",
    "event_timestamp_ms", "transaction_id", "original_transaction_id",
    "renewal_number", "is_trial_conversion", "cancel_reason", "expiration_reason",
    "price", "price_in_purchased_currency", "currency", "country_code",
    "tax_percentage", "commission_percentage", "takehome_percentage",
}


def trim(apps, schema_editor):
    StoreWebhookEvent = apps.get_model("billing", "StoreWebhookEvent")
    for row in StoreWebhookEvent.objects.exclude(payload={}).iterator():
        payload = row.payload or {}
        event = payload.get("event")
        if not isinstance(event, dict):
            continue
        trimmed = {k: v for k, v in event.items() if k in FIELDS}
        if trimmed == event:
            continue
        payload["event"] = trimmed
        row.payload = payload
        row.save(update_fields=["payload"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]

    operations = [migrations.RunPython(trim, migrations.RunPython.noop)]

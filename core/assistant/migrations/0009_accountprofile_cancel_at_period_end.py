"""Add cancel_at_period_end flag to AccountProfile.

Mirrors the Stripe subscription's `cancel_at_period_end` so the UI can
show a "scheduled to cancel on X" state without hitting Stripe on every
/usage/ load. Updated by sync_subscription_to_profile on webhook events
and by cancel/reactivate service calls.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0008_accountprofile_stripe_price_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="cancel_at_period_end",
            field=models.BooleanField(default=False),
        ),
    ]

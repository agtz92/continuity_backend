"""Add stripe_price_id to AccountProfile.

Lets the backend report the current billing period (monthly/annual)
without hitting Stripe on every /usage/ request. Filled by
sync_subscription_to_profile during webhook handling.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0007_had_retention_offer"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="stripe_price_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]

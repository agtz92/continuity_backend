"""Add had_retention_offer flag to AccountProfile.

Tracks whether a user has already received (and accepted) a retention
coupon during a cancellation attempt. We cap retention offers at one per
user to prevent gaming the cancellation flow for discounts.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0006_grant_studio_to_existing"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="had_retention_offer",
            field=models.BooleanField(default=False),
        ),
    ]

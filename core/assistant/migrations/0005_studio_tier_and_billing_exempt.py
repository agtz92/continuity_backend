"""Add Studio tier to Plan and is_billing_exempt flag.

- Plan now has a `studio` choice between `pro` and `admin`. `admin` is
  retained as an internal staff role (no public offering).
- `is_billing_exempt` lets staff mark cuentas as comp/cortesía: their
  plan dictates features, the flag dictates whether Stripe charges them.
  Defaults False — set explicitly via admin UI or data migration.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0004_usageday_deep_messages"),
    ]

    operations = [
        migrations.AlterField(
            model_name="accountprofile",
            name="plan",
            field=models.CharField(
                choices=[
                    ("free", "Free"),
                    ("pro", "Pro"),
                    ("studio", "Studio"),
                    ("admin", "Admin"),
                ],
                default="free",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="is_billing_exempt",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]

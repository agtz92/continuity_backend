"""Backfill the beta cohort from the existing user base.

Owner decision (2026-06-15): every current user EXCEPT three explicit accounts
becomes a beta member. For each backfilled profile:

    beta_cohort=True, beta_status="active", billing_exempt_reason="beta",
    is_billing_exempt=True, beta_enrolled_at=created
    plan -> "pro" only if currently "free" (never downgrade studio/admin)

The three EXCLUDED accounts are left untouched (beta_cohort stays False; their
billing is NOT changed here — toggle in /admin/beta if they should pay).

Runs only against the deploy DB on `migrate`. Reversible: clears the beta
fields for rows whose exemption reason is "beta".
"""

import uuid

from django.db import migrations
from django.db.models import F

# Accounts that must NOT be in the beta cohort.
EXCLUDED = [
    uuid.UUID("042175b7-13c4-4576-9e66-2e8a78b32233"),
    uuid.UUID("ceb43168-dc75-47a6-a2a0-cafbd288c3c4"),
    uuid.UUID("425276ec-207c-4da2-beff-1090fa75930a"),
]


def backfill(apps, schema_editor):
    AccountProfile = apps.get_model("assistant", "AccountProfile")
    beta = AccountProfile.objects.exclude(user_id__in=EXCLUDED).filter(beta_cohort=False)
    beta.update(
        beta_cohort=True,
        beta_status="active",
        is_billing_exempt=True,
        billing_exempt_reason="beta",
        beta_enrolled_at=F("created"),
    )
    # Beta members on the free plan get Pro features; never downgrade a higher tier.
    AccountProfile.objects.filter(beta_cohort=True, plan="free").update(plan="pro")


def unbackfill(apps, schema_editor):
    AccountProfile = apps.get_model("assistant", "AccountProfile")
    AccountProfile.objects.filter(
        beta_cohort=True, billing_exempt_reason="beta"
    ).update(
        beta_cohort=False,
        beta_status="",
        billing_exempt_reason="",
        beta_enrolled_at=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0010_accountprofile_beta_cohort_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]

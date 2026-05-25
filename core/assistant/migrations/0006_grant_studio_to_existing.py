"""Promote every pre-existing AccountProfile to Studio + billing exempt.

Background: the public Studio tier is launching, and the ~5 users that
existed pre-launch (beta testers / founders) get Studio free for life as
a thank-you. Because the launch flips on the Stripe webhook and the
public signup flow at the same time, every profile that exists *right
now* is by definition pre-launch — no email filter needed.

This migration must run **before** Stripe webhooks are pointed at
production, otherwise subscription events for new sign-ups could race
against the upgrade. The deploy runbook has the explicit ordering.

The reverse path restores the affected profiles to free / non-exempt —
intended as an emergency unwind, not a regular operation.
"""

from django.db import migrations


def grant_studio_to_pre_launch(apps, schema_editor):
    AccountProfile = apps.get_model("assistant", "AccountProfile")
    AccountProfile.objects.all().update(plan="studio", is_billing_exempt=True)


def reverse_grant(apps, schema_editor):
    AccountProfile = apps.get_model("assistant", "AccountProfile")
    AccountProfile.objects.filter(is_billing_exempt=True).update(
        plan="free", is_billing_exempt=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0005_studio_tier_and_billing_exempt"),
    ]

    operations = [
        migrations.RunPython(grant_studio_to_pre_launch, reverse_grant),
    ]

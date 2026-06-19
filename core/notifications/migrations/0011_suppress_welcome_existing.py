"""Suppress the new-signup welcome for users that already exist at launch.

The backfill made existing users beta_cohort, but the welcome ("You're in,
create your first project") makes no sense for people who've used the app for
months. This marks every current AccountProfile with a SUPPRESSED welcome row
so send_lifecycle_welcome skips them. New signups (no such row) still get it.

Owner decision 2026-06-15. Reversible: deletes the SUPPRESSED rows.
"""

from django.db import migrations
from django.utils import timezone


def suppress(apps, schema_editor):
    AccountProfile = apps.get_model("assistant", "AccountProfile")
    EmailSend = apps.get_model("notifications", "EmailSend")

    already = set(
        EmailSend.objects.filter(
            email_id__in=["welcome_beta", "welcome_regular"], dry_run=False
        ).values_list("user_id", flat=True)
    )
    now = timezone.now()
    rows = []
    for user_id, beta in AccountProfile.objects.values_list("user_id", "beta_cohort"):
        if user_id in already:
            continue
        rows.append(
            EmailSend(
                user_id=user_id,
                email_id="welcome_beta" if beta else "welcome_regular",
                episode_key="",
                status="suppressed",
                dry_run=False,
                sent_at=now,
            )
        )
    EmailSend.objects.bulk_create(rows, ignore_conflicts=True)


def unsuppress(apps, schema_editor):
    EmailSend = apps.get_model("notifications", "EmailSend")
    EmailSend.objects.filter(status="suppressed").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0010_alter_emailsend_status"),
        ("assistant", "0011_backfill_beta_cohort"),
    ]

    operations = [
        migrations.RunPython(suppress, unsuppress),
    ]

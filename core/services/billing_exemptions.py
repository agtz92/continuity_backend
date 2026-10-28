"""Expire billing exemptions whose end date (`billing_exempt_until`) passed.

A courtesy plan ("3 months of Studio, on us") is an exemption with an end
date. When it passes:

- `is_billing_exempt` goes off and the reason/date are cleared.
- If nobody is charging for the plan (`billing_source == ""`), the plan drops
  to Free — the same thing `entitlements._revoke` does when a subscription
  ends. A user who started paying in the meantime keeps the plan they bought.
- `Plan.ADMIN` (staff) is never touched.

Runs every hour from `run_beta_lifecycle`, before its daily hour gate, so an
exemption ends within the hour of its date. Unlike the beta emails it ignores
`app_config.dry_run`: the date was set explicitly by an admin.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from django.db import transaction
from django.utils import timezone

from core.assistant.models import AccountProfile, Plan

from .beta_lifecycle import SYSTEM_ACTOR


def expire_due(now: Optional[dt.datetime] = None) -> int:
    """Expire every due exemption. Returns how many were expired."""
    from core.admin_api import audit

    now = now or timezone.now()
    expired = 0
    due = AccountProfile.objects.filter(
        is_billing_exempt=True, billing_exempt_until__lte=now
    ).values_list("user_id", flat=True)
    for user_id in list(due):
        with transaction.atomic():
            # Re-read under lock: an admin may have extended it meanwhile.
            profile = (
                AccountProfile.objects.select_for_update()
                .filter(
                    user_id=user_id,
                    is_billing_exempt=True,
                    billing_exempt_until__lte=now,
                )
                .first()
            )
            if profile is None:
                continue
            before = {
                "plan": profile.plan,
                "reason": profile.billing_exempt_reason,
                "until": profile.billing_exempt_until.isoformat(),
            }
            profile.is_billing_exempt = False
            profile.billing_exempt_reason = ""
            profile.billing_exempt_until = None
            fields = [
                "is_billing_exempt",
                "billing_exempt_reason",
                "billing_exempt_until",
                "updated_at",
            ]
            if not profile.billing_source and profile.plan != Plan.ADMIN:
                profile.plan = Plan.FREE.value
                fields.append("plan")
            profile.save(update_fields=fields)
            audit.record(
                actor_user_id=SYSTEM_ACTOR,
                action="billing.exempt_expired",
                target_type="user",
                target_id=profile.user_id,
                payload={"before": before, "after_plan": profile.plan},
            )
            expired += 1
    return expired

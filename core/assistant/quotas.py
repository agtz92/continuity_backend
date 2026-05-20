"""Per-user quota check + recording."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import AccountProfile, Plan, UsageDay


PLAN_QUOTAS = {
    Plan.FREE.value: {"daily_messages": 20, "monthly_tokens": 200_000},
    Plan.PRO.value: {"daily_messages": 300, "monthly_tokens": 5_000_000},
    Plan.ADMIN.value: {"daily_messages": None, "monthly_tokens": None},
}


class QuotaExceeded(Exception):
    def __init__(self, kind: str, reset_at: dt.datetime):
        super().__init__(f"Quota exceeded: {kind}")
        self.kind = kind
        self.reset_at = reset_at


@dataclass
class UsageSnapshot:
    plan: str
    messages_sent_today: int
    daily_message_cap: Optional[int]
    tokens_used_month: int
    monthly_token_cap: Optional[int]
    reset_at: dt.datetime


def get_or_create_profile(user_id: uuid.UUID) -> AccountProfile:
    profile, _ = AccountProfile.objects.get_or_create(user_id=user_id)
    return profile


def _start_of_next_day(now: dt.datetime) -> dt.datetime:
    tomorrow = (now + dt.timedelta(days=1)).date()
    return dt.datetime(
        tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=now.tzinfo
    )


def _start_of_month(now: dt.datetime) -> dt.date:
    return dt.date(now.year, now.month, 1)


def get_usage(user_id: uuid.UUID) -> UsageSnapshot:
    profile = get_or_create_profile(user_id)
    quota = PLAN_QUOTAS[profile.plan]
    now = timezone.now()

    today = UsageDay.objects.filter(user_id=user_id, date=now.date()).first()
    messages_today = today.messages_sent if today else 0

    month_start = _start_of_month(now)
    month_total = (
        UsageDay.objects.filter(user_id=user_id, date__gte=month_start)
        .aggregate(t=Sum("tokens_in"), o=Sum("tokens_out"))
    )
    tokens_month = (month_total["t"] or 0) + (month_total["o"] or 0)

    return UsageSnapshot(
        plan=profile.plan,
        messages_sent_today=messages_today,
        daily_message_cap=quota["daily_messages"],
        tokens_used_month=tokens_month,
        monthly_token_cap=quota["monthly_tokens"],
        reset_at=_start_of_next_day(now),
    )


def check(user_id: uuid.UUID) -> UsageSnapshot:
    """Raise QuotaExceeded if the user is over either cap. Returns current snapshot."""
    snap = get_usage(user_id)
    if snap.daily_message_cap is not None and snap.messages_sent_today >= snap.daily_message_cap:
        raise QuotaExceeded("daily_messages", snap.reset_at)
    if (
        snap.monthly_token_cap is not None
        and snap.tokens_used_month >= snap.monthly_token_cap
    ):
        raise QuotaExceeded("monthly_tokens", snap.reset_at)
    return snap


def deep_allowed(user_id: uuid.UUID) -> bool:
    """True if the user still has room under the daily Sonnet (deep) cap.

    The cap applies to every plan, admin included — it's a cost guard, not
    a feature gate. A cap of 0 (or less) disables deep mode entirely.
    """
    cap = getattr(settings, "ASSISTANT_DEEP_DAILY_CAP", 10)
    if cap is None or cap <= 0:
        return False
    today = UsageDay.objects.filter(
        user_id=user_id, date=timezone.now().date()
    ).first()
    used = today.deep_messages if today else 0
    return used < cap


def record(
    user_id: uuid.UUID,
    *,
    tokens_in: int,
    tokens_out: int,
    cache_read_in: int,
    counts_message: bool = True,
    deep: bool = False,
) -> None:
    """Append usage counters for today. Idempotent under concurrent calls thanks to F() expressions."""
    today = timezone.now().date()
    with transaction.atomic():
        row, created = UsageDay.objects.get_or_create(
            user_id=user_id, date=today
        )
        UsageDay.objects.filter(pk=row.pk).update(
            messages_sent=F("messages_sent") + (1 if counts_message else 0),
            tokens_in=F("tokens_in") + max(0, int(tokens_in)),
            tokens_out=F("tokens_out") + max(0, int(tokens_out)),
            cache_read_in=F("cache_read_in") + max(0, int(cache_read_in)),
            deep_messages=F("deep_messages") + (1 if deep else 0),
        )

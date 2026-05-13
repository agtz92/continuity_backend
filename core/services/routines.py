"""Routine services.

Routines are user-owned recurring (or one-off) activities that don't belong
to any project. The recurrence rule lives on the Routine row; pending
occurrences are computed on the fly via `compute_due_dates`; completed
occurrences are persisted as RoutineOccurrence rows (historical record).
"""

from __future__ import annotations

import calendar
import datetime as dt
import uuid
from typing import Optional

from django.core.exceptions import ValidationError
from django.utils import timezone

from ..models import (
    ActivityKind,
    IntervalUnit,
    RecurrenceType,
    Routine,
    RoutineOccurrence,
)
from ._cache import bump_context_version
from ._common import NotFoundError
from .activities import log_event


WEEKDAY_MIN = 0
WEEKDAY_MAX = 6


def _validate_rule(
    *,
    recurrence_type: str,
    start_date: dt.date,
    end_date: Optional[dt.date],
    weekdays: Optional[list],
    interval_n: Optional[int],
    interval_unit: Optional[str],
    monthly_day: Optional[int],
) -> None:
    if recurrence_type not in {v for v, _ in RecurrenceType.choices}:
        raise ValidationError(f"Invalid recurrence_type: {recurrence_type}")
    if end_date and end_date < start_date:
        raise ValidationError("end_date must be on or after start_date")

    if recurrence_type == RecurrenceType.WEEKLY_DAYS:
        if not weekdays:
            raise ValidationError("weekly_days requires at least one weekday")
        for d in weekdays:
            if not isinstance(d, int) or d < WEEKDAY_MIN or d > WEEKDAY_MAX:
                raise ValidationError("weekdays must be integers in 0..6")
    elif recurrence_type == RecurrenceType.EVERY_N:
        if not interval_n or interval_n < 1:
            raise ValidationError("every_n requires interval_n >= 1")
        if interval_unit not in {v for v, _ in IntervalUnit.choices}:
            raise ValidationError("every_n requires a valid interval_unit")
    elif recurrence_type == RecurrenceType.MONTHLY_DAY:
        if not monthly_day or monthly_day < 1 or monthly_day > 31:
            raise ValidationError("monthly_day requires day in 1..31")


def _normalize_rule_fields(recurrence_type: str, fields: dict) -> dict:
    """Null out fields that don't apply to the chosen recurrence type so
    we don't carry stale data when a routine's rule is changed."""
    cleaned = dict(fields)
    if recurrence_type != RecurrenceType.WEEKLY_DAYS:
        cleaned["weekdays"] = []
    if recurrence_type != RecurrenceType.EVERY_N:
        cleaned["interval_n"] = None
        cleaned["interval_unit"] = ""
    if recurrence_type != RecurrenceType.MONTHLY_DAY:
        cleaned["monthly_day"] = None
    return cleaned


def list_routines(
    user_id: uuid.UUID, *, include_archived: bool = True
) -> list[Routine]:
    qs = Routine.objects.filter(user_id=user_id)
    if not include_archived:
        qs = qs.filter(archived=False)
    return list(qs.order_by("archived", "-created"))


def list_recent_occurrences(
    user_id: uuid.UUID, *, days: int = 90
) -> list[RoutineOccurrence]:
    cutoff = timezone.now().date() - dt.timedelta(days=max(1, int(days)))
    return list(
        RoutineOccurrence.objects.filter(
            user_id=user_id, scheduled_date__gte=cutoff
        ).order_by("-scheduled_date")
    )


def get_routine(user_id: uuid.UUID, routine_id) -> Routine:
    obj = Routine.objects.filter(pk=routine_id, user_id=user_id).first()
    if obj is None:
        raise NotFoundError("Routine not found")
    return obj


def create_routine(
    user_id: uuid.UUID,
    *,
    title: str,
    recurrence_type: str,
    start_date: dt.date,
    description: str = "",
    end_date: Optional[dt.date] = None,
    weekdays: Optional[list] = None,
    interval_n: Optional[int] = None,
    interval_unit: Optional[str] = None,
    monthly_day: Optional[int] = None,
) -> Routine:
    _validate_rule(
        recurrence_type=recurrence_type,
        start_date=start_date,
        end_date=end_date,
        weekdays=weekdays,
        interval_n=interval_n,
        interval_unit=interval_unit,
        monthly_day=monthly_day,
    )
    cleaned = _normalize_rule_fields(
        recurrence_type,
        {
            "weekdays": weekdays or [],
            "interval_n": interval_n,
            "interval_unit": interval_unit or "",
            "monthly_day": monthly_day,
        },
    )
    routine = Routine.objects.create(
        user_id=user_id,
        title=title,
        description=description or "",
        recurrence_type=recurrence_type,
        start_date=start_date,
        end_date=end_date,
        **cleaned,
    )
    log_event(
        user_id,
        kind=ActivityKind.ROUTINE_CREATED,
        entity_id=routine.id,
        entity_title=routine.title,
    )
    bump_context_version(user_id)
    return routine


def update_routine(
    user_id: uuid.UUID,
    routine_id,
    *,
    title: str,
    recurrence_type: str,
    start_date: dt.date,
    description: str = "",
    end_date: Optional[dt.date] = None,
    weekdays: Optional[list] = None,
    interval_n: Optional[int] = None,
    interval_unit: Optional[str] = None,
    monthly_day: Optional[int] = None,
) -> Routine:
    routine = get_routine(user_id, routine_id)
    _validate_rule(
        recurrence_type=recurrence_type,
        start_date=start_date,
        end_date=end_date,
        weekdays=weekdays,
        interval_n=interval_n,
        interval_unit=interval_unit,
        monthly_day=monthly_day,
    )
    cleaned = _normalize_rule_fields(
        recurrence_type,
        {
            "weekdays": weekdays or [],
            "interval_n": interval_n,
            "interval_unit": interval_unit or "",
            "monthly_day": monthly_day,
        },
    )
    routine.title = title
    routine.description = description or ""
    routine.recurrence_type = recurrence_type
    routine.start_date = start_date
    routine.end_date = end_date
    routine.weekdays = cleaned["weekdays"]
    routine.interval_n = cleaned["interval_n"]
    routine.interval_unit = cleaned["interval_unit"]
    routine.monthly_day = cleaned["monthly_day"]
    routine.save()
    bump_context_version(user_id)
    return routine


def archive_routine(
    user_id: uuid.UUID, routine_id, *, archived: bool
) -> Routine:
    routine = get_routine(user_id, routine_id)
    routine.archived = bool(archived)
    routine.save(update_fields=["archived"])
    bump_context_version(user_id)
    return routine


def delete_routine(user_id: uuid.UUID, routine_id) -> None:
    routine = (
        Routine.objects.filter(pk=routine_id, user_id=user_id)
        .only("id", "title")
        .first()
    )
    Routine.objects.filter(pk=routine_id, user_id=user_id).delete()
    if routine is not None:
        log_event(
            user_id,
            kind=ActivityKind.ROUTINE_DELETED,
            entity_id=routine.id,
            entity_title=routine.title,
        )
    bump_context_version(user_id)


# ---------- Recurrence computation ----------


def _clamp_month_day(year: int, month: int, day: int) -> dt.date:
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(day, last))


def _add_months(d: dt.date, months: int) -> dt.date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    return _clamp_month_day(year, month, d.day)


def compute_due_dates(
    routine: Routine, from_date: dt.date, to_date: dt.date
) -> list[dt.date]:
    """Pure function: return the list of scheduled dates for this routine
    within [from_date, to_date] inclusive. No DB access."""
    if from_date > to_date:
        return []
    rng_start = max(from_date, routine.start_date)
    rng_end = to_date
    if routine.end_date and routine.end_date < rng_end:
        rng_end = routine.end_date
    if rng_start > rng_end:
        return []

    rtype = routine.recurrence_type

    if rtype == RecurrenceType.ONCE:
        return [routine.start_date] if from_date <= routine.start_date <= to_date else []

    if rtype == RecurrenceType.WEEKLY_DAYS:
        wanted = set(int(d) for d in (routine.weekdays or []))
        if not wanted:
            return []
        out: list[dt.date] = []
        cur = rng_start
        while cur <= rng_end:
            if cur.weekday() in wanted:
                out.append(cur)
            cur += dt.timedelta(days=1)
        return out

    if rtype == RecurrenceType.EVERY_N:
        n = max(1, int(routine.interval_n or 1))
        unit = routine.interval_unit
        out = []
        cur = routine.start_date
        # Step forward in raw units until we clear `rng_end`.
        while cur <= rng_end:
            if cur >= rng_start:
                out.append(cur)
            if unit == IntervalUnit.DAYS:
                cur = cur + dt.timedelta(days=n)
            elif unit == IntervalUnit.WEEKS:
                cur = cur + dt.timedelta(weeks=n)
            elif unit == IntervalUnit.MONTHS:
                cur = _add_months(cur, n)
            else:
                break
        return out

    if rtype == RecurrenceType.MONTHLY_DAY:
        day = max(1, min(31, int(routine.monthly_day or routine.start_date.day)))
        out = []
        # Walk month-by-month from start_date's month up to rng_end.
        y, m = routine.start_date.year, routine.start_date.month
        end_y, end_m = rng_end.year, rng_end.month
        while (y, m) <= (end_y, end_m):
            candidate = _clamp_month_day(y, m, day)
            if (
                candidate >= routine.start_date
                and rng_start <= candidate <= rng_end
            ):
                out.append(candidate)
            # Advance one month
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1
        return out

    return []


def list_due_in_range(
    user_id: uuid.UUID, from_date: dt.date, to_date: dt.date
) -> list[dict]:
    """For each active routine, list its due dates in the range and pair
    them with the matching RoutineOccurrence (if already completed)."""
    routines = [
        r
        for r in Routine.objects.filter(user_id=user_id, archived=False)
    ]
    if not routines:
        return []
    occurrences = {
        (occ.routine_id, occ.scheduled_date): occ
        for occ in RoutineOccurrence.objects.filter(
            user_id=user_id,
            routine_id__in=[r.id for r in routines],
            scheduled_date__gte=from_date,
            scheduled_date__lte=to_date,
        )
    }
    items: list[dict] = []
    for r in routines:
        for d in compute_due_dates(r, from_date, to_date):
            occ = occurrences.get((r.id, d))
            items.append(
                {
                    "routine_id": r.id,
                    "scheduled_date": d,
                    "occurrence_id": occ.id if occ else None,
                }
            )
    items.sort(key=lambda x: (x["scheduled_date"], str(x["routine_id"])))
    return items


# ---------- Occurrence mutations ----------


def complete_occurrence(
    user_id: uuid.UUID,
    routine_id,
    *,
    scheduled_date: dt.date,
    note: str = "",
) -> RoutineOccurrence:
    routine = get_routine(user_id, routine_id)
    occ, created = RoutineOccurrence.objects.get_or_create(
        user_id=user_id,
        routine=routine,
        scheduled_date=scheduled_date,
        defaults={"completed_at": timezone.now(), "note": note or ""},
    )
    if not created:
        # Idempotent: refresh completion timestamp and note.
        occ.completed_at = timezone.now()
        if note:
            occ.note = note
        occ.save(update_fields=["completed_at", "note"])
    if created and routine.recurrence_type == RecurrenceType.ONCE:
        routine.archived = True
        routine.save(update_fields=["archived"])
    log_event(
        user_id,
        kind=ActivityKind.ROUTINE_COMPLETED,
        entity_id=routine.id,
        entity_title=routine.title,
    )
    bump_context_version(user_id)
    return occ


def uncomplete_occurrence(user_id: uuid.UUID, occurrence_id) -> None:
    occ = RoutineOccurrence.objects.filter(
        pk=occurrence_id, user_id=user_id
    ).first()
    if occ is None:
        return
    routine_id = occ.routine_id
    occ.delete()
    # If the originating routine was a ONCE that got auto-archived, unarchive it.
    Routine.objects.filter(
        pk=routine_id,
        user_id=user_id,
        recurrence_type=RecurrenceType.ONCE,
        archived=True,
    ).update(archived=False)
    bump_context_version(user_id)

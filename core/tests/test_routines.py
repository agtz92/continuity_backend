"""Tests for routines: recurrence math and GraphQL surface."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from core.models import (
    IntervalUnit,
    RecurrenceType,
    Routine,
    RoutineOccurrence,
)
from core.services import routines as routines_svc


# ---------- compute_due_dates (pure function) ----------


def _make_routine(**overrides) -> Routine:
    """Build an unsaved Routine instance for pure-function tests."""
    defaults = dict(
        title="r",
        description="",
        recurrence_type=RecurrenceType.ONCE,
        start_date=dt.date(2026, 1, 1),
        end_date=None,
        weekdays=[],
        interval_n=None,
        interval_unit="",
        monthly_day=None,
        archived=False,
    )
    defaults.update(overrides)
    return Routine(**defaults)


def test_compute_once_in_range():
    r = _make_routine(
        recurrence_type=RecurrenceType.ONCE, start_date=dt.date(2026, 1, 5)
    )
    assert routines_svc.compute_due_dates(
        r, dt.date(2026, 1, 1), dt.date(2026, 1, 10)
    ) == [dt.date(2026, 1, 5)]


def test_compute_once_outside_range():
    r = _make_routine(
        recurrence_type=RecurrenceType.ONCE, start_date=dt.date(2026, 1, 5)
    )
    assert routines_svc.compute_due_dates(
        r, dt.date(2026, 2, 1), dt.date(2026, 2, 28)
    ) == []


def test_compute_weekly_days_mon_thu_sun():
    # Anchor on a Monday: 2026-01-05
    r = _make_routine(
        recurrence_type=RecurrenceType.WEEKLY_DAYS,
        start_date=dt.date(2026, 1, 5),
        weekdays=[0, 3, 6],  # mon, thu, sun
    )
    out = routines_svc.compute_due_dates(
        r, dt.date(2026, 1, 5), dt.date(2026, 1, 18)
    )
    # Week 1: mon 5, thu 8, sun 11 — Week 2: mon 12, thu 15, sun 18
    assert out == [
        dt.date(2026, 1, 5),
        dt.date(2026, 1, 8),
        dt.date(2026, 1, 11),
        dt.date(2026, 1, 12),
        dt.date(2026, 1, 15),
        dt.date(2026, 1, 18),
    ]


def test_compute_weekly_days_skips_before_start():
    r = _make_routine(
        recurrence_type=RecurrenceType.WEEKLY_DAYS,
        start_date=dt.date(2026, 1, 10),  # a Saturday
        weekdays=[0, 5],  # mon, sat
    )
    out = routines_svc.compute_due_dates(
        r, dt.date(2026, 1, 1), dt.date(2026, 1, 14)
    )
    # First valid date is the Saturday 2026-01-10 (start_date), then Mon 12.
    assert out == [dt.date(2026, 1, 10), dt.date(2026, 1, 12)]


def test_compute_every_n_days():
    r = _make_routine(
        recurrence_type=RecurrenceType.EVERY_N,
        start_date=dt.date(2026, 1, 1),
        interval_n=3,
        interval_unit=IntervalUnit.DAYS,
    )
    out = routines_svc.compute_due_dates(
        r, dt.date(2026, 1, 1), dt.date(2026, 1, 12)
    )
    assert out == [
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 4),
        dt.date(2026, 1, 7),
        dt.date(2026, 1, 10),
    ]


def test_compute_every_n_weeks():
    r = _make_routine(
        recurrence_type=RecurrenceType.EVERY_N,
        start_date=dt.date(2026, 1, 1),
        interval_n=2,
        interval_unit=IntervalUnit.WEEKS,
    )
    out = routines_svc.compute_due_dates(
        r, dt.date(2026, 1, 1), dt.date(2026, 2, 28)
    )
    assert out == [
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 15),
        dt.date(2026, 1, 29),
        dt.date(2026, 2, 12),
        dt.date(2026, 2, 26),
    ]


def test_compute_every_n_months():
    r = _make_routine(
        recurrence_type=RecurrenceType.EVERY_N,
        start_date=dt.date(2026, 1, 15),
        interval_n=1,
        interval_unit=IntervalUnit.MONTHS,
    )
    out = routines_svc.compute_due_dates(
        r, dt.date(2026, 1, 1), dt.date(2026, 4, 30)
    )
    assert out == [
        dt.date(2026, 1, 15),
        dt.date(2026, 2, 15),
        dt.date(2026, 3, 15),
        dt.date(2026, 4, 15),
    ]


def test_compute_monthly_day_clamps_february():
    # Day 31 of every month → clamp to last day of February.
    r = _make_routine(
        recurrence_type=RecurrenceType.MONTHLY_DAY,
        start_date=dt.date(2026, 1, 1),
        monthly_day=31,
    )
    out = routines_svc.compute_due_dates(
        r, dt.date(2026, 1, 1), dt.date(2026, 4, 30)
    )
    assert out == [
        dt.date(2026, 1, 31),
        dt.date(2026, 2, 28),
        dt.date(2026, 3, 31),
        dt.date(2026, 4, 30),
    ]


def test_compute_respects_end_date():
    r = _make_routine(
        recurrence_type=RecurrenceType.EVERY_N,
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 1, 7),
        interval_n=2,
        interval_unit=IntervalUnit.DAYS,
    )
    out = routines_svc.compute_due_dates(
        r, dt.date(2026, 1, 1), dt.date(2026, 1, 31)
    )
    assert out == [
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 3),
        dt.date(2026, 1, 5),
        dt.date(2026, 1, 7),
    ]


# ---------- Service layer (DB-backed) ----------


@pytest.mark.django_db
def test_create_routine_validation_weekly_requires_days(user_a):
    with pytest.raises(ValidationError):
        routines_svc.create_routine(
            user_a,
            title="r",
            recurrence_type=RecurrenceType.WEEKLY_DAYS,
            start_date=dt.date(2026, 1, 1),
            weekdays=[],
        )


@pytest.mark.django_db
def test_create_routine_strips_unrelated_fields(user_a):
    r = routines_svc.create_routine(
        user_a,
        title="weekly",
        recurrence_type=RecurrenceType.WEEKLY_DAYS,
        start_date=dt.date(2026, 1, 5),
        weekdays=[0, 3],
        interval_n=99,
        interval_unit=IntervalUnit.DAYS,
        monthly_day=15,
    )
    assert r.interval_n is None
    assert r.interval_unit == ""
    assert r.monthly_day is None
    assert r.weekdays == [0, 3]


@pytest.mark.django_db
def test_complete_occurrence_marks_once_archived(user_a):
    r = routines_svc.create_routine(
        user_a,
        title="electrician",
        recurrence_type=RecurrenceType.ONCE,
        start_date=dt.date(2026, 5, 13),
    )
    routines_svc.complete_occurrence(
        user_a, r.id, scheduled_date=dt.date(2026, 5, 13)
    )
    r.refresh_from_db()
    assert r.archived is True


@pytest.mark.django_db
def test_complete_occurrence_is_idempotent(user_a):
    r = routines_svc.create_routine(
        user_a,
        title="water",
        recurrence_type=RecurrenceType.WEEKLY_DAYS,
        start_date=dt.date(2026, 5, 11),
        weekdays=[0],
    )
    routines_svc.complete_occurrence(
        user_a, r.id, scheduled_date=dt.date(2026, 5, 11)
    )
    routines_svc.complete_occurrence(
        user_a, r.id, scheduled_date=dt.date(2026, 5, 11)
    )
    assert RoutineOccurrence.objects.filter(routine=r).count() == 1


@pytest.mark.django_db
def test_list_due_in_range_marks_completed_occurrences(user_a):
    r = routines_svc.create_routine(
        user_a,
        title="water",
        recurrence_type=RecurrenceType.WEEKLY_DAYS,
        start_date=dt.date(2026, 5, 11),
        weekdays=[0, 3],
    )
    routines_svc.complete_occurrence(
        user_a, r.id, scheduled_date=dt.date(2026, 5, 11)
    )
    items = routines_svc.list_due_in_range(
        user_a, dt.date(2026, 5, 11), dt.date(2026, 5, 14)
    )
    by_date = {it["scheduled_date"]: it for it in items}
    assert by_date[dt.date(2026, 5, 11)]["occurrence_id"] is not None
    assert by_date[dt.date(2026, 5, 14)]["occurrence_id"] is None


@pytest.mark.django_db
def test_uncomplete_unarchives_once(user_a):
    r = routines_svc.create_routine(
        user_a,
        title="electrician",
        recurrence_type=RecurrenceType.ONCE,
        start_date=dt.date(2026, 5, 13),
    )
    occ = routines_svc.complete_occurrence(
        user_a, r.id, scheduled_date=dt.date(2026, 5, 13)
    )
    routines_svc.uncomplete_occurrence(user_a, occ.id)
    r.refresh_from_db()
    assert r.archived is False

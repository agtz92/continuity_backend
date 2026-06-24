"""Calendar integration — RRULE mapping, ICS feed, and feed-token tests.

Covers the pure event-mapping (calendar_export), the ICS document
(calendar_feed) and the public feed-token lookup. The Google/iCloud push paths
hit external APIs and are not exercised here (only their pure helpers are).
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from core.models import Routine, Task
from core.services import calendar_export, calendar_feed
from core.notifications.models import NotificationSettings


# ---------- RRULE mapping ----------


@pytest.mark.django_db
def test_weekly_days_rrule(user_a):
    r = Routine.objects.create(
        user_id=user_a,
        title="Gym",
        recurrence_type="weekly_days",
        start_date=dt.date(2026, 6, 1),
        weekdays=[0, 2, 4],
    )
    assert calendar_export.routine_rrule(r) == "FREQ=WEEKLY;BYDAY=MO,WE,FR"


@pytest.mark.django_db
def test_every_n_weeks_rrule_with_until(user_a):
    r = Routine.objects.create(
        user_id=user_a,
        title="Riego",
        recurrence_type="every_n",
        start_date=dt.date(2026, 6, 1),
        interval_n=3,
        interval_unit="weeks",
        end_date=dt.date(2026, 12, 31),
    )
    assert calendar_export.routine_rrule(r) == "FREQ=WEEKLY;INTERVAL=3;UNTIL=20261231"


@pytest.mark.django_db
def test_monthly_day_rrule(user_a):
    r = Routine.objects.create(
        user_id=user_a,
        title="Finanzas",
        recurrence_type="monthly_day",
        start_date=dt.date(2026, 6, 15),
        monthly_day=15,
    )
    assert calendar_export.routine_rrule(r) == "FREQ=MONTHLY;BYMONTHDAY=15"


@pytest.mark.django_db
def test_once_has_no_rrule(user_a):
    r = Routine.objects.create(
        user_id=user_a,
        title="Mudanza",
        recurrence_type="once",
        start_date=dt.date(2026, 6, 20),
    )
    assert calendar_export.routine_rrule(r) is None


# ---------- task/routine event mapping ----------


@pytest.mark.django_db
def test_task_without_time_is_all_day(user_a):
    t = Task.objects.create(
        user_id=user_a, title="Pagar renta", due_date=dt.datetime(2026, 6, 25, 0, 0)
    )
    ev = calendar_export.task_to_event(t)
    assert ev is not None and ev.all_day is True
    assert ev.start == dt.date(2026, 6, 25)
    assert ev.end == dt.date(2026, 6, 26)  # DTEND exclusive


@pytest.mark.django_db
def test_task_with_time_is_timed(user_a):
    t = Task.objects.create(
        user_id=user_a,
        title="Junta",
        due_date=dt.datetime(2026, 6, 25, 0, 0),
        due_time=dt.time(9, 0),
        duration_minutes=45,
    )
    ev = calendar_export.task_to_event(t)
    assert ev is not None and ev.all_day is False
    assert ev.start == dt.datetime(2026, 6, 25, 9, 0)
    assert ev.end == dt.datetime(2026, 6, 25, 9, 45)


@pytest.mark.django_db
def test_done_task_and_no_due_are_skipped(user_a):
    done = Task.objects.create(
        user_id=user_a, title="x", due_date=dt.datetime(2026, 6, 25, 0, 0), done=True
    )
    no_due = Task.objects.create(user_id=user_a, title="y")
    assert calendar_export.task_to_event(done) is None
    assert calendar_export.task_to_event(no_due) is None


# ---------- ICS feed + token ----------


@pytest.mark.django_db
def test_build_ics_contains_events_and_rrule(user_a):
    Task.objects.create(
        user_id=user_a, title="Pagar renta", due_date=dt.datetime(2026, 6, 25, 0, 0)
    )
    Routine.objects.create(
        user_id=user_a,
        title="Gym",
        recurrence_type="weekly_days",
        start_date=dt.date(2026, 6, 1),
        weekdays=[0, 2, 4],
    )
    ics = calendar_feed.build_ics(user_a).decode()
    assert "BEGIN:VCALENDAR" in ics
    assert "SUMMARY:Pagar renta" in ics
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR" in ics


@pytest.mark.django_db
def test_feed_toggles_exclude_routines(user_a):
    NotificationSettings.objects.create(
        user_id=user_a, calendar_sync_tasks=True, calendar_sync_routines=False
    )
    Task.objects.create(
        user_id=user_a, title="Solo task", due_date=dt.datetime(2026, 6, 25, 0, 0)
    )
    Routine.objects.create(
        user_id=user_a,
        title="Oculta",
        recurrence_type="weekly_days",
        start_date=dt.date(2026, 6, 1),
        weekdays=[0],
    )
    ics = calendar_feed.build_ics(user_a).decode()
    assert "SUMMARY:Solo task" in ics
    assert "Oculta" not in ics


@pytest.mark.django_db
def test_feed_token_roundtrip(user_a):
    token = calendar_feed.get_or_create_feed_token(user_a)
    assert token
    assert calendar_feed.user_for_token(token) == user_a
    # Rotating invalidates the old token.
    new = calendar_feed.regenerate_feed_token(user_a)
    assert new != token
    assert calendar_feed.user_for_token(token) is None
    assert calendar_feed.user_for_token(new) == user_a

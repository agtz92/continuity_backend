"""Shared calendar-export helpers.

Pure-ish logic that turns Continuity tasks and routines into calendar events,
reused by both the ICS subscription feed (``calendar_feed``) and the direct
Google Calendar API push (``google_calendar``).

Design notes:
- Continuity entities have no time-of-day by default. A task/routine with no
  time maps to an **all-day** event (date only). When a time IS set, it maps to
  a timed event running ``duration_minutes`` (default 30) in the user's tz.
- Routines are exported as a SINGLE recurring event with an iCalendar RRULE
  derived from the recurrence rule — the calendar expands the occurrences, so we
  never push one event per day.
- Times are emitted as **floating local time** (naive datetimes): personal
  calendars render them in the viewer's local zone, which is what users expect.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Optional

from ..models import Routine, Task
from ..models import RecurrenceType, IntervalUnit


DEFAULT_DURATION_MINUTES = 30
# Python weekday() index (0=Mon) → iCalendar BYDAY token.
_BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


@dataclass
class CalendarEvent:
    """A calendar event in a backend-neutral shape.

    ``start``/``end`` are ``date`` for all-day events or naive ``datetime`` for
    timed events. ``rrule`` is an iCalendar RRULE string (without the ``RRULE:``
    prefix) or None for single events.
    """

    uid: str
    summary: str
    all_day: bool
    start: dt.date
    end: dt.date
    description: str = ""
    rrule: Optional[str] = None
    source_kind: str = "task"  # "task" | "routine"
    source_id: str = ""


def _coerce_date(value) -> Optional[dt.date]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    return value


def task_to_event(task: Task) -> Optional[CalendarEvent]:
    """Map a task with a due date to a calendar event. Returns None if the task
    has no due date (can't be placed) or is already done."""
    due_date = _coerce_date(task.due_date)
    if due_date is None or task.done:
        return None
    summary = task.title or "(untitled)"
    if task.due_time is not None:
        start = dt.datetime.combine(due_date, task.due_time)
        minutes = task.duration_minutes or DEFAULT_DURATION_MINUTES
        end = start + dt.timedelta(minutes=minutes)
        return CalendarEvent(
            uid=f"task-{task.id}@continuu.it",
            summary=summary,
            all_day=False,
            start=start,
            end=end,
            source_kind="task",
            source_id=str(task.id),
        )
    # All-day: DTEND is exclusive in iCalendar, so it's the day after.
    return CalendarEvent(
        uid=f"task-{task.id}@continuu.it",
        summary=summary,
        all_day=True,
        start=due_date,
        end=due_date + dt.timedelta(days=1),
        source_kind="task",
        source_id=str(task.id),
    )


def routine_rrule(routine: Routine) -> Optional[str]:
    """Build an iCalendar RRULE (without prefix) for a routine, or None for a
    one-off (``ONCE``) routine, which is exported as a single event."""
    rtype = routine.recurrence_type
    parts: list[str] = []
    if rtype == RecurrenceType.ONCE:
        return None
    elif rtype == RecurrenceType.WEEKLY_DAYS:
        days = [int(d) for d in (routine.weekdays or []) if 0 <= int(d) <= 6]
        if not days:
            return None
        parts.append("FREQ=WEEKLY")
        parts.append("BYDAY=" + ",".join(_BYDAY[d] for d in sorted(days)))
    elif rtype == RecurrenceType.EVERY_N:
        n = max(1, int(routine.interval_n or 1))
        unit = routine.interval_unit
        freq = {
            IntervalUnit.DAYS: "DAILY",
            IntervalUnit.WEEKS: "WEEKLY",
            IntervalUnit.MONTHS: "MONTHLY",
        }.get(unit)
        if not freq:
            return None
        parts.append(f"FREQ={freq}")
        parts.append(f"INTERVAL={n}")
    elif rtype == RecurrenceType.MONTHLY_DAY:
        day = max(1, min(31, int(routine.monthly_day or routine.start_date.day)))
        parts.append("FREQ=MONTHLY")
        parts.append(f"BYMONTHDAY={day}")
    else:
        return None

    if routine.end_date:
        parts.append("UNTIL=" + routine.end_date.strftime("%Y%m%d"))
    return ";".join(parts)


def routine_to_event(routine: Routine) -> Optional[CalendarEvent]:
    """Map a routine to a (possibly recurring) calendar event. Skips archived."""
    if routine.archived:
        return None
    summary = routine.title or "(untitled)"
    rrule = routine_rrule(routine)
    start_date = routine.start_date
    if routine.time_of_day is not None:
        start = dt.datetime.combine(start_date, routine.time_of_day)
        minutes = routine.duration_minutes or DEFAULT_DURATION_MINUTES
        end = start + dt.timedelta(minutes=minutes)
        all_day = False
    else:
        start = start_date
        end = start_date + dt.timedelta(days=1)
        all_day = True
    return CalendarEvent(
        uid=f"routine-{routine.id}@continuu.it",
        summary=summary,
        all_day=all_day,
        start=start,
        end=end,
        description=routine.description or "",
        rrule=rrule,
        source_kind="routine",
        source_id=str(routine.id),
    )


def collect_events(
    user_id: uuid.UUID,
    *,
    include_tasks: bool = True,
    include_routines: bool = True,
) -> list[CalendarEvent]:
    """Gather every exportable calendar event for a user, honoring the
    per-entity-type toggles passed in."""
    events: list[CalendarEvent] = []
    if include_tasks:
        tasks = Task.objects.filter(
            user_id=user_id, done=False, due_date__isnull=False
        )
        for t in tasks:
            ev = task_to_event(t)
            if ev:
                events.append(ev)
    if include_routines:
        routines = Routine.objects.filter(user_id=user_id, archived=False)
        for r in routines:
            ev = routine_to_event(r)
            if ev:
                events.append(ev)
    return events


__all__ = [
    "CalendarEvent",
    "DEFAULT_DURATION_MINUTES",
    "task_to_event",
    "routine_to_event",
    "routine_rrule",
    "collect_events",
]

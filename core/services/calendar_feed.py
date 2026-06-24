"""ICS subscription feed for the calendar plugin.

Builds an iCalendar (.ics) document from a user's tasks and routines, served at
a public, token-authenticated URL. A single feed URL can be subscribed from
iCloud/iOS (Settings → Calendar → Add Subscribed Calendar), Google Calendar
("From URL") and Outlook — one implementation, every platform, no OAuth.

The feed is read-only and one-way (Continuity → calendar), which is exactly the
product's goal. Clients poll it on their own schedule (iOS controls the refresh
interval), so changes appear within hours, not instantly.
"""

from __future__ import annotations

import secrets
import uuid

from django.conf import settings as django_settings
from icalendar import Calendar, Event
from icalendar.prop import vRecur

from ..notifications.models import NotificationSettings
from . import calendar_export


def get_or_create_feed_token(user_id: uuid.UUID) -> str:
    """Return the user's ICS feed token, creating one on first use."""
    default_tz = getattr(
        django_settings, "NOTIFICATIONS_DEFAULT_TIMEZONE", "America/Mexico_City"
    )
    s, _ = NotificationSettings.objects.get_or_create(
        user_id=user_id, defaults={"timezone": default_tz}
    )
    if not s.calendar_feed_token:
        s.calendar_feed_token = secrets.token_urlsafe(24)
        s.save(update_fields=["calendar_feed_token"])
    return s.calendar_feed_token


def regenerate_feed_token(user_id: uuid.UUID) -> str:
    """Rotate the feed token, invalidating any previously shared URL."""
    s, _ = NotificationSettings.objects.get_or_create(user_id=user_id)
    s.calendar_feed_token = secrets.token_urlsafe(24)
    s.save(update_fields=["calendar_feed_token"])
    return s.calendar_feed_token


def feed_url(user_id: uuid.UUID) -> str:
    """Absolute subscription URL for the user's feed (webcal-friendly path)."""
    base = getattr(django_settings, "BACKEND_PUBLIC_URL", "").rstrip("/")
    token = get_or_create_feed_token(user_id)
    return f"{base}/api/calendar/feed/{token}.ics"


def _add_event(cal: Calendar, ev: calendar_export.CalendarEvent) -> None:
    item = Event()
    item.add("uid", ev.uid)
    item.add("summary", ev.summary)
    if ev.description:
        item.add("description", ev.description)
    # date objects → all-day (VALUE=DATE); naive datetimes → floating local time.
    item.add("dtstart", ev.start)
    item.add("dtend", ev.end)
    if ev.rrule:
        item.add("rrule", vRecur.from_ical(ev.rrule))
    cal.add_component(item)


def build_ics(user_id: uuid.UUID) -> bytes:
    """Render the user's tasks + routines as an iCalendar document.

    Honors the per-entity-type toggles in NotificationSettings. The master
    ``calendar_sync_enabled`` flag is NOT required to view the feed — possessing
    the token is the gate — but the toggles still scope what's included.
    """
    s = NotificationSettings.objects.filter(user_id=user_id).first()
    include_tasks = s.calendar_sync_tasks if s else True
    include_routines = s.calendar_sync_routines if s else True

    cal = Calendar()
    cal.add("prodid", "-//Continuity//Calendar Feed//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "Continuity")
    cal.add("x-wr-timezone", s.timezone if s else "UTC")

    for ev in calendar_export.collect_events(
        user_id,
        include_tasks=include_tasks,
        include_routines=include_routines,
    ):
        _add_event(cal, ev)

    return cal.to_ical()


def user_for_token(token: str) -> uuid.UUID | None:
    """Resolve a feed token to its owner, or None if unknown."""
    token = (token or "").strip()
    if not token:
        return None
    row = (
        NotificationSettings.objects.filter(calendar_feed_token=token)
        .only("user_id")
        .first()
    )
    return row.user_id if row else None


__all__ = [
    "get_or_create_feed_token",
    "regenerate_feed_token",
    "feed_url",
    "build_ics",
    "user_for_token",
]

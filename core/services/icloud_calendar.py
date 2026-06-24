"""iCloud CalDAV plugin service (optional, E3) — native write to iCloud.

Apple exposes no calendar OAuth/API for third parties, so we use CalDAV at
caldav.icloud.com with the user's Apple ID + an app-specific password. The
``caldav`` library is imported lazily so the app runs fine without it installed;
the feature simply reports as unavailable.

This is the heavier, credential-storing path. Most users are better served by
the ICS subscription feed (``calendar_feed``), which already covers iOS one-way.
"""

from __future__ import annotations

import logging
import uuid

from icalendar import Calendar, Event
from icalendar.prop import vRecur

from ..models import ICloudCalendarCredential, Routine, Task
from ..notifications.models import NotificationSettings
from . import calendar_export
from .google_tasks import GoogleTasksError, _decrypt, _encrypt

logger = logging.getLogger(__name__)

CALDAV_URL = "https://caldav.icloud.com"


class ICloudCalendarError(GoogleTasksError):
    """User-visible failure in the iCloud CalDAV plugin."""


class NotConnectedError(ICloudCalendarError):
    pass


def _caldav():
    try:
        import caldav  # noqa: WPS433 (lazy, optional dependency)
    except ImportError as e:  # pragma: no cover - depends on optional install
        raise ICloudCalendarError(
            "iCloud CalDAV support is not installed on the server"
        ) from e
    return caldav


def _client(apple_id: str, app_password: str):
    caldav = _caldav()
    return caldav.DAVClient(url=CALDAV_URL, username=apple_id, password=app_password)


def connect(user_id: uuid.UUID, apple_id: str, app_password: str) -> None:
    """Verify the credentials against iCloud and store them encrypted."""
    apple_id = (apple_id or "").strip()
    app_password = (app_password or "").strip()
    if not apple_id or not app_password:
        raise ICloudCalendarError("Apple ID and app-specific password are required")
    try:
        client = _client(apple_id, app_password)
        principal = client.principal()
        calendars = principal.calendars()
    except ICloudCalendarError:
        raise
    except Exception as e:  # pragma: no cover - network/auth dependent
        raise ICloudCalendarError(
            "Could not connect to iCloud — check the Apple ID and app password"
        ) from e
    default_url = str(calendars[0].url) if calendars else ""
    ICloudCalendarCredential.objects.update_or_create(
        user_id=user_id,
        defaults={
            "apple_id": apple_id,
            "app_password": _encrypt(app_password),
            "calendar_url": default_url,
        },
    )


def get_connection_status(user_id: uuid.UUID) -> dict | None:
    row = ICloudCalendarCredential.objects.filter(user_id=user_id).first()
    if row is None:
        return None
    return {"apple_id": row.apple_id, "connected_at": row.created}


def disconnect(user_id: uuid.UUID) -> None:
    ICloudCalendarCredential.objects.filter(user_id=user_id).delete()


def _event_to_ical(ev: calendar_export.CalendarEvent, tz: str) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Continuity//iCloud CalDAV//EN")
    cal.add("version", "2.0")
    item = Event()
    item.add("uid", ev.uid)
    item.add("summary", ev.summary)
    if ev.description:
        item.add("description", ev.description)
    item.add("dtstart", ev.start)
    item.add("dtend", ev.end)
    if ev.rrule:
        item.add("rrule", vRecur.from_ical(ev.rrule))
    cal.add_component(item)
    return cal.to_ical()


def sync_user(user_id: uuid.UUID) -> dict:
    """Push the user's tasks + routines into their iCloud calendar via CalDAV."""
    row = ICloudCalendarCredential.objects.filter(user_id=user_id).first()
    if row is None:
        raise NotConnectedError("iCloud Calendar is not connected")
    s = NotificationSettings.objects.filter(user_id=user_id).first()
    tz = (s.timezone if s else "UTC") or "UTC"
    include_tasks = s.calendar_sync_tasks if s else True
    include_routines = s.calendar_sync_routines if s else True

    client = _client(row.apple_id, _decrypt(row.app_password))
    principal = client.principal()
    calendar = None
    for c in principal.calendars():
        if str(c.url) == row.calendar_url:
            calendar = c
            break
    if calendar is None:
        cals = principal.calendars()
        if not cals:
            raise ICloudCalendarError("No iCloud calendars available")
        calendar = cals[0]

    pushed = 0
    for ev in calendar_export.collect_events(
        user_id, include_tasks=include_tasks, include_routines=include_routines
    ):
        try:
            calendar.save_event(_event_to_ical(ev, tz).decode("utf-8"))
            pushed += 1
        except Exception:  # pragma: no cover - network dependent
            logger.warning("iCloud push failed for %s", ev.uid, exc_info=True)
    return {"pushed": pushed}


__all__ = [
    "ICloudCalendarError",
    "NotConnectedError",
    "connect",
    "get_connection_status",
    "disconnect",
    "sync_user",
]

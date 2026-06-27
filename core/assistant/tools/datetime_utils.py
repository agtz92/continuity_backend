"""Parsing de fechas/horas y zona horaria del usuario para las tools del asistente.

Extraído de tools/write.py (ver AUDITORIA_CODIGO.md) para centralizar los parsers
de fecha que estaban dispersos y dejar las tools delgadas.
"""

import datetime as dt
import uuid  # noqa: F401  (tipo de user_id en las firmas)
from zoneinfo import ZoneInfo

from core.notifications.models import NotificationSettings

_DEFAULT_TZ = "America/Mexico_City"


def _parse_date(value) -> dt.date | None:
    """'YYYY-MM-DD' (or longer ISO) -> date; empty -> None."""
    if value in (None, ""):
        return None
    return dt.date.fromisoformat(str(value)[:10])


def _user_timezone(user_id: uuid.UUID) -> ZoneInfo | None:
    """The user's configured timezone, or None if zone data is unavailable."""
    row = (
        NotificationSettings.objects.filter(user_id=user_id)
        .only("timezone")
        .first()
    )
    name = (getattr(row, "timezone", "") or "").strip() or _DEFAULT_TZ
    for candidate in (name, _DEFAULT_TZ):
        try:
            return ZoneInfo(candidate)
        except Exception:  # noqa: BLE001 — bad/unknown zone, try the fallback
            continue
    return None


def _parse_due_dt(value, user_id: uuid.UUID) -> dt.datetime | None:
    """'YYYY-MM-DD' -> aware datetime at midnight of that day; empty -> None.

    Project/Task `due_date` columns are DateTimeFields. The rest of the app
    stores a picked date as midnight of the user's LOCAL day; anchoring it
    anywhere else (e.g. midnight UTC) makes the date render as the previous
    day for users west of UTC. So we anchor to midnight in the user's
    timezone. If zone data can't be loaded, noon UTC is a safe fallback —
    it lands on the intended calendar day in every realistic timezone.
    """
    d = _parse_date(value)
    if d is None:
        return None
    tz = _user_timezone(user_id)
    if tz is not None:
        return dt.datetime.combine(d, dt.time.min, tzinfo=tz)
    return dt.datetime.combine(d, dt.time(12, 0), tzinfo=dt.timezone.utc)


def _parse_time(value) -> dt.time | None:
    """'HH:MM' or 'HH:MM:SS' -> time; empty / unparseable -> None.

    Tasks (`due_time`) and routines (`time_of_day`) carry an OPTIONAL clock
    time. When set, the item is placed on the calendar's hourly day view;
    when omitted it stays all-day.
    """
    if not value:
        return None
    try:
        parts = [int(x) for x in str(value).split(":")]
    except ValueError:
        return None
    if not parts:
        return None
    hour = parts[0]
    minute = parts[1] if len(parts) > 1 else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return dt.time(hour=hour, minute=minute)

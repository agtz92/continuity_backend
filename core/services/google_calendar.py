"""Google Calendar plugin service — direct one-way push (Continuity → Google).

Reuses the OAuth plumbing of the Google Tasks plugin: same ``GoogleOAuthCredential``
row (a Google account can hold both scopes), same Fernet token encryption, same
HMAC-signed state, same ``/api/google/oauth/callback`` redirect endpoint. The
only new piece is the ``calendar.events`` scope, requested via incremental
authorization (``include_granted_scopes``), and the event push itself.

Tasks/routines are mirrored as calendar events; routines use a single recurring
event with an RRULE. Each entity stores ``calendar_event_id`` so re-syncs patch
instead of duplicating, and so completing/archiving/deleting removes the event.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from django.conf import settings
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from ..models import GoogleOAuthCredential, Routine, Task
from ..notifications.models import NotificationSettings
from . import calendar_export
from .google_tasks import (
    GoogleTasksError,
    NotConnectedError,
    _decrypt,
    _encrypt,
    _sign_state,
)

logger = logging.getLogger(__name__)

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleCalendarError(GoogleTasksError):
    """User-visible failure in the Google Calendar plugin."""


def _scopes_list(row: GoogleOAuthCredential) -> list[str]:
    return [s for s in (row.scopes or "").split(",") if s]


def _flow() -> Flow:
    if not (
        settings.GOOGLE_OAUTH_CLIENT_ID
        and settings.GOOGLE_OAUTH_CLIENT_SECRET
        and settings.GOOGLE_OAUTH_REDIRECT_URI
    ):
        raise GoogleCalendarError("Google OAuth is not configured on the server")
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
            }
        },
        scopes=[CALENDAR_SCOPE, "https://www.googleapis.com/auth/userinfo.email", "openid"],
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
    )


def build_authorization_url(user_id: uuid.UUID, return_to: str) -> str:
    from django.utils import timezone

    state = _sign_state(
        {
            "uid": str(user_id),
            "ret": return_to or "/settings/plugins/google-calendar",
            "iat": int(timezone.now().timestamp()),
        }
    )
    auth_url, _ = _flow().authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return auth_url


def get_connection_status(user_id: uuid.UUID) -> Optional[dict]:
    """Connected = a Google credential exists AND it carries the calendar scope."""
    row = GoogleOAuthCredential.objects.filter(user_id=user_id).first()
    if row is None or CALENDAR_SCOPE not in _scopes_list(row):
        return None
    return {"email": row.email, "connected_at": row.created}


def disconnect(user_id: uuid.UUID) -> None:
    """Drop the calendar scope (keep the credential for Google Tasks if present)
    and clear the chosen destination calendar. Also clears stored event ids so a
    future reconnect re-creates events cleanly."""
    row = GoogleOAuthCredential.objects.filter(user_id=user_id).first()
    if row is not None:
        remaining = [s for s in _scopes_list(row) if s != CALENDAR_SCOPE]
        if remaining:
            row.scopes = ",".join(remaining)
            row.save(update_fields=["scopes"])
        else:
            row.delete()
    NotificationSettings.objects.filter(user_id=user_id).update(google_calendar_id="")
    Task.objects.filter(user_id=user_id).exclude(calendar_event_id="").update(
        calendar_event_id=""
    )
    Routine.objects.filter(user_id=user_id).exclude(calendar_event_id="").update(
        calendar_event_id=""
    )


def _load_credentials(user_id: uuid.UUID) -> Credentials:
    row = GoogleOAuthCredential.objects.filter(user_id=user_id).first()
    if row is None or CALENDAR_SCOPE not in _scopes_list(row):
        raise NotConnectedError("Google Calendar is not connected")
    creds = Credentials(
        token=_decrypt(row.access_token) or None,
        refresh_token=_decrypt(row.refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=_scopes_list(row),
    )
    if row.token_expiry:
        creds.expiry = (
            row.token_expiry.replace(tzinfo=None)
            if row.token_expiry.tzinfo
            else row.token_expiry
        )
    if not creds.valid:
        creds.refresh(GoogleRequest())
        GoogleOAuthCredential.objects.filter(user_id=user_id).update(
            access_token=_encrypt(creds.token or ""),
            token_expiry=creds.expiry,
        )
    return creds


def _service(user_id: uuid.UUID):
    return build("calendar", "v3", credentials=_load_credentials(user_id), cache_discovery=False)


def list_calendars(user_id: uuid.UUID) -> list[dict]:
    svc = _service(user_id)
    out: list[dict] = []
    page_token = None
    while True:
        resp = svc.calendarList().list(pageToken=page_token).execute()
        for item in resp.get("items", []) or []:
            out.append(
                {
                    "id": item["id"],
                    "title": item.get("summaryOverride") or item.get("summary", ""),
                    "primary": bool(item.get("primary")),
                }
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def _target_calendar_id(user_id: uuid.UUID) -> str:
    s = NotificationSettings.objects.filter(user_id=user_id).only(
        "google_calendar_id", "timezone"
    ).first()
    cal_id = (s.google_calendar_id if s else "") or "primary"
    return cal_id


def _event_body(ev: calendar_export.CalendarEvent, tz: str) -> dict:
    body: dict = {"summary": ev.summary}
    if ev.description:
        body["description"] = ev.description
    if ev.all_day:
        body["start"] = {"date": ev.start.isoformat()}
        body["end"] = {"date": ev.end.isoformat()}
    else:
        body["start"] = {"dateTime": ev.start.isoformat(), "timeZone": tz}
        body["end"] = {"dateTime": ev.end.isoformat(), "timeZone": tz}
    if ev.rrule:
        body["recurrence"] = [f"RRULE:{ev.rrule}"]
    return body


def sync_user(user_id: uuid.UUID) -> dict:
    """Push the user's tasks + routines to their chosen Google calendar.

    Idempotent: inserts new events, patches existing ones (by stored event id),
    and deletes events for entities that are no longer exportable (task done /
    no due date, routine archived). Returns counts for logging.
    """
    s = NotificationSettings.objects.filter(user_id=user_id).first()
    if not s or not s.calendar_sync_enabled:
        return {"skipped": "sync_disabled"}
    if get_connection_status(user_id) is None:
        raise NotConnectedError("Google Calendar is not connected")

    svc = _service(user_id)
    cal_id = _target_calendar_id(user_id)
    tz = s.timezone or "UTC"
    created = updated = deleted = 0

    def _upsert(obj, ev) -> None:
        nonlocal created, updated
        body = _event_body(ev, tz)
        if obj.calendar_event_id:
            try:
                svc.events().patch(
                    calendarId=cal_id, eventId=obj.calendar_event_id, body=body
                ).execute()
                updated += 1
                return
            except Exception:
                logger.warning("patch failed, recreating event", exc_info=True)
        res = svc.events().insert(calendarId=cal_id, body=body).execute()
        obj.calendar_event_id = res.get("id", "")
        obj.save(update_fields=["calendar_event_id"])
        created += 1

    def _remove(obj) -> None:
        nonlocal deleted
        if not obj.calendar_event_id:
            return
        try:
            svc.events().delete(
                calendarId=cal_id, eventId=obj.calendar_event_id
            ).execute()
            deleted += 1
        except Exception:
            logger.warning("delete failed", exc_info=True)
        obj.calendar_event_id = ""
        obj.save(update_fields=["calendar_event_id"])

    if s.calendar_sync_tasks:
        for task in Task.objects.filter(user_id=user_id):
            ev = calendar_export.task_to_event(task)
            if ev is None:
                _remove(task)
            else:
                _upsert(task, ev)

    if s.calendar_sync_routines:
        for routine in Routine.objects.filter(user_id=user_id):
            ev = calendar_export.routine_to_event(routine)
            if ev is None:
                _remove(routine)
            else:
                _upsert(routine, ev)

    return {"created": created, "updated": updated, "deleted": deleted}


__all__ = [
    "GoogleCalendarError",
    "CALENDAR_SCOPE",
    "build_authorization_url",
    "get_connection_status",
    "disconnect",
    "list_calendars",
    "sync_user",
]

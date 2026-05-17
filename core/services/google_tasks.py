"""Google Tasks plugin service.

Handles the OAuth dance (state signing, code exchange, token refresh) and the
one-shot import: pull Google Tasks for a user, dedupe by ``google_task_id``,
and route each Google task list to the Continuity Project the user picked.

The user-facing decisions live in the GraphQL mutations / Django views — this
module is library-style code that those entry points call.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import uuid
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from ..models import GoogleOAuthCredential, Project, Task
from ._cache import bump_context_version
from . import projects as projects_svc

logger = logging.getLogger(__name__)


SCOPES = [
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


class GoogleTasksError(Exception):
    """Raised for any user-visible failure in this module."""


class NotConnectedError(GoogleTasksError):
    pass


class InvalidStateError(GoogleTasksError):
    pass


# ---------- Token encryption ----------


def _fernet() -> Fernet:
    raw = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def _encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise GoogleTasksError("Stored Google credential is unreadable") from e


# ---------- OAuth state (HMAC-signed) ----------


def _sign_state(payload: dict) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    sig = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), body, hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
    return f"{body.decode('ascii')}.{sig_b64.decode('ascii')}"


def _verify_state(state: str) -> dict:
    try:
        body_str, sig_str = state.split(".", 1)
    except ValueError as e:
        raise InvalidStateError("Malformed state") from e
    body = body_str.encode("ascii")
    expected = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected_b64 = base64.urlsafe_b64encode(expected).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(expected_b64, sig_str):
        raise InvalidStateError("State signature mismatch")
    padded = body + b"=" * (-len(body) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    issued_at = payload.get("iat")
    if not isinstance(issued_at, int) or (
        timezone.now().timestamp() - issued_at > 600
    ):
        raise InvalidStateError("State expired")
    return payload


# ---------- OAuth flow ----------


def _flow() -> Flow:
    if not (
        settings.GOOGLE_OAUTH_CLIENT_ID
        and settings.GOOGLE_OAUTH_CLIENT_SECRET
        and settings.GOOGLE_OAUTH_REDIRECT_URI
    ):
        raise GoogleTasksError(
            "Google OAuth is not configured on the server"
        )
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
        scopes=SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
    )


def build_authorization_url(user_id: uuid.UUID, return_to: str) -> str:
    state = _sign_state(
        {
            "uid": str(user_id),
            "ret": return_to or "/settings/plugins/google-tasks",
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


def exchange_code_and_store(code: str, state: str) -> tuple[uuid.UUID, str]:
    """Validate state, swap ``code`` for tokens, persist them, return (uid, return_to)."""
    payload = _verify_state(state)
    user_id = uuid.UUID(payload["uid"])
    return_to = payload.get("ret") or "/settings/plugins/google-tasks"

    flow = _flow()
    flow.fetch_token(code=code)
    creds: Credentials = flow.credentials

    if not creds.refresh_token:
        existing = GoogleOAuthCredential.objects.filter(user_id=user_id).first()
        refresh_token = _decrypt(existing.refresh_token) if existing else ""
        if not refresh_token:
            raise GoogleTasksError(
                "Google did not return a refresh token; disconnect and try again"
            )
    else:
        refresh_token = creds.refresh_token

    email = _fetch_email(creds)
    GoogleOAuthCredential.objects.update_or_create(
        user_id=user_id,
        defaults={
            "refresh_token": _encrypt(refresh_token),
            "access_token": _encrypt(creds.token or ""),
            "token_expiry": creds.expiry if creds.expiry else None,
            "scopes": ",".join(creds.scopes or SCOPES),
            "email": email or "",
        },
    )
    return user_id, return_to


def _fetch_email(creds: Credentials) -> str:
    try:
        svc = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = svc.userinfo().get().execute()
        return info.get("email", "") or ""
    except Exception:
        logger.exception("Failed to fetch Google account email")
        return ""


def disconnect(user_id: uuid.UUID) -> None:
    GoogleOAuthCredential.objects.filter(user_id=user_id).delete()


# ---------- Credential loading + Google API access ----------


def _load_credentials(user_id: uuid.UUID) -> Credentials:
    row = GoogleOAuthCredential.objects.filter(user_id=user_id).first()
    if row is None:
        raise NotConnectedError("Google Tasks is not connected")
    creds = Credentials(
        token=_decrypt(row.access_token) or None,
        refresh_token=_decrypt(row.refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=row.scopes.split(",") if row.scopes else SCOPES,
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


def get_connection_status(user_id: uuid.UUID) -> Optional[dict]:
    row = GoogleOAuthCredential.objects.filter(user_id=user_id).first()
    if row is None:
        return None
    return {"email": row.email, "connected_at": row.created}


def list_task_lists(user_id: uuid.UUID) -> list[dict]:
    creds = _load_credentials(user_id)
    svc = build("tasks", "v1", credentials=creds, cache_discovery=False)
    out: list[dict] = []
    page_token: Optional[str] = None
    while True:
        resp = svc.tasklists().list(maxResults=100, pageToken=page_token).execute()
        for item in resp.get("items", []) or []:
            out.append({"id": item["id"], "title": item.get("title", "")})
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


# ---------- Import ----------


def _parse_due(raw: Optional[str]) -> Optional[dt.datetime]:
    """Google Tasks returns ``due`` as an RFC3339 timestamp at 00:00 UTC, but
    the time component is meaningless — it's a date-only field. We keep it as a
    timezone-aware datetime since Continuity's Task.due_date is a DateTimeField."""
    if not raw:
        return None
    try:
        # "2025-05-20T00:00:00.000Z" → 2025-05-20T00:00:00+00:00
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_completed(raw: Optional[str]) -> Optional[dt.datetime]:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def import_tasks(user_id: uuid.UUID, mappings: list[dict]) -> dict:
    """Run a one-shot import for each (google_list_id → project) mapping.

    ``mappings`` items:
      - ``google_list_id``: required
      - ``project_id``: optional UUID — assign imported tasks to this project
      - ``new_project_name``: optional str — create a new project with this name
        (used when project_id is None and the user wants a fresh bucket)

    Returns: ``{imported, skipped, created_projects: [project names]}``.
    """
    creds = _load_credentials(user_id)
    svc = build("tasks", "v1", credentials=creds, cache_discovery=False)

    imported = 0
    skipped = 0
    created_projects: list[str] = []

    for mapping in mappings:
        google_list_id = mapping.get("google_list_id")
        if not google_list_id:
            continue
        project_id = _resolve_project(
            user_id,
            project_id=mapping.get("project_id"),
            new_project_name=mapping.get("new_project_name"),
            created_projects=created_projects,
        )

        page_token: Optional[str] = None
        while True:
            resp = (
                svc.tasks()
                .list(
                    tasklist=google_list_id,
                    showCompleted=True,
                    showHidden=True,
                    maxResults=100,
                    pageToken=page_token,
                )
                .execute()
            )
            for item in resp.get("items", []) or []:
                if item.get("kind") != "tasks#task":
                    continue
                gid = item.get("id")
                if not gid:
                    continue
                if Task.objects.filter(
                    user_id=user_id, google_task_id=gid
                ).exists():
                    skipped += 1
                    continue
                done = item.get("status") == "completed"
                Task.objects.create(
                    user_id=user_id,
                    project_id=project_id,
                    title=item.get("title", "") or "(untitled)",
                    due_date=_parse_due(item.get("due")),
                    done=done,
                    completed_at=_parse_completed(item.get("completed"))
                    if done
                    else None,
                    google_task_id=gid,
                )
                imported += 1
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    if imported:
        bump_context_version(user_id)

    return {
        "imported": imported,
        "skipped": skipped,
        "created_projects": created_projects,
    }


def _resolve_project(
    user_id: uuid.UUID,
    *,
    project_id: Optional[str],
    new_project_name: Optional[str],
    created_projects: list[str],
) -> Optional[uuid.UUID]:
    if project_id:
        pid = uuid.UUID(str(project_id))
        if not Project.objects.filter(pk=pid, user_id=user_id).exists():
            raise GoogleTasksError("Selected project no longer exists")
        return pid
    name = (new_project_name or "").strip()
    if not name:
        return None
    project = projects_svc.create_project(user_id, name=name, status="active")
    created_projects.append(project.name)
    return project.id


__all__ = [
    "GoogleTasksError",
    "NotConnectedError",
    "InvalidStateError",
    "build_authorization_url",
    "exchange_code_and_store",
    "disconnect",
    "get_connection_status",
    "list_task_lists",
    "import_tasks",
]

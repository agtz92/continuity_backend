"""Hard-delete all of a user's data + their Supabase auth account.

Backs the `deleteAccount` GraphQL mutation (Apple App Store requirement:
in-app account deletion). App data is removed in a single transaction, then the
Supabase auth user is deleted so the account can no longer sign in.

Every model that stores a `user_id` must appear either in `USER_OWNED_MODELS`
(deleted) or in `_anonymize_retained_records` (kept for billing/audit, stripped
of anything that points back to the person). `core/tests/test_account_deletion.py`
fails when a new model with a `user_id` field is in neither — that is the
guard that keeps the privacy policy's "we delete your content" true.

Note: this does NOT cancel the subscription at the store — the UI warns the user to
cancel billing on the web first.
"""

from __future__ import annotations

import logging
import uuid

from django.db import transaction

from core.admin_api import supabase_admin
from core.admin_api.models import AdminAuditLog
from core.announcements.models import Announcement, Status as AnnouncementStatus
from core.assistant.models import AccountProfile, Conversation, UsageDay
from core.billing.models import StoreWebhookEvent
from core.billing.store_webhooks import minimal_payload
from core.feedback.models import BugReport
from core.models import (
    Activity,
    BackupMeta,
    Category,
    GoogleOAuthCredential,
    GraveyardInsight,
    Idea,
    InteractionDay,
    NoteSection,
    OAuthAuthorizationCode,
    OAuthConnectionEvent,
    OAuthRefreshToken,
    OnboardingProgress,
    Profile,
    Project,
    ProjectNote,
    QuickNote,
    Routine,
    RoutineOccurrence,
    Task,
    TaskBlocker,
    UserPreferences,
)
from core.notifications.models import (
    EmailSend,
    ExpoPushToken,
    Notification,
    NotificationSettings,
)

log = logging.getLogger(__name__)

#: Deleted outright, child→parent. FKs are CASCADE/SET_NULL so cascades would
#: cover some of these, but listing every one keeps the erase obvious and lets
#: the test check it is complete. `Message` goes with `Conversation` (CASCADE).
USER_OWNED_MODELS = (
    # Content
    RoutineOccurrence,
    TaskBlocker,
    Activity,
    ProjectNote,
    NoteSection,
    QuickNote,
    Task,
    Routine,
    Project,
    Idea,
    Category,
    GraveyardInsight,
    # Assistant
    Conversation,
    UsageDay,
    AccountProfile,
    # Notifications + email
    Notification,
    ExpoPushToken,
    NotificationSettings,
    EmailSend,
    # Integrations + connector OAuth
    GoogleOAuthCredential,
    OAuthAuthorizationCode,
    OAuthRefreshToken,
    OAuthConnectionEvent,
    # Per-user singletons + telemetry
    BackupMeta,
    Profile,
    OnboardingProgress,
    UserPreferences,
    InteractionDay,
    # Feedback
    BugReport,
)

_REDACTED = {"redacted": "account_deleted"}


def _delete_app_data(user_id: uuid.UUID) -> None:
    """Delete every row owned by the user."""
    for model in USER_OWNED_MODELS:
        model.objects.filter(user_id=user_id).delete()


def _scrub_store_payload(payload: dict) -> dict:
    # Rows stored before ingest started trimming still carry the full body.
    return {**_REDACTED, **minimal_payload(payload)}


def _anonymize_retained_records(user_id: uuid.UUID) -> None:
    """Keep the rows the business still needs, minus the link to the person.

    - `StoreWebhookEvent`: payment records (and the dedupe key for store
      redeliveries) — blank `app_user_id`, keep only the accounting fields.
    - `AdminAuditLog` entries *about* the user: keep that the action happened,
      drop the before/after payload (it can hold emails or profile values).
      Entries where the user was the *actor* (admins, billing conflicts) stay
      as they are: they record what that account did.
    - `Announcement.audience_user_ids`: drop the id. An announcement that only
      targeted this user would fall back to "everyone" with an empty audience,
      so it is archived instead.
    """
    uid = str(user_id)

    for event in StoreWebhookEvent.objects.filter(app_user_id=uid):
        event.app_user_id = ""
        event.payload = _scrub_store_payload(event.payload or {})
        event.save(update_fields=["app_user_id", "payload"])

    AdminAuditLog.objects.filter(
        target_type__in=("user", "account_profile"), target_id=uid
    ).update(payload=_REDACTED)
    AdminAuditLog.objects.filter(
        target_type="mcp_connection", target_id__startswith=f"{uid}:"
    ).update(payload=_REDACTED)

    # JSON `contains` isn't portable (SQLite in tests), and announcements are a
    # handful of admin-authored rows, so filter in Python.
    for ann in Announcement.objects.exclude(audience_user_ids=[]):
        ids = [i for i in (ann.audience_user_ids or []) if str(i) != uid]
        if len(ids) == len(ann.audience_user_ids or []):
            continue
        ann.audience_user_ids = ids
        fields = ["audience_user_ids", "updated_at"]
        if not ids and not ann.audience_plans:
            ann.status = AnnouncementStatus.ARCHIVED
            fields.append("status")
        ann.save(update_fields=fields)


def delete_account(user_id: uuid.UUID) -> None:
    """Erase the user's app data, then delete their Supabase auth account.

    Data first (single transaction), then the auth user. If the auth delete
    fails the caller surfaces the error; the data is already gone, so a retry is
    a no-op on data and just re-attempts the auth delete. Idempotent.
    """
    with transaction.atomic():
        _delete_app_data(user_id)
        _anonymize_retained_records(user_id)
    log.info("account_deletion: app data erased user=%s", user_id)

    supabase_admin.delete_user(user_id)
    log.info("account_deletion: supabase auth user deleted user=%s", user_id)

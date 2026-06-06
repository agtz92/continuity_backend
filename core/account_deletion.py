"""Hard-delete all of a user's data + their Supabase auth account.

Backs the `deleteAccount` GraphQL mutation (Apple App Store requirement:
in-app account deletion). App data is removed in a single transaction, then the
Supabase auth user is deleted so the account can no longer sign in.

Note: this does NOT cancel a Stripe subscription — the UI warns the user to
cancel billing on the web first.
"""

from __future__ import annotations

import logging
import uuid

from django.db import transaction

from core.admin_api import supabase_admin
from core.assistant.models import AccountProfile, Conversation, UsageDay
from core.models import (
    Activity,
    BackupMeta,
    Category,
    GoogleOAuthCredential,
    Idea,
    OnboardingProgress,
    Profile,
    Project,
    ProjectNote,
    Routine,
    RoutineOccurrence,
    Task,
    TaskBlocker,
    UserPreferences,
)
from core.notifications.models import (
    ExpoPushToken,
    Notification,
    NotificationLink,
    NotificationSettings,
)

log = logging.getLogger(__name__)


def _delete_app_data(user_id: uuid.UUID) -> None:
    """Delete every row owned by the user. Child→parent order; FKs are all
    CASCADE/SET_NULL so cascades would cover most, but explicit deletes keep it
    obvious and complete."""
    RoutineOccurrence.objects.filter(user_id=user_id).delete()
    TaskBlocker.objects.filter(user_id=user_id).delete()
    Activity.objects.filter(user_id=user_id).delete()
    ProjectNote.objects.filter(user_id=user_id).delete()
    Task.objects.filter(user_id=user_id).delete()
    Routine.objects.filter(user_id=user_id).delete()
    Project.objects.filter(user_id=user_id).delete()
    Idea.objects.filter(user_id=user_id).delete()
    Category.objects.filter(user_id=user_id).delete()

    # Assistant
    Conversation.objects.filter(user_id=user_id).delete()  # cascades Message
    UsageDay.objects.filter(user_id=user_id).delete()
    AccountProfile.objects.filter(user_id=user_id).delete()

    # Notifications
    Notification.objects.filter(user_id=user_id).delete()
    NotificationLink.objects.filter(user_id=user_id).delete()
    ExpoPushToken.objects.filter(user_id=user_id).delete()
    NotificationSettings.objects.filter(user_id=user_id).delete()

    # Per-user singletons
    BackupMeta.objects.filter(user_id=user_id).delete()
    Profile.objects.filter(user_id=user_id).delete()
    OnboardingProgress.objects.filter(user_id=user_id).delete()
    UserPreferences.objects.filter(user_id=user_id).delete()
    GoogleOAuthCredential.objects.filter(user_id=user_id).delete()


def delete_account(user_id: uuid.UUID) -> None:
    """Erase the user's app data, then delete their Supabase auth account.

    Data first (single transaction), then the auth user. If the auth delete
    fails the caller surfaces the error; the data is already gone, so a retry is
    a no-op on data and just re-attempts the auth delete. Idempotent.
    """
    with transaction.atomic():
        _delete_app_data(user_id)
    log.info("account_deletion: app data erased user=%s", user_id)

    supabase_admin.delete_user(user_id)
    log.info("account_deletion: supabase auth user deleted user=%s", user_id)

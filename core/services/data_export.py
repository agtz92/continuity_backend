"""Full export of a person's data (right to data portability).

Unlike the dashboard backup — built in the client from what the dashboard
query happens to load, and meant to be re-imported — this is everything we
hold *about the person's content and settings*, straight from the database.

Every model listed in `account_deletion.USER_OWNED_MODELS` is either exported
here (`SECTIONS`) or deliberately skipped (`NOT_EXPORTED`, with the reason).
`core/tests/test_data_export.py` fails when a new user-owned model is in
neither, the same guard that keeps account deletion complete.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any, Iterable

from django.db import models
from django.utils import timezone

from core.assistant.models import AccountProfile, Conversation, Message, UsageDay
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

EXPORT_VERSION = 1

#: (key in the JSON, model). Order is the order the file reads in.
SECTIONS: tuple[tuple[str, type[models.Model]], ...] = (
    ("profile", Profile),
    ("preferences", UserPreferences),
    ("notification_settings", NotificationSettings),
    ("onboarding", OnboardingProgress),
    ("subscription", AccountProfile),
    ("categories", Category),
    ("projects", Project),
    ("project_notes", ProjectNote),
    ("tasks", Task),
    ("task_blockers", TaskBlocker),
    ("routines", Routine),
    ("routine_occurrences", RoutineOccurrence),
    ("ideas", Idea),
    ("quick_notes", QuickNote),
    ("quick_note_sections", NoteSection),
    ("activity", Activity),
    ("graveyard_insight", GraveyardInsight),
    ("assistant_conversations", Conversation),
    ("bug_reports", BugReport),
    ("connector_events", OAuthConnectionEvent),
    ("backup", BackupMeta),
)

#: Held for the person but left out of the file, and why.
NOT_EXPORTED: dict[type[models.Model], str] = {
    GoogleOAuthCredential: "access credential (tokens), not content",
    OAuthAuthorizationCode: "short-lived access credential",
    OAuthRefreshToken: "access credential",
    ExpoPushToken: "device address for push, not content",
    Notification: "copy of push notices already built from the data above",
    EmailSend: "delivery ledger of emails we sent",
    UsageDay: "assistant usage counters",
    InteractionDay: "daily activity counter",
}

#: Columns never written to the file even on exported models.
_SKIP_FIELDS = {"user_id"}

#: Models where only these columns go out: the rest are internal ids and
#: counters that mean nothing outside the app.
_ONLY_FIELDS: dict[type[models.Model], set[str]] = {
    AccountProfile: {
        "plan",
        "plan_renews_at",
        "billing_source",
        "cancel_at_period_end",
        "is_billing_exempt",
        "beta_cohort",
        "beta_enrolled_at",
    },
}


def _value(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, decimal.Decimal):
        return str(v)
    return v


def _row(obj: models.Model) -> dict[str, Any]:
    only = _ONLY_FIELDS.get(type(obj))
    out: dict[str, Any] = {}
    for f in obj._meta.concrete_fields:
        if f.name in _SKIP_FIELDS or (only is not None and f.name not in only):
            continue
        # FKs export the id under the column name (`project_id`), not the object.
        out[f.attname] = _value(getattr(obj, f.attname))
    return out


def _rows(model: type[models.Model], user_id: uuid.UUID) -> Iterable[models.Model]:
    if model is Conversation:
        return model.objects.filter(user_id=user_id).order_by("created")
    qs = model.objects.filter(user_id=user_id)
    ordering = "created" if any(f.name == "created" for f in model._meta.fields) else "pk"
    return qs.order_by(ordering)


def build_export(user_id: uuid.UUID, *, email: str = "") -> dict[str, Any]:
    data: dict[str, Any] = {
        "version": EXPORT_VERSION,
        "exported_at": timezone.now().isoformat(),
        "account": {"user_id": str(user_id), "email": email},
    }
    for key, model in SECTIONS:
        rows = [_row(o) for o in _rows(model, user_id)]
        if model is Conversation:
            messages: dict[str, list] = {}
            for m in Message.objects.filter(conversation__user_id=user_id).order_by("created"):
                messages.setdefault(str(m.conversation_id), []).append(_row(m))
            for r in rows:
                r["messages"] = messages.get(r["id"], [])
        data[key] = rows
    return data

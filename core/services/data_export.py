"""Full export of a person's data (right to data portability).

Unlike the dashboard backup — built in the client from what the dashboard
query happens to load, and meant to be re-imported — this is everything we
hold *about the person's content and settings*, straight from the database.

Every model listed in `account_deletion.USER_OWNED_MODELS` is either exported
here (`SECTIONS`) or deliberately skipped (`NOT_EXPORTED`, with the reason).
`core/tests/test_data_export.py` fails when a new user-owned model is in
neither, the same guard that keeps account deletion complete.

Columns go out by allowlist (`FIELDS`), never by default: the file must not
carry credentials, internal flags or anything that describes how the app is
built (assistant models, tool calls, token counts, sequential ids). The same
test fails when a column is in neither `FIELDS` nor `OMITTED_FIELDS`.
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

#: Allowlist: the only columns (by `attname`) that go out for each model.
#: A column added to a model stays out until someone puts it here or in
#: `OMITTED_FIELDS`; `test_data_export.py` fails while it is in neither.
FIELDS: dict[type[models.Model], tuple[str, ...]] = {
    Profile: ("avatar", "first_name", "updated_at"),
    UserPreferences: ("today_layout", "created", "updated_at"),
    NotificationSettings: (
        "locale", "theme", "palette", "timezone",
        "digest_enabled", "digest_day_of_week", "digest_hour",
        "daily_digest_enabled", "daily_digest_hour",
        "sleeping_alerts_enabled", "due_reminders_enabled", "due_reminder_hour",
        "manual_enabled", "push_enabled", "lifecycle_emails_enabled",
        "calendar_sync_enabled", "calendar_sync_tasks", "calendar_sync_routines",
        "google_calendar_id", "updated_at",
    ),
    OnboardingProgress: (
        "status", "completed_at", "completed_via", "tour_status",
        "tour_completed_at", "created",
    ),
    AccountProfile: ("plan", "plan_renews_at", "billing_source", "cancel_at_period_end"),
    Category: ("id", "created", "name", "color"),
    Project: (
        "id", "created", "name", "description", "why", "next_step", "status",
        "priority", "category_id", "last_activity", "promoted_from_idea_at",
        "due_date", "paused_context", "paused_next_action", "paused_blocker",
        "paused_at", "killed_reason", "killed_learnings", "killed_would_restart",
        "killed_at", "killed_ai_reflection", "stalled_at", "position",
    ),
    ProjectNote: ("id", "created", "project_id", "title", "body", "updated_at"),
    Task: (
        "id", "created", "project_id", "title", "due_date", "due_time", "done",
        "completed_at", "effort_hours", "duration_minutes", "position",
    ),
    TaskBlocker: ("id", "created", "blocked_task_id", "blocking_task_id", "external_description"),
    Routine: (
        "id", "created", "title", "description", "recurrence_type", "start_date",
        "end_date", "weekdays", "interval_n", "interval_unit", "monthly_day",
        "effort_hours", "archived", "time_of_day", "duration_minutes", "project_id",
    ),
    RoutineOccurrence: ("id", "created", "routine_id", "scheduled_date", "completed_at", "note"),
    Idea: ("id", "created", "title", "description", "why"),
    QuickNote: ("id", "created", "title", "category_id", "project_id", "pinned", "updated_at"),
    NoteSection: ("id", "created", "note_id", "heading", "body", "position", "collapsed", "updated_at"),
    Activity: (
        "id", "created", "kind", "entity_id", "entity_title", "project_id",
        "target_project_id", "note", "previous_value", "new_value",
    ),
    GraveyardInsight: ("body", "deaths_count", "computed_at"),
    Conversation: ("id", "title", "archived", "created", "updated_at"),
    BugReport: ("topic", "message", "platform", "created"),
    OAuthConnectionEvent: ("client_name", "event", "created"),
    BackupMeta: ("last_backup",),
}

#: Columns deliberately left out, and why. Besides `user_id` (everywhere):
#: secrets, internal flags, sync plumbing and anything that describes how the
#: app works rather than what the person stored.
OMITTED_FIELDS: dict[type[models.Model], dict[str, str]] = {
    NotificationSettings: {
        "is_admin": "internal role flag",
        "calendar_feed_token": "access credential for the calendar feed",
    },
    OnboardingProgress: {
        "current_step": "wizard plumbing",
        "example_seeded_at": "internal seed marker",
        "updated_at": "wizard plumbing",
    },
    AccountProfile: {
        "billing_customer_id": "billing provider id",
        "billing_transaction_id": "billing provider id",
        "billing_product_id": "billing provider id",
        "is_admin": "internal role flag",
        "is_billing_exempt": "internal billing flag",
        "billing_exempt_reason": "internal billing flag",
        "billing_exempt_until": "internal billing flag",
        "beta_cohort": "internal program flag",
        "beta_status": "internal program flag",
        "beta_enrolled_at": "internal program flag",
        "reclaim_warned_at": "internal program flag",
        "had_retention_offer": "internal billing flag",
        "context_version": "cache counter",
        "created": "internal",
        "updated_at": "internal",
    },
    Task: {
        "google_task_id": "sync id in another service",
        "calendar_event_id": "sync id in another service",
        "parked_due_date": "internal state",
        "parked_due_time": "internal state",
        "client_token": "client dedupe token",
    },
    Routine: {"calendar_event_id": "sync id in another service"},
    GraveyardInsight: {"is_stale": "cache flag", "updated_at": "cache timestamp"},
    BugReport: {
        "id": "sequential id",
        "status": "admin triage state",
        "updated_at": "admin triage state",
    },
    OAuthConnectionEvent: {"id": "sequential id", "client_id": "OAuth client id"},
}

#: Connector events that are plumbing (a refresh every token lifetime), not
#: something the person did.
_SKIPPED_CONNECTOR_EVENTS = {OAuthConnectionEvent.Event.TOKEN_REFRESHED}


def _value(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, decimal.Decimal):
        return str(v)
    return v


def _row(obj: models.Model) -> dict[str, Any]:
    # FKs export the id under the column name (`project_id`), not the object.
    return {name: _value(getattr(obj, name)) for name in FIELDS[type(obj)]}


def _message_row(m: Message) -> dict[str, Any] | None:
    """What was said, nothing about how: tool calls, tool results, model and
    token counts stay out. Their effects are already in `activity`."""
    blocks = m.content if isinstance(m.content, list) else []
    text = "\n\n".join(
        b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
    )
    if m.role not in ("user", "assistant") or not text:
        return None
    return {"role": m.role, "text": text, "created": _value(m.created)}


def _rows(model: type[models.Model], user_id: uuid.UUID) -> Iterable[models.Model]:
    qs = model.objects.filter(user_id=user_id)
    if model is OAuthConnectionEvent:
        qs = qs.exclude(event__in=_SKIPPED_CONNECTOR_EVENTS)
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
                if (row := _message_row(m)) is not None:
                    messages.setdefault(str(m.conversation_id), []).append(row)
            for r in rows:
                r["messages"] = messages.get(r["id"], [])
        data[key] = rows
    return data

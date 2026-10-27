"""`delete_account` erases everything the privacy policy says it erases.

Two kinds of guard:

* behavioural — seed one row in every user-owned table for two users, delete
  one, check nothing of theirs is left and nothing of the other user moved;
* structural — every model with a `*user_id*` field must be either deleted
  (`USER_OWNED_MODELS`) or listed here with the reason it survives. A new table
  that stores a user id fails `test_every_user_keyed_model_is_accounted_for`
  until someone decides what account deletion does with it.
"""

import datetime as dt
import uuid

import pytest
from django.apps import apps
from django.utils import timezone

from core import account_deletion
from core.account_deletion import USER_OWNED_MODELS, delete_account
from core.admin_api.models import AdminAuditLog
from core.announcements.models import Announcement, Status as AnnouncementStatus
from core.assistant.models import AccountProfile, Conversation, Message, UsageDay
from core.billing.models import StoreWebhookEvent
from core.cms.models import BlogPost, HelpResource, MediaAsset, Page
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
    OAuthClient,
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

#: Models that keep a user id after deletion, and why. Each one is anonymized
#: by `_anonymize_retained_records` or holds staff ids, not end users.
RETAINED_MODELS = {
    StoreWebhookEvent: "payment record; app_user_id blanked, payload scrubbed",
    AdminAuditLog: "audit trail; payload of entries about the user redacted",
    Announcement: "user id removed from audience_user_ids",
    BlogPost: "author_user_id is staff",
    Page: "author_user_id is staff",
    HelpResource: "author_user_id is staff",
    MediaAsset: "uploaded_by_user_id is staff",
}


@pytest.fixture(autouse=True)
def no_supabase(monkeypatch):
    calls = []
    monkeypatch.setattr(
        account_deletion.supabase_admin, "delete_user", lambda uid: calls.append(uid)
    )
    return calls


def _seed(user_id: uuid.UUID) -> set[type]:
    """One row in every user-owned table. Returns the models it touched."""
    now = timezone.now()
    today = dt.date.today()
    nonce = uuid.uuid4().hex

    category = Category.objects.create(user_id=user_id, name="Work")
    project = Project.objects.create(user_id=user_id, name="Launch", category=category)
    task = Task.objects.create(user_id=user_id, project=project, title="Ship it")
    other_task = Task.objects.create(user_id=user_id, project=project, title="Test it")
    TaskBlocker.objects.create(
        user_id=user_id, blocked_task=task, blocking_task=other_task
    )
    routine = Routine.objects.create(
        user_id=user_id, title="Review", recurrence_type="daily", start_date=today
    )
    RoutineOccurrence.objects.create(
        user_id=user_id, routine=routine, scheduled_date=today, completed_at=now
    )
    Activity.objects.create(user_id=user_id, kind="note", note="Private thought")
    ProjectNote.objects.create(user_id=user_id, project=project, title="Spec", body="…")
    note = QuickNote.objects.create(user_id=user_id, title="Journal", project=project)
    NoteSection.objects.create(user_id=user_id, note=note, heading="Day 1", body="…")
    Idea.objects.create(user_id=user_id, title="Side quest")
    GraveyardInsight.objects.create(user_id=user_id, body="You quit at month 3.")

    conv = Conversation.objects.create(user_id=user_id, title="Plan")
    Message.objects.create(
        conversation=conv, role="user", content=[{"type": "text", "text": "hi"}]
    )
    UsageDay.objects.create(user_id=user_id, date=today)
    AccountProfile.objects.create(user_id=user_id)

    Notification.objects.create(
        user_id=user_id, channel="expo", kind="weekly_digest", dedupe_key="w1", body="…"
    )
    ExpoPushToken.objects.create(user_id=user_id, device_id="dev", token="ExponentPushToken[x]")
    NotificationSettings.objects.create(user_id=user_id)
    EmailSend.objects.create(user_id=user_id, email_id="welcome_regular", status="sent")

    GoogleOAuthCredential.objects.create(user_id=user_id, refresh_token="enc", email="a@b.c")
    client = OAuthClient.objects.create(client_id=f"c-{nonce}", client_name="Claude")
    OAuthAuthorizationCode.objects.create(
        code_hash=f"code-{nonce}",
        client=client,
        user_id=user_id,
        redirect_uri="https://claude.ai/cb",
        code_challenge="x",
        expires_at=now,
    )
    OAuthRefreshToken.objects.create(
        token_hash=f"rt-{nonce}", client=client, user_id=user_id, expires_at=now
    )
    OAuthConnectionEvent.objects.create(
        user_id=user_id, client_id=client.client_id, event="authorized"
    )

    BackupMeta.objects.create(user_id=user_id, last_backup=now)
    Profile.objects.create(user_id=user_id, first_name="Ana", avatar="3d/momo")
    OnboardingProgress.objects.create(user_id=user_id)
    UserPreferences.objects.create(user_id=user_id)
    InteractionDay.objects.create(user_id=user_id, date=today, source="web", count=3)
    BugReport.objects.create(user_id=user_id, topic="sync", message="My notes vanished")

    return {
        m for m in USER_OWNED_MODELS if m.objects.filter(user_id=user_id).exists()
    }


def _counts(user_id: uuid.UUID) -> dict[type, int]:
    return {m: m.objects.filter(user_id=user_id).count() for m in USER_OWNED_MODELS}


def _user_keyed_fields(model) -> list[str]:
    return [
        f.name
        for f in model._meta.concrete_fields
        if "user_id" in f.name  # user_id, app_user_id, author_user_id, audience_user_ids…
    ]


def test_every_user_keyed_model_is_accounted_for():
    unaccounted = [
        f"{m._meta.label} ({', '.join(_user_keyed_fields(m))})"
        for m in apps.get_models()
        if _user_keyed_fields(m)
        and m not in USER_OWNED_MODELS
        and m not in RETAINED_MODELS
    ]
    assert not unaccounted, (
        "Decide what deleteAccount does with these (add to USER_OWNED_MODELS, or "
        f"anonymize them and list them in RETAINED_MODELS): {unaccounted}"
    )


@pytest.mark.django_db
def test_seed_covers_every_user_owned_model(user_a):
    # Keeps the behavioural test honest: a model added to USER_OWNED_MODELS
    # without a row here would "pass" deletion trivially.
    assert _seed(user_a) == set(USER_OWNED_MODELS)


@pytest.mark.django_db
def test_delete_account_erases_everything_of_the_user_only(user_a, user_b, no_supabase):
    _seed(user_a)
    _seed(user_b)
    before_b = _counts(user_b)
    messages_b = Message.objects.filter(conversation__user_id=user_b).count()

    delete_account(user_a)

    left = {m._meta.label: n for m, n in _counts(user_a).items() if n}
    assert left == {}
    assert not Message.objects.filter(conversation__user_id=user_a).exists()

    assert _counts(user_b) == before_b
    assert Message.objects.filter(conversation__user_id=user_b).count() == messages_b
    assert no_supabase == [user_a]


@pytest.mark.django_db
def test_delete_account_is_idempotent(user_a, no_supabase):
    _seed(user_a)
    delete_account(user_a)
    delete_account(user_a)
    assert not any(_counts(user_a).values())
    assert no_supabase == [user_a, user_a]


@pytest.mark.django_db
def test_store_events_keep_accounting_fields_but_lose_the_person(user_a, user_b):
    payload = {
        "api_version": "1.0",
        "event": {
            "id": "evt-1",
            "type": "INITIAL_PURCHASE",
            "app_user_id": str(user_a),
            "original_app_user_id": str(user_a),
            "aliases": [str(user_a), "$RCAnonymousID:abc"],
            "subscriber_attributes": {"$email": {"value": "ana@example.com"}},
            "product_id": "studio_monthly",
            "transaction_id": "tx-1",
            "price": 9.99,
            "currency": "USD",
            "country_code": "MX",
        },
    }
    StoreWebhookEvent.objects.create(
        event_id="evt-1",
        event_type="INITIAL_PURCHASE",
        app_user_id=str(user_a),
        product_id="studio_monthly",
        payload=payload,
    )
    StoreWebhookEvent.objects.create(
        event_id="evt-2", app_user_id=str(user_b), payload={"event": {"id": "evt-2"}}
    )

    delete_account(user_a)

    row = StoreWebhookEvent.objects.get(event_id="evt-1")
    assert row.app_user_id == ""
    assert row.product_id == "studio_monthly"
    event = row.payload["event"]
    assert event == {
        "id": "evt-1",
        "type": "INITIAL_PURCHASE",
        "product_id": "studio_monthly",
        "transaction_id": "tx-1",
        "price": 9.99,
        "currency": "USD",
        "country_code": "MX",
    }
    assert str(user_a) not in str(row.payload)
    assert "ana@example.com" not in str(row.payload)

    other = StoreWebhookEvent.objects.get(event_id="evt-2")
    assert other.app_user_id == str(user_b)


@pytest.mark.django_db
def test_audit_entries_about_the_user_are_redacted(user_a, user_b):
    admin = uuid.uuid4()
    about_a = AdminAuditLog.objects.create(
        actor_user_id=admin,
        action="beta.set_fields",
        target_type="account_profile",
        target_id=str(user_a),
        payload={"before": {"plan": "free"}, "after": {"plan": "studio"}},
    )
    mcp_a = AdminAuditLog.objects.create(
        actor_user_id=admin,
        action="mcp.revoke_connection",
        target_type="mcp_connection",
        target_id=f"{user_a}:client-1",
        payload={"revoked": 1},
    )
    about_b = AdminAuditLog.objects.create(
        actor_user_id=admin,
        action="user.set_plan",
        target_type="user",
        target_id=str(user_b),
        payload={"plan": "pro"},
    )

    delete_account(user_a)

    for entry in (about_a, mcp_a):
        entry.refresh_from_db()
        assert entry.payload == {"redacted": "account_deleted"}
        assert entry.action  # the fact that it happened stays
    about_b.refresh_from_db()
    assert about_b.payload == {"plan": "pro"}


@pytest.mark.django_db
def test_announcement_audience_drops_the_user_without_going_public(user_a, user_b):
    only_a = Announcement.objects.create(
        title="Just for you", status="published", audience_user_ids=[str(user_a)]
    )
    a_and_b = Announcement.objects.create(
        title="Both", status="published", audience_user_ids=[str(user_a), str(user_b)]
    )
    a_or_pro = Announcement.objects.create(
        title="A or pro",
        status="published",
        audience_user_ids=[str(user_a)],
        audience_plans=["pro"],
    )

    delete_account(user_a)

    only_a.refresh_from_db()
    assert only_a.audience_user_ids == []
    assert only_a.status == AnnouncementStatus.ARCHIVED  # not shown to everyone

    a_and_b.refresh_from_db()
    assert a_and_b.audience_user_ids == [str(user_b)]
    assert a_and_b.status == AnnouncementStatus.PUBLISHED

    a_or_pro.refresh_from_db()
    assert a_or_pro.audience_user_ids == []
    assert a_or_pro.status == AnnouncementStatus.PUBLISHED  # still scoped to the pro plan

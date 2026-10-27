"""Unsubscribe from lifecycle emails: signed link, headers, opt-out honoured."""

from __future__ import annotations

import uuid

import pytest
from django.test import Client

from core.notifications import lifecycle, unsubscribe
from core.notifications.models import EmailSend, NotificationSettings
from core.notifications.providers.base import DeliveryResult
from core.services import app_config


class _FakeUser:
    email = "user@example.com"


@pytest.fixture
def capture(monkeypatch):
    app_config.set("dry_run", False)
    monkeypatch.setattr("core.admin_api.supabase_admin.get_user", lambda uid: _FakeUser())
    sent = []

    class _Capture:
        def send(self, to, subject, html, text="", **kw):
            sent.append({"html": html, "text": text, "headers": kw.get("headers") or {}})
            return DeliveryResult(success=True, external_message_id="m1")

    monkeypatch.setattr(lifecycle, "ResendEmailProvider", _Capture)
    return sent


def test_token_roundtrip_and_tamper():
    u = uuid.uuid4()
    token = unsubscribe.make_token(u)
    assert unsubscribe.read_token(token) == u
    assert unsubscribe.read_token(token[:-2] + "xx") is None
    assert unsubscribe.read_token("") is None


@pytest.mark.django_db
def test_lifecycle_email_carries_link_and_one_click_headers(capture):
    u = uuid.uuid4()

    assert lifecycle.deliver(u, "inactivity_1") == lifecycle.SENT

    mail = capture[0]
    url = unsubscribe.unsubscribe_url(u)
    assert url in mail["html"] and url in mail["text"]
    assert mail["headers"] == {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


@pytest.mark.django_db
def test_account_notices_have_no_link(capture):
    u = uuid.uuid4()
    lifecycle.deliver(u, "reclaim_warn", episode_key="2026-10-01")
    assert capture[0]["headers"] == {}
    assert "unsubscribe" not in capture[0]["html"]


@pytest.mark.django_db
def test_opted_out_user_gets_only_account_notices(capture):
    u = uuid.uuid4()
    NotificationSettings.objects.create(user_id=u, lifecycle_emails_enabled=False)

    assert lifecycle.deliver(u, "inactivity_1") == lifecycle.OPTED_OUT
    assert not EmailSend.objects.filter(user_id=u, email_id="inactivity_1").exists()
    assert lifecycle.deliver(u, "reclaim_warn", episode_key="2026-10-01") == lifecycle.SENT
    assert len(capture) == 1


@pytest.mark.django_db
def test_get_asks_and_post_unsubscribes():
    u = uuid.uuid4()
    NotificationSettings.objects.create(user_id=u, locale="es")
    token = unsubscribe.make_token(u)
    client = Client()

    page = client.get("/email/unsubscribe/", {"t": token})
    assert page.status_code == 200
    assert "Darme de baja" in page.content.decode()
    # A link prefetch (GET) never changes anything.
    assert NotificationSettings.objects.get(user_id=u).lifecycle_emails_enabled is True

    done = client.post(f"/email/unsubscribe/?t={token}", {"List-Unsubscribe": "One-Click"})
    assert done.status_code == 200
    assert NotificationSettings.objects.get(user_id=u).lifecycle_emails_enabled is False


@pytest.mark.django_db
def test_post_creates_settings_row_and_rejects_bad_token():
    u = uuid.uuid4()
    client = Client()

    assert client.post("/email/unsubscribe/", {"t": "nope"}).status_code == 400
    assert client.post("/email/unsubscribe/", {"t": unsubscribe.make_token(u)}).status_code == 200
    assert NotificationSettings.objects.get(user_id=u).lifecycle_emails_enabled is False

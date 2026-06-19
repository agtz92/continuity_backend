"""Tests for product/lifecycle email delivery (welcome path + idempotency)."""

from __future__ import annotations

import uuid

import pytest

from core.notifications import lifecycle
from core.notifications.models import EmailSend
from core.notifications.providers.base import DeliveryResult
from core.services import app_config


class _FakeUser:
    def __init__(self, email):
        self.email = email


def _patch_recipient(monkeypatch, email="user@example.com"):
    monkeypatch.setattr(
        "core.admin_api.supabase_admin.get_user",
        lambda uid: _FakeUser(email),
    )


def _patch_provider(monkeypatch, *, success=True, error=""):
    class _FakeProvider:
        def send(self, to, subject, html, text="", **kw):
            return DeliveryResult(
                success=success, external_message_id="msg_1" if success else "", error=error
            )

    monkeypatch.setattr(lifecycle, "ResendEmailProvider", _FakeProvider)


@pytest.mark.django_db
def test_dry_run_logs_preview_without_sending(monkeypatch):
    # Default seeded config has dry_run = True.
    u = uuid.uuid4()
    # Provider must NOT be called in dry_run — make it explode if it is.
    _patch_provider(monkeypatch, success=False, error="should not be called")

    assert lifecycle.deliver(u, "welcome_beta") == lifecycle.DRY_RUN
    row = EmailSend.objects.get(user_id=u, email_id="welcome_beta")
    assert row.dry_run is True
    assert row.status == EmailSend.Status.DRY_RUN

    # Second run does not create a duplicate preview row.
    assert lifecycle.deliver(u, "welcome_beta") == lifecycle.DRY_RUN_SKIPPED
    assert EmailSend.objects.filter(user_id=u, email_id="welcome_beta").count() == 1


@pytest.mark.django_db
def test_real_send_is_idempotent(monkeypatch):
    app_config.set("dry_run", False)
    u = uuid.uuid4()
    _patch_recipient(monkeypatch)
    _patch_provider(monkeypatch, success=True)

    assert lifecycle.deliver(u, "welcome_regular") == lifecycle.SENT
    row = EmailSend.objects.get(user_id=u, email_id="welcome_regular", dry_run=False)
    assert row.status == EmailSend.Status.SENT
    assert row.resend_message_id == "msg_1"

    # Second real attempt is a no-op; still exactly one real row.
    assert lifecycle.deliver(u, "welcome_regular") == lifecycle.ALREADY_SENT
    assert EmailSend.objects.filter(
        user_id=u, email_id="welcome_regular", dry_run=False
    ).count() == 1


@pytest.mark.django_db
def test_failure_increments_attempts_on_same_row(monkeypatch):
    app_config.set("dry_run", False)
    u = uuid.uuid4()
    _patch_recipient(monkeypatch)
    _patch_provider(monkeypatch, success=False, error="resend 500")

    assert lifecycle.deliver(u, "welcome_beta") == lifecycle.FAILED
    assert lifecycle.deliver(u, "welcome_beta") == lifecycle.FAILED
    rows = EmailSend.objects.filter(user_id=u, email_id="welcome_beta", dry_run=False)
    assert rows.count() == 1
    assert rows.first().attempts == 2
    assert rows.first().status == EmailSend.Status.FAILED


@pytest.mark.django_db
def test_missing_recipient_is_a_failure(monkeypatch):
    app_config.set("dry_run", False)
    u = uuid.uuid4()
    monkeypatch.setattr("core.admin_api.supabase_admin.get_user", lambda uid: None)

    assert lifecycle.deliver(u, "welcome_regular") == lifecycle.FAILED
    row = EmailSend.objects.get(user_id=u, email_id="welcome_regular", dry_run=False)
    assert row.error == "no recipient email"


@pytest.mark.django_db
def test_welcome_skips_suppressed_users():
    from django.core.management import call_command

    from core.assistant.models import AccountProfile

    existing = uuid.uuid4()
    fresh = uuid.uuid4()
    AccountProfile.objects.create(user_id=existing, beta_cohort=True, beta_status="active")
    AccountProfile.objects.create(user_id=fresh, beta_cohort=True, beta_status="active")
    # `existing` marked SUPPRESSED at launch (as migration 0011 would).
    EmailSend.objects.create(
        user_id=existing,
        email_id="welcome_beta",
        status=EmailSend.Status.SUPPRESSED,
        dry_run=False,
    )

    call_command("send_lifecycle_welcome")

    # Suppressed user got no welcome (not even a dry_run preview).
    assert EmailSend.objects.filter(user_id=existing).count() == 1
    assert not EmailSend.objects.filter(user_id=existing, dry_run=True).exists()
    # Fresh user got the welcome preview.
    assert EmailSend.objects.filter(
        user_id=fresh, email_id="welcome_beta", dry_run=True
    ).exists()


@pytest.mark.django_db
def test_render_respects_locale():
    from core.notifications.email_templates import render

    ctx = {"greeting": "Hi", "spot_cap": 50, "app_url": "https://x", "days_inactive": 5}
    subj_en, html_en, _ = render("welcome_beta", ctx, "en")
    subj_es, _, _ = render("welcome_beta", ctx, "es")
    assert subj_en == "You're in 🎉"
    assert subj_es == "Estás dentro 🎉"
    assert "Open continuu" in html_en  # CTA injected
    # Unknown locale falls back to en.
    subj_fr, _, _ = render("welcome_beta", ctx, "fr")
    assert subj_fr == subj_en


@pytest.mark.django_db
def test_user_locale_lookup():
    from core.notifications.models import NotificationSettings

    u = uuid.uuid4()
    assert lifecycle._user_locale(u) == "en"  # default, no row
    NotificationSettings.objects.create(user_id=u, locale="es")
    assert lifecycle._user_locale(u) == "es"


@pytest.mark.django_db
def test_deliver_uses_user_language(monkeypatch):
    from core.notifications.models import NotificationSettings

    app_config.set("dry_run", False)
    u = uuid.uuid4()
    NotificationSettings.objects.create(user_id=u, locale="es")
    _patch_recipient(monkeypatch)

    captured = {}

    class _Capture:
        def send(self, to, subject, html, text="", **kw):
            captured["subject"] = subject
            return DeliveryResult(success=True, external_message_id="m1")

    monkeypatch.setattr(lifecycle, "ResendEmailProvider", _Capture)

    lifecycle.deliver(u, "welcome_beta")
    assert captured["subject"] == "Estás dentro 🎉"


@pytest.mark.django_db
def test_welcome_command_picks_template_by_cohort(monkeypatch):
    from django.core.management import call_command

    from core.assistant.models import AccountProfile

    beta = uuid.uuid4()
    regular = uuid.uuid4()
    AccountProfile.objects.create(user_id=beta, beta_cohort=True, beta_status="active")
    AccountProfile.objects.create(user_id=regular, beta_cohort=False)

    # dry_run default → previews logged, no sends.
    call_command("send_lifecycle_welcome")

    assert EmailSend.objects.filter(user_id=beta, email_id="welcome_beta").exists()
    assert EmailSend.objects.filter(user_id=regular, email_id="welcome_regular").exists()

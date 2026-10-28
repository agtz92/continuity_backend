"""adminSendUserEmail: hand-written email from the admin panel to one user."""

from __future__ import annotations

import uuid

import pytest

from core.admin_api.models import AdminAuditLog
from core.assistant.models import AccountProfile
from core.notifications.models import EmailSend, NotificationSettings
from core.notifications.providers.base import DeliveryResult

SEND = """
mutation($id: ID!, $s: String!, $b: String!) {
  adminSendUserEmail(userId: $id, subject: $s, body: $b) { subject body locale status }
}
"""


@pytest.fixture
def admin_id():
    uid = uuid.uuid4()
    AccountProfile.objects.create(user_id=uid, is_admin=True)
    return uid


@pytest.fixture
def sent(monkeypatch):
    """Capture Resend calls and resolve every recipient to friend@x.com."""
    calls: list[dict] = []
    result = {"ok": True}

    class _P:
        def send(self, to, subject, html, text="", **kw):
            calls.append({"to": to, "subject": subject, "html": html, "text": text, **kw})
            if result["ok"]:
                return DeliveryResult(success=True, external_message_id="m1")
            return DeliveryResult(success=False, error="resend 500: boom")

    monkeypatch.setattr("core.notifications.direct.ResendEmailProvider", _P)
    monkeypatch.setattr(
        "core.notifications.lifecycle._recipient_email", lambda uid: "friend@x.com"
    )
    calls_holder = type("C", (), {"calls": calls, "result": result})
    return calls_holder


@pytest.mark.django_db
def test_sends_with_tokens_footer_and_ledger(execute_query, admin_id, user_a, sent):
    NotificationSettings.objects.create(user_id=user_a, locale="es")
    res = execute_query(
        SEND,
        user_id=admin_id,
        variable_values={
            "id": str(user_a),
            "s": "Una pregunta\n rápida",
            "b": "{{greeting}},\n\nVi que creaste tu cuenta.\n\nAlfredo",
        },
    )
    assert res.errors is None, res.errors
    out = res.data["adminSendUserEmail"]
    assert out["status"] == "sent"
    assert out["locale"] == "es"
    assert out["subject"] == "Una pregunta rápida"

    (call,) = sent.calls
    assert call["to"] == "friend@x.com"
    assert call["text"].startswith("Hola,")
    assert "<p>Vi que creaste tu cuenta.</p>" in call["html"]
    assert "List-Unsubscribe" in call["headers"]
    assert call["reply_to"] == '"continuu · friend" <hello@continuu.it>'

    row = EmailSend.objects.get(user_id=user_a)
    assert row.email_id == "admin_direct"
    assert row.status == EmailSend.Status.SENT and not row.dry_run
    log = AdminAuditLog.objects.get(action="user.send_email")
    assert log.payload["send_id"] == row.id


@pytest.mark.django_db
def test_second_email_is_not_blocked_by_idempotency(execute_query, admin_id, user_a, sent):
    for _ in range(2):
        res = execute_query(
            SEND, user_id=admin_id, variable_values={"id": str(user_a), "s": "Hi", "b": "Hello"}
        )
        assert res.errors is None, res.errors
    assert EmailSend.objects.filter(user_id=user_a, status="sent").count() == 2


@pytest.mark.django_db
def test_refuses_opted_out_user(execute_query, admin_id, user_a, sent):
    NotificationSettings.objects.create(user_id=user_a, lifecycle_emails_enabled=False)
    res = execute_query(
        SEND, user_id=admin_id, variable_values={"id": str(user_a), "s": "Hi", "b": "Hello"}
    )
    assert res.errors[0].extensions["code"] == "OPTED_OUT"
    assert sent.calls == []
    assert not EmailSend.objects.exists()


@pytest.mark.django_db
def test_refuses_empty_body(execute_query, admin_id, user_a, sent):
    res = execute_query(
        SEND, user_id=admin_id, variable_values={"id": str(user_a), "s": "Hi", "b": "  "}
    )
    assert res.errors[0].extensions["code"] == "BAD_INPUT"
    assert sent.calls == []


@pytest.mark.django_db
def test_provider_failure_is_recorded_and_reported(execute_query, admin_id, user_a, sent):
    sent.result["ok"] = False
    res = execute_query(
        SEND, user_id=admin_id, variable_values={"id": str(user_a), "s": "Hi", "b": "Hello"}
    )
    assert res.errors[0].extensions["code"] == "SEND_FAILED"
    row = EmailSend.objects.get(user_id=user_a)
    assert row.status == EmailSend.Status.FAILED and row.attempts == 1


@pytest.mark.django_db
def test_requires_admin(execute_query, user_a, user_b, sent):
    AccountProfile.objects.create(user_id=user_a, is_admin=False)
    res = execute_query(
        SEND, user_id=user_a, variable_values={"id": str(user_b), "s": "Hi", "b": "Hello"}
    )
    assert res.errors is not None
    assert sent.calls == []


@pytest.mark.django_db
def test_history_shows_in_user_detail(execute_query, admin_id, user_a, sent, monkeypatch):
    execute_query(
        SEND, user_id=admin_id, variable_values={"id": str(user_a), "s": "Hi", "b": "Hello"}
    )
    monkeypatch.setattr(
        "core.admin_api.schema.supabase_get_user",
        lambda uid: type(
            "U",
            (),
            {
                "email": "friend@x.com",
                "created_at": None,
                "last_sign_in_at": None,
                "email_confirmed_at": None,
                "banned_until": None,
            },
        )(),
    )
    doc = """query($id: ID!) { adminUser(userId: $id) {
        emailLocale lifecycleEmailsEnabled directEmails { subject body status }
    } }"""
    res = execute_query(doc, user_id=admin_id, variable_values={"id": str(user_a)})
    assert res.errors is None, res.errors
    u = res.data["adminUser"]
    assert u["emailLocale"] == "en"
    assert u["lifecycleEmailsEnabled"] is True
    assert u["directEmails"] == [{"subject": "Hi", "body": "Hello", "status": "sent"}]


def test_reply_to_label_uses_first_name_and_strips_header_chars():
    from core.notifications.direct import reply_to_for

    assert reply_to_for("Gangeswari", "g@x.com") == '"continuu · Gangeswari" <hello@continuu.it>'
    assert reply_to_for('Ana "<x>", Pérez', "a@x.com") == '"continuu · Ana x Pérez" <hello@continuu.it>'
    assert reply_to_for("", "selva.gange@gmail.com") == '"continuu · selva.gange" <hello@continuu.it>'

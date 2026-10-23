"""Push/Telegram message redesign: short push content, capped Telegram lists,
localized dates, Expo payload shape, and the push action buttons."""

from __future__ import annotations

import datetime as dt
import uuid
import zoneinfo
from types import SimpleNamespace

import pytest

from core.models import Project, Routine, Task
from core.notifications import actions, builders
from core.notifications.models import NotificationSettings
from core.notifications.providers.base import PushContent
from core.notifications.providers.expo import build_payload
from core.schema import schema

TZ = zoneinfo.ZoneInfo("America/Mexico_City")
TODAY = dt.date(2026, 10, 20)  # a Tuesday


def _at(day: dt.date, hour: int = 12) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour), tzinfo=TZ)


@pytest.fixture
def user(db):
    uid = uuid.uuid4()
    NotificationSettings.objects.create(user_id=uid, locale="es", timezone=TZ.key)
    return uid


def _task(uid, title, due, project=None, **kw):
    return Task.objects.create(user_id=uid, title=title, due_date=due, project=project, **kw)


# ---------- daily digest ----------


@pytest.mark.django_db
def test_daily_push_is_short_and_names_the_oldest_overdue_task(user):
    _task(user, "Revisar contrato", _at(TODAY - dt.timedelta(days=1)))
    oldest = _task(user, "Enviar propuesta", _at(TODAY - dt.timedelta(days=2)))
    _task(user, "Llamar al banco", _at(TODAY))

    msg = builders.build_daily_digest(user, today=TODAY)

    assert msg.push.title == "3 pendientes para hoy, 2 atrasadas"
    assert msg.push.body == "Empieza por «Enviar propuesta»: lleva 2 días atrasada."
    assert msg.push.category == builders.CATEGORY_TASK_FOCUS
    assert msg.push.data == {"taskIds": [str(oldest.id)]}
    assert msg.push.path == "/today"
    # Telegram: localized date, focus line, the focus task isn't repeated below.
    assert "mar 20 oct" in msg.text
    assert "👉 *Empieza por:* Enviar propuesta" in msg.text
    assert msg.text.count("Enviar propuesta") == 1


@pytest.mark.django_db
def test_daily_telegram_caps_long_sections(user):
    for i in range(8):
        _task(user, f"Tarea {i}", _at(TODAY, 9 + i))

    msg = builders.build_daily_digest(user, today=TODAY)

    # Focus takes "Tarea 0"; 7 remain in "Para hoy", capped at 5 + "…y 2 más".
    assert "_…y 2 más_" in msg.text
    assert "Tarea 7" not in msg.text
    assert msg.push.title == "8 pendientes para hoy"
    assert msg.push.body == "Empieza por «Tarea 0»."


@pytest.mark.django_db
def test_daily_focus_mentions_project(user):
    p = Project.objects.create(user_id=user, name="Landing", status="active", priority="medium")
    _task(user, "Copiar hero", _at(TODAY), project=p)

    msg = builders.build_daily_digest(user, today=TODAY)

    assert msg.push.title == "1 pendiente para hoy"
    assert msg.push.body == "Empieza por «Copiar hero» de Landing."


@pytest.mark.django_db
def test_daily_routines_only_has_no_action_buttons(user):
    Routine.objects.create(
        user_id=user, title="Gym", recurrence_type="once", start_date=TODAY
    )

    msg = builders.build_daily_digest(user, today=TODAY)

    assert msg.push.body == "Rutinas de hoy: «Gym»."
    assert msg.push.category == ""


@pytest.mark.django_db
def test_daily_empty_is_valid_markdown_v2(user):
    msg = builders.build_daily_digest(user, today=TODAY)

    assert msg.push.title == "Sin pendientes hoy"
    # Literal dots must be escaped or Telegram rejects the whole message.
    assert "hoy\\." in msg.text


# ---------- end-of-day warning ----------


@pytest.mark.django_db
def test_due_warning_none_when_nothing_pending(user):
    assert builders.build_due_warning(user, today=TODAY) is None


@pytest.mark.django_db
def test_due_warning_single_task_offers_focus_actions(user):
    t = _task(user, "Llamar al banco", _at(TODAY))

    msg = builders.build_due_warning(user, today=TODAY)

    assert msg.push.title == "Te queda 1 por cerrar"
    assert msg.push.body == "«Llamar al banco». ¿La cierras o pasa a mañana?"
    assert msg.push.category == builders.CATEGORY_TASK_FOCUS
    assert msg.push.data == {"taskIds": [str(t.id)]}
    assert msg.push.android_channel == "reminders"


@pytest.mark.django_db
def test_due_warning_several_tasks_offers_bulk_postpone(user):
    ids = {str(_task(user, f"T{i}", _at(TODAY, 10 + i)).id) for i in range(3)}

    msg = builders.build_due_warning(user, today=TODAY)

    assert msg.push.title == "Te quedan 3 por cerrar"
    assert msg.push.body == "«T0», «T1» y 1 más. ¿Las cierras o pasan a mañana?"
    assert msg.push.category == builders.CATEGORY_TASKS_BULK
    assert set(msg.push.data["taskIds"]) == ids


# ---------- weekly ----------


def _analytics(**overrides):
    base = dict(
        cadence=SimpleNamespace(active_days_in_range=5, total_activity_events=42),
        top_projects=[SimpleNamespace(name="Continuity App", interactions=18, delta_vs_prev=4)],
        backlog=SimpleNamespace(
            open_tasks=14, overdue_tasks=3, due_soon_tasks=2, quick_wins=0, almost_there=0
        ),
        sleeping_projects=[
            SimpleNamespace(name="Blog", days_idle=9),
            SimpleNamespace(name="Landing", days_idle=14),
        ],
        stale_ideas=[],
        idea_funnel=SimpleNamespace(ideas_created=0, ideas_promoted=0, promotion_rate=0),
        effort=SimpleNamespace(effort_hours_total=0),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.django_db
def test_weekly_push_is_quiet_and_points_at_analytics(user, monkeypatch):
    monkeypatch.setattr(builders.analytics, "compute_analytics", lambda *a: _analytics())

    msg = builders.build_weekly_digest(user)

    assert msg.push.title == "Activo 5 de 7 días esta semana"
    assert msg.push.body == (
        "Continuity App fue lo que más avanzó. Landing lleva 14 días sin moverse."
    )
    assert msg.push.path == "/analytics"
    assert msg.push.quiet is True
    # The dashboard link is a button now, not inline Markdown.
    assert "](" not in msg.text
    assert msg.text.index("Landing") < msg.text.index("Blog")  # most idle first


@pytest.mark.django_db
def test_weekly_quiet_week(user, monkeypatch):
    monkeypatch.setattr(
        builders.analytics,
        "compute_analytics",
        lambda *a: _analytics(
            cadence=SimpleNamespace(active_days_in_range=0, total_activity_events=0),
            top_projects=[],
            sleeping_projects=[],
        ),
    )

    msg = builders.build_weekly_digest(user)

    assert msg.push.title == "Semana en pausa"


# ---------- Expo payload ----------


def test_expo_payload_uses_push_content(settings):
    settings.EXPO_PUSH_ANDROID_CHANNELS = True
    push = PushContent(
        title="T",
        body="B",
        path="/analytics",
        category="task_focus",
        android_channel="weekly",
        quiet=True,
        data={"taskIds": ["x"]},
    )

    p = build_payload("tok", "ignored", kind="weekly_digest", push=push)

    assert p["title"] == "T" and p["body"] == "B"
    assert p["data"] == {"taskIds": ["x"], "path": "/analytics", "kind": "weekly_digest"}
    assert p["categoryId"] == "task_focus"
    assert p["channelId"] == "weekly"
    assert p["interruptionLevel"] == "passive"
    assert "sound" not in p


def test_expo_payload_omits_channel_until_enabled(settings):
    settings.EXPO_PUSH_ANDROID_CHANNELS = False
    p = build_payload(
        "tok", "x", kind="manual", push=PushContent(title="T", body="B", android_channel="daily")
    )
    assert "channelId" not in p
    assert p["sound"] == "default"


def test_expo_fallback_strips_links_and_clips():
    body = "Hola\n" + ("palabra " * 60) + "\n[Ver dashboard](https://continuu.it)"

    p = build_payload("tok", body, kind="manual", push=None)

    assert p["title"] == "Hola"
    assert len(p["body"]) <= 180
    assert p["body"].endswith("…")
    assert "https://" not in p["body"]


# ---------- action buttons ----------


@pytest.mark.django_db
def test_complete_is_idempotent(user):
    t = _task(user, "A", _at(TODAY))

    assert actions.complete_tasks(user, [str(t.id)]) == 1
    assert actions.complete_tasks(user, [str(t.id)]) == 0  # replayed response
    t.refresh_from_db()
    assert t.done is True and t.completed_at is not None


@pytest.mark.django_db
def test_postpone_moves_to_tomorrow_keeping_time_and_skips_future(user):
    overdue = _task(user, "A", _at(TODAY - dt.timedelta(days=3), 9))
    future = _task(user, "B", _at(TODAY + dt.timedelta(days=5), 9))
    now = _at(TODAY, 19)

    moved = actions.postpone_tasks(user, [str(overdue.id), str(future.id)], now=now)

    assert moved == 1
    overdue.refresh_from_db()
    future.refresh_from_db()
    assert overdue.due_date.astimezone(TZ) == _at(TODAY + dt.timedelta(days=1), 9)
    assert future.due_date.astimezone(TZ) == _at(TODAY + dt.timedelta(days=5), 9)


@pytest.mark.django_db
def test_actions_ignore_other_users_and_bad_ids(user):
    other = uuid.uuid4()
    theirs = _task(other, "Ajena", _at(TODAY))

    assert actions.complete_tasks(user, [str(theirs.id), "not-a-uuid"]) == 0
    theirs.refresh_from_db()
    assert theirs.done is False


@pytest.mark.django_db
def test_run_notification_action_mutation(user):
    t = _task(user, "A", _at(TODAY))
    doc = """
      mutation($ids: [ID!]!) {
        runNotificationAction(action: COMPLETE, taskIds: $ids)
      }
    """

    res = schema.execute_sync(
        doc, context_value=SimpleNamespace(user_id=user), variable_values={"ids": [str(t.id)]}
    )
    assert res.errors is None
    assert res.data == {"runNotificationAction": 1}

    anon = schema.execute_sync(
        doc, context_value=SimpleNamespace(user_id=None), variable_values={"ids": [str(t.id)]}
    )
    assert anon.errors

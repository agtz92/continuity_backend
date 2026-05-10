"""Tests for the skinny-context builder."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from core.assistant import prompts
from core.notifications.models import NotificationSettings


@pytest.mark.django_db
def test_skinny_context_wraps_user_data_in_xml(user_a, make_profile, make_project):
    make_profile(user_a)
    make_project(user_a, name="Alpha")
    text = prompts.build_skinny_context_text(
        user_a, plan="free", now=timezone.now()
    )
    assert text.startswith("<user_data>")
    assert text.rstrip().endswith("</user_data>")
    assert "Alpha" in text


@pytest.mark.django_db
def test_skinny_context_includes_locale_and_timezone(user_a, make_profile):
    NotificationSettings.objects.create(
        user_id=user_a, locale="es", timezone="America/Mexico_City"
    )
    text = prompts.build_skinny_context_text(
        user_a, plan="pro", now=timezone.now()
    )
    assert "<locale>es</locale>" in text
    assert "America/Mexico_City" in text
    assert "<plan>pro</plan>" in text


@pytest.mark.django_db
def test_skinny_context_escapes_xml_in_names(user_a, make_project):
    make_project(user_a, name="Pro&jects <weird>")
    text = prompts.build_skinny_context_text(
        user_a, plan="free", now=timezone.now()
    )
    assert "Pro&amp;jects" in text
    assert "&lt;weird&gt;" in text
    # Raw entity must not escape into user_data
    assert "<weird>" not in text


@pytest.mark.django_db
def test_skinny_context_ignores_other_users(user_a, user_b, make_project):
    make_project(user_a, name="MineProject")
    make_project(user_b, name="TheirsProject")
    text = prompts.build_skinny_context_text(
        user_a, plan="free", now=timezone.now()
    )
    assert "MineProject" in text
    assert "TheirsProject" not in text

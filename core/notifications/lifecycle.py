"""Idempotent delivery for product/lifecycle emails.

Single entry point `deliver()` shared by the welcome command and the daily beta
lifecycle cron. Enforces:

- Idempotency: at most ONE real send per (user_id, email_id, episode_key),
  backed by the partial unique constraint on EmailSend (dry_run=False).
- dry_run (app_config): when on, nothing is sent — a single dry_run row is
  logged per combo for admin preview, with NO side effects.
- Failure tracking: a real-send failure keeps the row at status=failed and
  increments attempts; surfaced in admin at attempts >= 3.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from django.conf import settings
from django.utils import timezone

from .email_templates import render
from .models import EmailSend
from .providers.base import DeliveryResult, ProviderError
from .providers.resend import ResendEmailProvider

logger = logging.getLogger(__name__)

# Result codes returned by deliver().
SENT = "sent"
FAILED = "failed"
ALREADY_SENT = "already_sent"
DRY_RUN = "dry_run"
DRY_RUN_SKIPPED = "dry_run_skipped"


def _user_locale(user_id: uuid.UUID) -> str:
    """User's email language from NotificationSettings.locale. Normalised to
    'es' or 'en' (default 'en')."""
    from .models import NotificationSettings

    loc = (
        NotificationSettings.objects.filter(user_id=user_id)
        .values_list("locale", flat=True)
        .first()
        or "en"
    )
    return "es" if str(loc).split("-")[0].lower() == "es" else "en"


def _build_context(
    user_id: uuid.UUID, extra: Optional[dict[str, Any]], locale: str
) -> dict[str, Any]:
    from core.services import app_config, profiles

    first_name = ""
    try:
        first_name = (profiles.get_profile(user_id).first_name or "").strip()
    except Exception:  # profile may not exist yet — greet generically
        pass
    if locale == "es":
        greeting = f"Hola {first_name}" if first_name else "Hola"
        project_fallback = "tus proyectos"
    else:
        greeting = f"Hi {first_name}" if first_name else "Hi"
        project_fallback = "your projects"
    ctx: dict[str, Any] = {
        "first_name": first_name,
        "greeting": greeting,
        "app_url": getattr(settings, "FRONTEND_BASE_URL", ""),
        "spot_cap": app_config.get_int("beta_spot_cap"),
        # Defaults so reengage tokens never leak literally; the cron overrides
        # these via extra_ctx with real values.
        "days_inactive": "a few" if locale == "en" else "varios",
        "last_project_title": project_fallback,
    }
    if extra:
        ctx.update({k: v for k, v in extra.items() if v not in (None, "")})
    return ctx


def _recipient_email(user_id: uuid.UUID) -> str:
    from core.admin_api import supabase_admin

    try:
        user = supabase_admin.get_user(user_id)
    except Exception as e:  # SupabaseAdminError / network
        logger.warning("deliver: cannot resolve email for %s: %s", user_id, e)
        return ""
    return user.email if user else ""


def deliver(
    user_id: uuid.UUID,
    email_id: str,
    *,
    episode_key: str = "",
    extra_ctx: Optional[dict[str, Any]] = None,
) -> str:
    """Render and (unless dry_run) send `email_id` to `user_id`, idempotently."""
    from core.services import app_config

    now = timezone.now()
    locale = _user_locale(user_id)
    ctx = _build_context(user_id, extra_ctx, locale)
    subject, html, text = render(email_id, ctx, locale)

    if app_config.get_bool("dry_run"):
        already = EmailSend.objects.filter(
            user_id=user_id, email_id=email_id, episode_key=episode_key, dry_run=True
        ).exists()
        if already:
            return DRY_RUN_SKIPPED
        EmailSend.objects.create(
            user_id=user_id,
            email_id=email_id,
            episode_key=episode_key,
            status=EmailSend.Status.DRY_RUN,
            dry_run=True,
            sent_at=now,
        )
        return DRY_RUN

    # Real send: one row per (user, email_id, episode_key) thanks to the
    # partial unique constraint. Reuse it across retries.
    row, _ = EmailSend.objects.get_or_create(
        user_id=user_id,
        email_id=email_id,
        episode_key=episode_key,
        dry_run=False,
        defaults={"status": EmailSend.Status.FAILED, "attempts": 0},
    )
    if row.status == EmailSend.Status.SENT:
        return ALREADY_SENT

    to = _recipient_email(user_id)
    if not to:
        row.status = EmailSend.Status.FAILED
        row.error = "no recipient email"
        row.attempts += 1
        row.save(update_fields=["status", "error", "attempts"])
        return FAILED

    try:
        result = ResendEmailProvider().send(to, subject, html, text)
    except ProviderError as e:
        result = DeliveryResult(success=False, error=str(e))

    if result.success:
        row.status = EmailSend.Status.SENT
        row.resend_message_id = result.external_message_id
        row.error = ""
        row.sent_at = now
        row.save(update_fields=["status", "resend_message_id", "error", "sent_at"])
        return SENT

    row.status = EmailSend.Status.FAILED
    row.error = result.error
    row.attempts += 1
    row.save(update_fields=["status", "error", "attempts"])
    logger.warning("deliver failed user=%s email=%s: %s", user_id, email_id, result.error)
    return FAILED

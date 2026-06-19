"""Resend email provider for product/lifecycle emails.

Transport only — idempotency, dry_run and the email_sends ledger live in
`core.notifications.lifecycle`. Uses the REST API directly via `requests`
(no extra dependency). Sender defaults to settings.EMAIL_FROM
(Alfredo <alfredo@continuu.it>).
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from .base import DeliveryResult, ProviderError

logger = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"


class ResendEmailProvider:
    channel = "resend"

    def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: str = "",
        *,
        reply_to: str = "",
    ) -> DeliveryResult:
        """Send one email. Raises ProviderError on misconfiguration; returns a
        DeliveryResult(success=False, ...) for transient API failures so the
        caller can record the attempt and retry next run."""
        key = getattr(settings, "RESEND_API_KEY", "")
        if not key:
            raise ProviderError("RESEND_API_KEY is not configured")
        if not to:
            raise ProviderError("missing recipient email")

        payload = {
            "from": settings.EMAIL_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to

        try:
            resp = requests.post(
                _RESEND_ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
        except requests.RequestException as e:
            return DeliveryResult(success=False, error=f"request failed: {e}")

        if resp.status_code >= 400:
            return DeliveryResult(
                success=False, error=f"resend {resp.status_code}: {resp.text[:300]}"
            )
        try:
            message_id = resp.json().get("id", "")
        except ValueError:
            message_id = ""
        return DeliveryResult(success=True, external_message_id=message_id)

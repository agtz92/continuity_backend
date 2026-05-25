"""Stripe SDK initialization.

Single import point so the API key is set once and re-imports don't fight
each other. Stripe's SDK uses a module-level `stripe.api_key` global.
"""

from __future__ import annotations

import stripe
from django.conf import settings


_initialized = False


def get_stripe():
    global _initialized
    if not _initialized:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        _initialized = True
    return stripe

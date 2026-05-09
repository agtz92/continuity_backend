"""Locale-aware string lookup for notification bodies.

Each supported locale exposes a flat dict of keys → format strings. The
`get(locale)` factory returns the dict; missing keys fall back to English so
a partially-translated locale still works.
"""

from __future__ import annotations

from typing import Dict

from . import en as _en
from . import es as _es

SUPPORTED_LOCALES = ("en", "es")
_BUNDLES: Dict[str, Dict[str, str]] = {
    "en": _en.STRINGS,
    "es": _es.STRINGS,
}


def get(locale: str) -> Dict[str, str]:
    """Return the strings dict for `locale`, falling back to English keys
    that aren't translated."""
    base = _BUNDLES["en"]
    if locale == "en" or locale not in _BUNDLES:
        return base
    bundle = _BUNDLES[locale]
    return {**base, **bundle}

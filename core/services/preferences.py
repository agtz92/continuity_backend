"""User UI preferences. Per-user singleton row keyed by user_id.

Today layout: which sections the user has hidden and the order they
appear in. Stored as JSON so adding new sections doesn't require a
migration — unknown ids are dropped on read and missing ones get the
default position.
"""

from __future__ import annotations

import uuid
from typing import Iterable

from django.core.exceptions import ValidationError

from ..models import UserPreferences


# Canonical list of Today sections. Order here IS the default order
# shown to a new user. Keep these ids in lockstep with the frontend
# and mobile clients — if you rename one here, rename it there too.
#
# `hideable=False` means the section is always visible (Today's Focus
# IS the page's identity). It still participates in `order` so the
# user can move it.
TODAY_SECTION_IDS: tuple[str, ...] = (
    "streak",
    "counters",
    "stalled-alert",
    "today-focus",
    "routines-today",
    "done-today",
    "closeable",
    "sleeping",
    "stale-ideas",
    "active-projects",
    "launched-with-tasks",
)

NON_HIDEABLE_TODAY_IDS: frozenset[str] = frozenset({"today-focus"})


def _get_or_create(user_id: uuid.UUID) -> UserPreferences:
    prefs, _ = UserPreferences.objects.get_or_create(user_id=user_id)
    return prefs


def get_today_layout(user_id: uuid.UUID) -> dict:
    """Return the user's effective Today layout.

    Always returns the full canonical order with stored overrides
    applied — clients don't need to merge with defaults themselves.
    Unknown ids in storage are dropped; sections that exist in code
    but not in storage fall back to their default index.
    """

    prefs = _get_or_create(user_id)
    raw = prefs.today_layout or {}
    stored_order: list[str] = [
        s for s in (raw.get("order") or []) if s in TODAY_SECTION_IDS
    ]
    # Sections added to the canonical list after the user last saved
    # get appended at the end so they're visibly "new" and the user
    # can drag them where they want.
    if stored_order:
        known = set(stored_order)
        order = stored_order + [
            sid for sid in TODAY_SECTION_IDS if sid not in known
        ]
    else:
        order = list(TODAY_SECTION_IDS)

    stored_hidden = raw.get("hidden") or []
    hidden = [
        s for s in stored_hidden
        if s in TODAY_SECTION_IDS and s not in NON_HIDEABLE_TODAY_IDS
    ]
    return {"order": order, "hidden": hidden}


def update_today_layout(
    user_id: uuid.UUID,
    *,
    order: Iterable[str] | None = None,
    hidden: Iterable[str] | None = None,
) -> dict:
    """Persist a partial update. Only fields explicitly passed are written.

    Validates that every id is canonical and that non-hideable sections
    are not in `hidden`. Returns the same shape as `get_today_layout`.
    """

    prefs = _get_or_create(user_id)
    raw = dict(prefs.today_layout or {})

    if order is not None:
        order_list = list(order)
        unknown = [s for s in order_list if s not in TODAY_SECTION_IDS]
        if unknown:
            raise ValidationError(f"Unknown section id(s): {', '.join(unknown)}")
        # Dedup while preserving order.
        seen: set[str] = set()
        deduped = []
        for s in order_list:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        raw["order"] = deduped

    if hidden is not None:
        hidden_list = list(hidden)
        unknown = [s for s in hidden_list if s not in TODAY_SECTION_IDS]
        if unknown:
            raise ValidationError(f"Unknown section id(s): {', '.join(unknown)}")
        locked = [s for s in hidden_list if s in NON_HIDEABLE_TODAY_IDS]
        if locked:
            raise ValidationError(
                f"Cannot hide always-visible section(s): {', '.join(locked)}"
            )
        raw["hidden"] = sorted(set(hidden_list))

    prefs.today_layout = raw
    prefs.save(update_fields=["today_layout", "updated_at"])
    return get_today_layout(user_id)


def reset_today_layout(user_id: uuid.UUID) -> dict:
    """Wipe stored layout — user goes back to canonical defaults."""

    prefs = _get_or_create(user_id)
    prefs.today_layout = {}
    prefs.save(update_fields=["today_layout", "updated_at"])
    return get_today_layout(user_id)

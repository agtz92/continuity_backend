"""Profile services. Per-user singleton row for editable account preferences."""

from __future__ import annotations

import uuid
from typing import Optional

from django.core.exceptions import ValidationError

from ..models import Profile

# Source of truth for which avatar IDs the server will accept. Must stay in
# sync with frontend/src/lib/avatars.ts and continuity-mobile/src/lib/avatars.ts.
# Avatars are stored as "{style}/{slug}"; since 2026-11 the only style is
# "vector" and the images ship inside each client (no Storage fetch).
AVATAR_SLUGS: tuple[str, ...] = ("momo", "yuki", "tako", "kuma", "hoshi", "pip", "tetsu")
VALID_AVATARS: set[str] = {f"vector/{slug}" for slug in AVATAR_SLUGS}

# Retired styles. Old mobile builds may still send them: map to the same
# character in vector instead of rejecting (migration 0039 converted stored rows).
LEGACY_AVATAR_STYLES: tuple[str, ...] = ("3d", "anime", "8bit")


def normalize_avatar(avatar: str) -> str:
    style, _, slug = avatar.partition("/")
    if style in LEGACY_AVATAR_STYLES:
        return f"vector/{slug}"
    return avatar


def get_profile(user_id: uuid.UUID) -> Profile:
    profile, _ = Profile.objects.get_or_create(user_id=user_id)
    return profile


def set_avatar(user_id: uuid.UUID, avatar: Optional[str]) -> Profile:
    profile = get_profile(user_id)
    if avatar is None or avatar == "":
        profile.avatar = ""
    else:
        avatar = normalize_avatar(avatar)
        if avatar not in VALID_AVATARS:
            raise ValidationError(f"Unknown avatar id: {avatar}")
        profile.avatar = avatar
    profile.save()
    return profile


def set_first_name(user_id: uuid.UUID, first_name: Optional[str]) -> Profile:
    """Set the user's first name. Empty string clears it.

    Trimmed and capped at 50 chars (matches the column constraint). The UI
    rejects empty in onboarding step 1; this service stays permissive so
    callers can also use it to clear the value during account cleanup.
    """
    profile = get_profile(user_id)
    if first_name is None:
        profile.first_name = ""
    else:
        cleaned = first_name.strip()
        if len(cleaned) > 50:
            raise ValidationError("first_name is too long (max 50 characters)")
        profile.first_name = cleaned
    profile.save()
    return profile

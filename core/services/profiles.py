"""Profile services. Per-user singleton row for editable account preferences."""

from __future__ import annotations

import uuid
from typing import Optional

from django.core.exceptions import ValidationError

from ..models import Profile

# Source of truth for which avatar IDs the server will accept. Must stay in
# sync with frontend/src/lib/avatars.ts AVATAR_CATALOG. Avatars are stored as
# "{style}/{slug}" strings; the image lives at
# {SUPABASE_URL}/storage/v1/object/public/avatars/{style}/{slug}.png.
VALID_AVATARS: set[str] = {
    # 3D
    "3d/momo", "3d/yuki", "3d/tako", "3d/kuma", "3d/hoshi", "3d/pip", "3d/tetsu",
    # Anime
    "anime/momo", "anime/yuki", "anime/tako", "anime/kuma", "anime/hoshi", "anime/pip", "anime/tetsu",
    # 8-bit
    "8bit/momo", "8bit/yuki", "8bit/tako", "8bit/kuma", "8bit/hoshi", "8bit/pip", "8bit/tetsu",
    # Vector
    "vector/momo", "vector/yuki", "vector/tako", "vector/kuma", "vector/hoshi", "vector/pip", "vector/tetsu",
}


def get_profile(user_id: uuid.UUID) -> Profile:
    profile, _ = Profile.objects.get_or_create(user_id=user_id)
    return profile


def set_avatar(user_id: uuid.UUID, avatar: Optional[str]) -> Profile:
    profile = get_profile(user_id)
    if avatar is None or avatar == "":
        profile.avatar = ""
    else:
        if avatar not in VALID_AVATARS:
            raise ValidationError(f"Unknown avatar id: {avatar}")
        profile.avatar = avatar
    profile.save()
    return profile

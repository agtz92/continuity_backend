"""Avatars are vector-only; retired styles map to the same character."""

import uuid
from importlib import import_module

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError

from core.models import Profile
from core.services import profiles


@pytest.mark.django_db
def test_set_avatar_accepts_vector():
    uid = uuid.uuid4()
    assert profiles.set_avatar(uid, "vector/kuma").avatar == "vector/kuma"


@pytest.mark.django_db
@pytest.mark.parametrize("old", ["3d/momo", "anime/momo", "8bit/momo"])
def test_set_avatar_maps_legacy_styles_to_vector(old):
    uid = uuid.uuid4()
    assert profiles.set_avatar(uid, old).avatar == "vector/momo"


@pytest.mark.django_db
@pytest.mark.parametrize("bad", ["vector/nope", "pixel/momo", "momo"])
def test_set_avatar_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        profiles.set_avatar(uuid.uuid4(), bad)


@pytest.mark.django_db
def test_migration_moves_stored_avatars_to_vector():
    rows = {
        "3d/tako": "vector/tako",
        "anime/pip": "vector/pip",
        "8bit/hoshi": "vector/hoshi",
        "vector/yuki": "vector/yuki",
        "": "",
    }
    ids = {}
    for avatar in rows:
        p = Profile.objects.create(user_id=uuid.uuid4(), avatar=avatar)
        ids[p.pk] = avatar

    mig = import_module("core.migrations.0039_avatars_vector_only")
    mig.to_vector(apps, None)

    for pk, before in ids.items():
        assert Profile.objects.get(pk=pk).avatar == rows[before]

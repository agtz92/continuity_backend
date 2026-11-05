"""Avatars: retire the 3d/anime/8bit styles.

Every stored avatar keeps its character and moves to the vector style
(e.g. "3d/momo" -> "vector/momo"). Not reversible: the original style is
not kept anywhere, and the old images are no longer offered.
"""

from django.db import migrations

LEGACY_STYLES = ("3d", "anime", "8bit")


def to_vector(apps, schema_editor):
    Profile = apps.get_model("core", "Profile")
    for style in LEGACY_STYLES:
        prefix = f"{style}/"
        for p in Profile.objects.filter(avatar__startswith=prefix).only("pk", "avatar"):
            p.avatar = "vector/" + p.avatar[len(prefix):]
            p.save(update_fields=["avatar"])


class Migration(migrations.Migration):
    dependencies = [("core", "0038_remove_icloud_calendar")]

    operations = [migrations.RunPython(to_vector, migrations.RunPython.noop)]

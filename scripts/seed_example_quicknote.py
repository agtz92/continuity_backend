"""One-off: seed an English example Quick Note for a docs/demo account.

Run from the backend dir with the repo-root venv:
    .venv/bin/python manage.py shell < scripts/seed_example_quicknote.py

Idempotent: re-running deletes the previous example note (matched by exact
title) and recreates it, so the screenshot data stays stable.
"""

from core.assistant.management.commands.promote_admin import (
    _lookup_supabase_user_id,
)
from core.models import Project, ProjectStatus, Priority, QuickNote
from core.services import categories as cat_svc
from core.services import quick_notes as qn_svc

EMAIL = "agtz.docs@gmail.com"
NOTE_TITLE = "API Integration — Working Notes"

uid = _lookup_supabase_user_id(EMAIL)
print(f"Resolved {EMAIL} -> {uid}")

# Category badge (blue) — get_or_create via service.
category = cat_svc.create_category(uid, name="Engineering", color="blue")

# Linked project — reuse if it already exists, else create one.
project = Project.objects.filter(user_id=uid, name="Mobile App v2").first()
if project is None:
    project = Project.objects.create(
        user_id=uid,
        name="Mobile App v2",
        description="Rebuild of the mobile client on the new GraphQL API.",
        status=ProjectStatus.ACTIVE,
        priority=Priority.HIGH,
        category=category,
    )
    print(f"Created project {project.id}")
else:
    print(f"Reusing project {project.id}")

# Drop any prior example note (same title) so the script is re-runnable.
deleted = QuickNote.objects.filter(user_id=uid, title=NOTE_TITLE).count()
for n in QuickNote.objects.filter(user_id=uid, title=NOTE_TITLE):
    qn_svc.delete_quick_note(uid, n.id)
if deleted:
    print(f"Removed {deleted} previous example note(s)")

note = qn_svc.create_quick_note(
    uid,
    title=NOTE_TITLE,
    category_id=category.id,
    project_id=project.id,
    pinned=True,
)

SECTIONS = [
    (
        "Goal",
        "Wire the mobile client to the new GraphQL endpoint and replace the "
        "legacy REST calls. Ship behind a feature flag so we can roll back fast.",
        False,
    ),
    (
        "Decisions",
        "- **Auth:** reuse the existing Supabase JWT — no new token flow.\n"
        "- **Pagination:** cursor-based, 20 items per page.\n"
        "- **Errors:** surface a single toast; log the full payload to Sentry.",
        False,
    ),
    (
        "Open questions",
        "- Do we cache offline reads, or fail loudly when there's no network?\n"
        "- Who owns the rate-limit budget — mobile or backend?",
        False,
    ),
    (
        "Done ✅ (this one starts folded)",
        "- [x] Schema reviewed with backend\n"
        "- [x] Staging endpoint reachable from device\n"
        "- [ ] QA pass on Android",
        True,
    ),
]

for pos, (heading, body, collapsed) in enumerate(SECTIONS):
    qn_svc.add_section(
        uid,
        note.id,
        heading=heading,
        body=body,
        position=pos,
        collapsed=collapsed,
    )

print(f"Created QuickNote {note.id} with {len(SECTIONS)} sections")
print("Done.")

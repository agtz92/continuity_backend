"""Quick Notes services — notebook-style notes with collapsible sections.

A QuickNote is a top-level note (categorizable, optionally linked to a project
or standalone) that owns an ordered list of NoteSection blocks. Mirrors the
ideas/notes service conventions: every function takes `user_id` first and
filters by it, quotas are checked in `create_*`/`add_*`, and the assistant
context version is bumped after writes.
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.db import transaction
from django.db.models import Q

from ..models import ActivityKind, Category, NoteSection, Project, QuickNote
from ..quotas import check_entity_quota
from ._cache import bump_context_version
from .activities import log_event
from .projects import NotFoundError


# ---------- helpers ----------


def _resolve_category(user_id: uuid.UUID, category_id) -> Optional[Category]:
    if not category_id:
        return None
    cat = Category.objects.filter(pk=category_id, user_id=user_id).first()
    if cat is None:
        raise NotFoundError("Category not found")
    return cat


def _resolve_project(user_id: uuid.UUID, project_id) -> Optional[Project]:
    if not project_id:
        return None
    proj = Project.objects.filter(pk=project_id, user_id=user_id).first()
    if proj is None:
        raise NotFoundError("Project not found")
    return proj


def _touch_note(user_id: uuid.UUID, note_id) -> None:
    """Bump the parent note's updated_at so editing a section floats the note
    to the top of the recently-updated ordering (auto_now fires on save())."""
    note = QuickNote.objects.filter(pk=note_id, user_id=user_id).first()
    if note is not None:
        note.save(update_fields=["updated_at"])


# ---------- notes ----------


def list_quick_notes(
    user_id: uuid.UUID,
    *,
    search: Optional[str] = None,
    category_id=None,
    project_id=None,
    pinned: Optional[bool] = None,
) -> list[QuickNote]:
    qs = QuickNote.objects.filter(user_id=user_id)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if project_id:
        qs = qs.filter(project_id=project_id)
    if pinned is not None:
        qs = qs.filter(pinned=pinned)
    if search and search.strip():
        s = search.strip()
        qs = qs.filter(
            Q(title__icontains=s)
            | Q(sections__heading__icontains=s)
            | Q(sections__body__icontains=s)
        ).distinct()
    return list(qs.prefetch_related("sections"))


def get_quick_note(user_id: uuid.UUID, note_id) -> QuickNote:
    obj = (
        QuickNote.objects.filter(pk=note_id, user_id=user_id)
        .prefetch_related("sections")
        .first()
    )
    if obj is None:
        raise NotFoundError("QuickNote not found")
    return obj


def create_quick_note(
    user_id: uuid.UUID,
    *,
    title: str = "",
    category_id=None,
    project_id=None,
    pinned: bool = False,
) -> QuickNote:
    check_entity_quota(user_id, "quick_notes")
    category = _resolve_category(user_id, category_id)
    project = _resolve_project(user_id, project_id)
    note = QuickNote.objects.create(
        user_id=user_id,
        title=(title or "").strip(),
        category=category,
        project=project,
        pinned=bool(pinned),
    )
    log_event(
        user_id,
        kind=ActivityKind.QUICK_NOTE_CREATED,
        entity_id=note.id,
        entity_title=note.title,
        project_id=project.id if project else None,
    )
    bump_context_version(user_id)
    return note


def update_quick_note(
    user_id: uuid.UUID,
    note_id,
    *,
    title: str = "",
    category_id=None,
    project_id=None,
    pinned: bool = False,
) -> QuickNote:
    note = get_quick_note(user_id, note_id)
    note.title = (title or "").strip()
    note.category = _resolve_category(user_id, category_id)
    note.project = _resolve_project(user_id, project_id)
    note.pinned = bool(pinned)
    note.save()
    bump_context_version(user_id)
    return note


def set_pin(user_id: uuid.UUID, note_id, pinned: bool) -> QuickNote:
    note = get_quick_note(user_id, note_id)
    note.pinned = bool(pinned)
    note.save(update_fields=["pinned", "updated_at"])
    bump_context_version(user_id)
    return note


def delete_quick_note(user_id: uuid.UUID, note_id) -> None:
    note = (
        QuickNote.objects.filter(pk=note_id, user_id=user_id)
        .only("id", "title")
        .first()
    )
    QuickNote.objects.filter(pk=note_id, user_id=user_id).delete()
    if note is not None:
        log_event(
            user_id,
            kind=ActivityKind.QUICK_NOTE_DELETED,
            entity_id=note.id,
            entity_title=note.title,
        )
    bump_context_version(user_id)


# ---------- sections ----------


def get_section(user_id: uuid.UUID, section_id) -> NoteSection:
    obj = NoteSection.objects.filter(pk=section_id, user_id=user_id).first()
    if obj is None:
        raise NotFoundError("NoteSection not found")
    return obj


def add_section(
    user_id: uuid.UUID,
    note_id,
    *,
    heading: str = "",
    body: str = "",
    position: Optional[int] = None,
    collapsed: bool = False,
) -> NoteSection:
    note = get_quick_note(user_id, note_id)  # ownership check
    check_entity_quota(user_id, "sections_per_note", project_id=note.id)
    if position is None:
        last = (
            NoteSection.objects.filter(note_id=note.id)
            .order_by("-position")
            .first()
        )
        position = (last.position + 1) if last else 0
    section = NoteSection.objects.create(
        user_id=user_id,
        note=note,
        heading=(heading or "").strip(),
        body=body or "",
        position=position,
        collapsed=bool(collapsed),
    )
    note.save(update_fields=["updated_at"])
    bump_context_version(user_id)
    return section


def update_section(
    user_id: uuid.UUID,
    section_id,
    *,
    heading: str = "",
    body: str = "",
    collapsed: Optional[bool] = None,
) -> NoteSection:
    section = get_section(user_id, section_id)
    section.heading = (heading or "").strip()
    section.body = body or ""
    if collapsed is not None:
        section.collapsed = bool(collapsed)
    section.save()
    _touch_note(user_id, section.note_id)
    bump_context_version(user_id)
    return section


def delete_section(user_id: uuid.UUID, section_id) -> None:
    section = (
        NoteSection.objects.filter(pk=section_id, user_id=user_id)
        .only("id", "note_id")
        .first()
    )
    note_id = section.note_id if section else None
    NoteSection.objects.filter(pk=section_id, user_id=user_id).delete()
    if note_id is not None:
        _touch_note(user_id, note_id)
    bump_context_version(user_id)


def reorder_sections(user_id: uuid.UUID, note_id, ordered_ids: list) -> QuickNote:
    note = get_quick_note(user_id, note_id)
    sections = {str(s.id): s for s in note.sections.all()}
    with transaction.atomic():
        for idx, sid in enumerate(ordered_ids):
            s = sections.get(str(sid))
            if s is not None and s.position != idx:
                s.position = idx
                s.save(update_fields=["position"])
        note.save(update_fields=["updated_at"])
    bump_context_version(user_id)
    return get_quick_note(user_id, note_id)

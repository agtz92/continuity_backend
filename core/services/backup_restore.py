"""Restore a backup file into the person's account: on the server, in one
transaction.

The file is the one `data_export.build_export` produces (the same JSON as
"Descargar mis datos"). Older client-side backups (`exportedAt`, camelCase,
`activities`, `projectNotes`, v1 `updates`) are converted first, so files
people already saved keep working.

Rules:
- **All or nothing.** Everything runs in `transaction.atomic()`; an invalid row
  or a quota overrun rolls the whole restore back.
- **New ids.** Every restored row gets a fresh id and references are remapped,
  so a file can never touch rows of another account.
- **Merge** skips rows whose id already exists in the account (re-importing
  the same file twice does not duplicate) and maps categories by name.
- **Replace** first deletes only the kinds the file carries: a legacy file
  without routines or Quick Notes leaves those alone.
- Timestamps (`created`, `updated_at`, `last_activity`) are kept from the file.
- Live signals are off for the transaction (`app.live_off`); the client
  refetches when the mutation returns.
- Settings, assistant conversations and the rest of the export are not
  restored: only content.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Optional

from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.db.models import Count

from ..models import (
    Activity,
    Category,
    Idea,
    NoteSection,
    Project,
    ProjectNote,
    QuickNote,
    Routine,
    RoutineOccurrence,
    Task,
    TaskBlocker,
)
from ..quotas import ENTITY_QUOTAS, EntityQuotaExceeded, _count, _get_plan
from ._cache import bump_context_version
from .data_export import FIELDS

MODES = ("merge", "replace")
MAX_ROWS = 50_000

#: (section key, model, {fk attname: (section it points to, required)}).
#: Order matters: a section only points to sections above it.
SECTIONS: tuple[tuple[str, type[models.Model], dict[str, tuple[str, bool]]], ...] = (
    ("categories", Category, {}),
    ("projects", Project, {"category_id": ("categories", False)}),
    ("project_notes", ProjectNote, {"project_id": ("projects", True)}),
    ("tasks", Task, {"project_id": ("projects", False)}),
    (
        "task_blockers",
        TaskBlocker,
        {"blocked_task_id": ("tasks", True), "blocking_task_id": ("tasks", False)},
    ),
    ("routines", Routine, {"project_id": ("projects", False)}),
    ("routine_occurrences", RoutineOccurrence, {"routine_id": ("routines", True)}),
    ("ideas", Idea, {}),
    (
        "quick_notes",
        QuickNote,
        {"category_id": ("categories", False), "project_id": ("projects", False)},
    ),
    ("quick_note_sections", NoteSection, {"note_id": ("quick_notes", True)}),
    ("activity", Activity, {}),
)

#: Auto-set columns whose value comes from the file after the insert.
_TIMESTAMPS = ("created", "updated_at", "last_activity")

#: Activity points to other rows by plain UUID columns, not FKs.
_ACTIVITY_REFS = {
    "entity_id": None,  # any section
    "project_id": "projects",
    "target_project_id": "projects",
}


class BackupInvalid(Exception):
    """The file can't be read as a backup; nothing was written."""


# ---------------------------------------------------------------- parsing


def parse_backup(raw: str) -> dict[str, list[dict]]:
    """JSON text → {section: rows}, with legacy files converted."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise BackupInvalid(f"Not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise BackupInvalid("Not a backup file")
    if "exportedAt" in data or "activities" in data or "updates" in data:
        data = _from_legacy(data)
    out: dict[str, list[dict]] = {}
    for key, _, _ in SECTIONS:
        if key not in data:
            continue
        rows = data[key]
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise BackupInvalid(f"'{key}' must be a list of objects")
        out[key] = rows
    if not out:
        raise BackupInvalid("Not a backup file")
    if sum(len(r) for r in out.values()) > MAX_ROWS:
        raise BackupInvalid(f"Too many rows (max {MAX_ROWS})")
    return out


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _from_legacy(data: dict) -> dict:
    """Client-side backups (v1/v2): camelCase rows from the dashboard query."""

    def rows(key: str) -> list[dict]:
        v = data.get(key) or []
        return [{_snake(k): val for k, val in r.items()} for r in v if isinstance(r, dict)]

    out: dict[str, list[dict]] = {}
    if "projects" in data:
        out["projects"] = rows("projects")
    if "tasks" in data:
        tasks = rows("tasks")
        blockers = []
        for t in tasks:
            for b in t.pop("blockers", None) or []:
                if isinstance(b, dict):
                    blockers.append({_snake(k): v for k, v in b.items()})
        out["tasks"] = tasks
        out["task_blockers"] = blockers
    if "ideas" in data:
        out["ideas"] = rows("ideas")
    if "projectNotes" in data:
        out["project_notes"] = rows("projectNotes")
    if "activities" in data or "updates" in data:
        activity = rows("activities")
        # v1: user notes as a flat list.
        for u in rows("updates"):
            activity.append(
                {"kind": "note", "project_id": u.get("project_id"), "note": u.get("note", ""), "created": u.get("date")}
            )
        out["activity"] = activity
    for section in ("projects", "activity"):
        for r in out.get(section, []):
            for k in ("kind", "status", "priority"):
                if isinstance(r.get(k), str):
                    r[k] = r[k].lower()
    return out


# ---------------------------------------------------------------- restore


def restore_backup(user_id: uuid.UUID, data: dict[str, list[dict]], *, mode: str) -> dict[str, int]:
    """Write `data` (from `parse_backup`) into the account. Returns rows
    created per section. Raises `BackupInvalid` or `EntityQuotaExceeded`
    with nothing written."""
    if mode not in MODES:
        raise BackupInvalid(f"Unknown mode '{mode}'")

    plan = _get_plan(user_id)
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("set local app.live_off = '1'")
        before = _quota_counts(user_id, plan)

        if mode == "replace":
            # Children first; only the kinds the file carries.
            for key, model, _ in reversed(SECTIONS):
                if key in data:
                    model.objects.filter(user_id=user_id).delete()

        id_maps: dict[str, dict[str, uuid.UUID]] = {key: {} for key, _, _ in SECTIONS}
        created: dict[str, int] = {}
        for key, model, fks in SECTIONS:
            if key in data:
                created[key] = _restore_section(user_id, key, model, fks, data[key], id_maps, mode)

        _check_quotas(user_id, plan, before)
    bump_context_version(user_id)
    return created


def _restore_section(
    user_id: uuid.UUID,
    key: str,
    model: type[models.Model],
    fks: dict[str, tuple[str, bool]],
    rows: list[dict],
    id_maps: dict[str, dict[str, uuid.UUID]],
    mode: str,
) -> int:
    id_map = id_maps[key]
    if mode == "merge":
        file_ids = [_uuid(r.get("id")) for r in rows]
        existing = set(
            model.objects.filter(user_id=user_id, pk__in=[i for i in file_ids if i]).values_list("pk", flat=True)
        )
        for i in existing:
            id_map[str(i)] = i
        if model is Category:
            by_name = dict(Category.objects.filter(user_id=user_id).values_list("name", "pk"))

    fields = {f.attname: f for f in model._meta.concrete_fields}
    seen_names: set[str] = set()
    objs, stamps = [], []
    for i, row in enumerate(rows):
        old_id = str(row.get("id") or "")
        if old_id and old_id in id_map:
            continue  # merge: already in the account
        kwargs: dict[str, Any] = {"user_id": user_id}
        skip = False
        for attname, (target, required) in fks.items():
            ref = row.get(attname)
            new = id_maps[target].get(str(ref)) if ref else None
            if new is None and required:
                skip = True  # orphan in the file (its parent wasn't exported)
                break
            kwargs[attname] = new
        if skip:
            continue
        stamp = {}
        for attname in FIELDS[model]:
            if attname == "id" or attname in fks or attname not in row:
                continue
            value = row[attname]
            field = fields[attname]
            if value is None and not field.null:
                continue
            try:
                value = field.clean(value, None)
            except ValidationError as e:
                raise BackupInvalid(f"{key}[{i}].{attname}: {'; '.join(e.messages)}") from e
            if attname in _TIMESTAMPS:
                stamp[attname] = value
            else:
                kwargs[attname] = value
        if model is Activity:
            for attname, target in _ACTIVITY_REFS.items():
                ref = kwargs.get(attname)
                if ref is not None:
                    kwargs[attname] = _remap(ref, target, id_maps)
        if model is Category:
            name = kwargs.get("name", "")
            if mode == "merge" and name in by_name:
                if old_id:
                    id_map[old_id] = by_name[name]
                continue
            if name in seen_names:
                continue
            seen_names.add(name)
        obj = model(**kwargs)
        if old_id:
            id_map[old_id] = obj.pk
        objs.append(obj)
        stamps.append(stamp)

    model.objects.bulk_create(
        objs, batch_size=500, ignore_conflicts=model is RoutineOccurrence
    )
    # bulk_create applied auto_now/auto_now_add; put the file's values back.
    for name in _TIMESTAMPS:
        changed = []
        for obj, stamp in zip(objs, stamps):
            if name in stamp:
                setattr(obj, name, stamp[name])
                changed.append(obj)
        if changed:
            model.objects.bulk_update(changed, [name], batch_size=500)
    return len(objs)


def _uuid(v: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(v))
    except (TypeError, ValueError):
        return None


def _remap(ref: uuid.UUID, target: Optional[str], id_maps: dict[str, dict[str, uuid.UUID]]) -> uuid.UUID:
    sections = [target] if target else list(id_maps)
    for s in sections:
        if str(ref) in id_maps[s]:
            return id_maps[s][str(ref)]
    return ref  # points to something deleted before the backup: keep as history


# ---------------------------------------------------------------- quotas

_PER_PARENT = {
    "tasks_per_project": (Task, "project_id", {"done": False}),
    "notes_per_project": (ProjectNote, "project_id", {}),
    "sections_per_note": (NoteSection, "note_id", {}),
}


def _quota_counts(user_id: uuid.UUID, plan: str) -> dict[tuple[str, Any], int]:
    counts: dict[tuple[str, Any], int] = {}
    for kind, caps in ENTITY_QUOTAS.items():
        if caps.get(plan) is None:
            continue
        if kind in _PER_PARENT:
            model, parent, extra = _PER_PARENT[kind]
            groups = (
                model.objects.filter(user_id=user_id, **extra)
                .exclude(**{parent: None})
                .values(parent)
                .annotate(n=Count("pk"))
            )
            for g in groups:
                counts[(kind, g[parent])] = g["n"]
        else:
            counts[(kind, None)] = _count(kind, user_id, None)
    return counts


def _check_quotas(user_id: uuid.UUID, plan: str, before: dict[tuple[str, Any], int]) -> None:
    """Fail when the restore pushed a count over the plan cap. A count that
    was already over (downgraded account) only fails if the restore grew it."""
    for (kind, parent), n in _quota_counts(user_id, plan).items():
        cap = ENTITY_QUOTAS[kind][plan]
        if n > cap and n > before.get((kind, parent), 0):
            raise EntityQuotaExceeded(kind=kind, current=n, cap=cap, plan=plan)

"""Cross-entity search service.

Postgres `ILIKE` over the user's own rows. Used by the assistant when
the user asks open-ended questions like "find anything about onboarding".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from django.db.models import Q

from ..models import Idea, Project, ProjectNote, Task

SearchKind = Literal["project", "task", "idea", "note"]


@dataclass
class SearchHit:
    kind: SearchKind
    id: uuid.UUID
    title: str
    snippet: str
    project_id: Optional[uuid.UUID] = None


def _truncate(text: str, length: int = 280) -> str:
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[: length - 1] + "…"


def search(
    user_id: uuid.UUID,
    *,
    query: str,
    kind: Optional[SearchKind] = None,
    limit: int = 20,
) -> list[SearchHit]:
    """Case-insensitive substring search. Returns up to `limit` hits across kinds."""
    q = (query or "").strip()
    limit = max(1, min(int(limit), 50))
    if not q:
        return []

    hits: list[SearchHit] = []

    if kind in (None, "project"):
        for p in Project.objects.filter(user_id=user_id).filter(
            Q(name__icontains=q)
            | Q(description__icontains=q)
            | Q(why__icontains=q)
            | Q(next_step__icontains=q)
        )[:limit]:
            hits.append(
                SearchHit(
                    kind="project",
                    id=p.id,
                    title=p.name,
                    snippet=_truncate(p.description or p.next_step or p.why),
                )
            )

    if kind in (None, "task"):
        for t in Task.objects.filter(user_id=user_id, title__icontains=q)[:limit]:
            hits.append(
                SearchHit(
                    kind="task",
                    id=t.id,
                    title=t.title,
                    snippet="done" if t.done else "open",
                    project_id=t.project_id,
                )
            )

    if kind in (None, "idea"):
        for i in Idea.objects.filter(user_id=user_id).filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(why__icontains=q)
        )[:limit]:
            hits.append(
                SearchHit(
                    kind="idea",
                    id=i.id,
                    title=i.title,
                    snippet=_truncate(i.description or i.why),
                )
            )

    if kind in (None, "note"):
        for n in ProjectNote.objects.filter(user_id=user_id).filter(
            Q(title__icontains=q) | Q(body__icontains=q)
        )[:limit]:
            hits.append(
                SearchHit(
                    kind="note",
                    id=n.id,
                    title=n.title or _truncate(n.body, 80),
                    snippet=_truncate(n.body),
                    project_id=n.project_id,
                )
            )

    return hits[:limit]

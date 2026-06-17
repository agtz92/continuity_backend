"""Loop's graveyard autopsy (STATE_CLOSURE_FINAL.md §5.3, D12).

Compute-on-write: a per-project reflection is generated once, when a project is
killed (Capa A); the cross-project pattern is recomputed only when a new project
dies, above a 3-death threshold (Capa B). Reading them never calls the model.

All work here is BEST-EFFORT and Pro+: any failure (no API key, free plan, API
error) is swallowed so the kill itself always succeeds. Revive marks the cached
pattern stale so the next death recomputes it.
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.utils import timezone

from ..assistant.models import AccountProfile
from ..models import GraveyardInsight, Project, ProjectStatus
from ..quotas import effective_plan

logger = logging.getLogger(__name__)

GRAVEYARD_PATTERN_THRESHOLD = 3
_AUTOPSY_PLANS = {"pro", "studio", "admin"}


def _plan(user_id: uuid.UUID) -> str:
    profile = AccountProfile.objects.filter(user_id=user_id).only("plan").first()
    return effective_plan(profile) if profile else "free"


def _complete(prompt: str, *, max_tokens: int = 320) -> str:
    from ..assistant.anthropic_client import _build_anthropic_client

    client = _build_anthropic_client()
    resp = client.messages.create(
        model=settings.ASSISTANT_MODEL_FAST,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()


def maybe_generate_on_kill(user_id: uuid.UUID, project: Project) -> None:
    """Generate the per-project reflection and (>=3 deaths) the pattern. Never raises."""
    try:
        if not settings.ANTHROPIC_API_KEY:
            return
        if _plan(user_id) not in _AUTOPSY_PLANS:
            return
        _generate_reflection(project)
        _recompute_pattern(user_id)
    except Exception:  # best-effort: the kill already committed
        logger.exception("graveyard autopsy failed for project %s", project.id)


def mark_pattern_stale(user_id: uuid.UUID) -> None:
    """Called on revive — the death set changed, so the cached pattern is stale."""
    GraveyardInsight.objects.filter(user_id=user_id).update(is_stale=True)


def _generate_reflection(project: Project) -> None:
    prompt = (
        "A user just ended (killed) a project on purpose. Write a short, "
        "compassionate reflection (2-3 sentences, second person, no preamble) on "
        "why it likely ended and the lesson worth keeping. Be a peer, not a coach. "
        "Do not use em-dashes.\n\n"
        f"Project: {project.name}\n"
        f"Why they killed it: {project.killed_reason}\n"
        f"What they learned: {project.killed_learnings}\n"
        f"Would restart: {project.killed_would_restart or 'n/a'}\n"
    )
    text = _complete(prompt, max_tokens=200)
    if text:
        project.killed_ai_reflection = text
        project.save(update_fields=["killed_ai_reflection"])


def _recompute_pattern(user_id: uuid.UUID) -> None:
    killed = list(
        Project.objects.filter(user_id=user_id, status=ProjectStatus.KILLED)
        .order_by("-killed_at")
        .values("name", "killed_reason", "killed_learnings", "killed_would_restart")[:30]
    )
    insight, _ = GraveyardInsight.objects.get_or_create(user_id=user_id)

    if len(killed) < GRAVEYARD_PATTERN_THRESHOLD:
        insight.deaths_count = len(killed)
        insight.is_stale = False
        insight.save(update_fields=["deaths_count", "is_stale", "updated_at"])
        return

    lines = "\n".join(
        f"- {k['name']}: reason={k['killed_reason']}; learned={k['killed_learnings']}"
        for k in killed
    )
    prompt = (
        "Here are a user's killed projects. In 3-4 sentences, name the strongest "
        "recurring PATTERN in why they die and one concrete change for next time. "
        "Compassionate peer tone, second person, no preamble, no em-dashes.\n\n"
        f"{lines}\n"
    )
    text = _complete(prompt, max_tokens=320)
    if text:
        insight.body = text
        insight.deaths_count = len(killed)
        insight.computed_at = timezone.now()
        insight.is_stale = False
        insight.save()

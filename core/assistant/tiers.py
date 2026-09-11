"""What the assistant does for each plan — the single source of truth.

Before this module the answer to "what can this plan do with Loop?" was
spelled out in six places that did not talk to each other: the chat view,
`prompts.is_write_tier`, 32 `plan_required="pro"` decorators, the MCP
policy, `canWrite` in the web panel and its mirror in the mobile app.
Re-tiering meant touching all of them and remembering all of them.

Three modes, one function:

- ``none``   — no assistant. The client shows a placeholder instead of a
  composer. `/chat/` and `/actions/` both refuse with ``plan_required``.
- ``canned`` — a fixed catalogue of read-only queries (`canned.py`). Runs
  server-side against the existing read tools. **Never calls Anthropic**,
  so it costs nothing and cannot be rate-limited by the model.
- ``llm``    — the real chat: Anthropic, tool use, writes.

`GET /usage/` returns the mode so web and mobile read the rule instead of
re-deriving it.

Deliberately NOT the MCP connector's policy: that one lives in
`core/mcp/policy.py` and filters on `Tool.mutates`, so re-tiering the
in-app assistant never silently moves the connector. The two channels are
priced differently on purpose — the connector spends the user's own Claude
subscription, the assistant spends ours.
"""

from __future__ import annotations

from .models import Plan


#: Assistant modes, cheapest to richest.
MODE_NONE = "none"
MODE_CANNED = "canned"
MODE_LLM = "llm"

ASSISTANT_MODE_BY_PLAN: dict[str, str] = {
    Plan.FREE.value: MODE_NONE,
    Plan.PRO.value: MODE_CANNED,
    Plan.STUDIO.value: MODE_LLM,
    Plan.ADMIN.value: MODE_LLM,
}

#: Plan a mutating tool requires. Every `@tool(..., plan_required=WRITE_TIER)`
#: reads from here, so moving writes between tiers is this one line.
WRITE_TIER = Plan.STUDIO.value


def assistant_mode(plan: str) -> str:
    """Which assistant a plan gets. Unknown plans fall back to the poorest."""
    return ASSISTANT_MODE_BY_PLAN.get(plan, MODE_NONE)


def is_llm_tier(plan: str) -> bool:
    """True when the plan may call the Anthropic API.

    Also gates `/parse-capture/`: interpreting a capture line is the same
    frontier (our money reaching the model), so it lives in one place.
    """
    return assistant_mode(plan) == MODE_LLM


def is_canned_tier(plan: str) -> bool:
    """True when the plan gets the deterministic action catalogue."""
    return assistant_mode(plan) == MODE_CANNED


def has_assistant(plan: str) -> bool:
    """True when the plan gets any assistant at all."""
    return assistant_mode(plan) != MODE_NONE

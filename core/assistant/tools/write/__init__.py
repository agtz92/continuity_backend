"""Read-write tools — the `llm` tier.

Every tool here is `plan_required=WRITE_TIER` (studio/admin), so it is
invisible to any plan below it (see `schemas_for_anthropic` / `call` in
this package's __init__). Free has no assistant at all and Pro's chat is
the deterministic catalogue in `core/assistant/canned.py`, which only ever
reaches read tools.

Note that the MCP connector does NOT follow `plan_required` — it filters
on `Tool.mutates` through `core/mcp/policy.py`, so re-tiering here never
silently moves the connector. Change both, deliberately, or neither.

Handlers delegate to `core.services.*` so validation and activity logging
stay shared with the GraphQL resolvers.

The service-layer `update_*` functions are full-replace (omitted fields
reset to their defaults), so the update tools here fetch the current row
first and merge the caller's changes onto it — a tool can pass just the
fields it wants to change.

Destructive tools (`delete_*`) require an explicit `confirm: true`. If it
is missing they return a `needs_confirmation` payload instead of deleting,
so the model is forced to round-trip a confirmation through the user.
"""

from __future__ import annotations

# Importing the domain modules triggers registration via the @tool decorator
# (same mechanism as the parent `tools` package). Order is irrelevant.
from . import categories  # noqa: E402, F401
from . import ideas  # noqa: E402, F401
from . import notes  # noqa: E402, F401
from . import projects  # noqa: E402, F401
from . import quick_notes  # noqa: E402, F401
from . import routines  # noqa: E402, F401
from . import tasks  # noqa: E402, F401

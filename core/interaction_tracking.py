"""Strawberry extension: count one interaction per successful mutation.

Hooks the GraphQL execution so that every **successful mutation** records a
single interaction tagged by the client channel (web/mobile via the
``X-Continuity-Client`` header). Reads (queries) and failed mutations are not
counted — this is the "actions with effect" definition.

Best-effort: any error here is swallowed so it can never break a request.
Assistant messages and connector tool calls are recorded at their own call
sites (they are not GraphQL operations).
"""

from __future__ import annotations

import logging

from strawberry.extensions import SchemaExtension

from core.services.interactions import record_interaction, source_from_request

logger = logging.getLogger(__name__)


def _is_mutation(op_type) -> bool:
    # `execution_context.operation_type` is Strawberry's OperationType enum,
    # which is NOT identity-equal to graphql-core's. Compare by member name
    # so we don't depend on which enum class produced the value.
    return getattr(op_type, "name", "").upper() == "MUTATION"


class InteractionTrackingExtension(SchemaExtension):
    def on_operation(self):  # type: ignore[override]
        # Let the operation execute first, then inspect the result.
        yield
        try:
            ec = self.execution_context
            if not _is_mutation(getattr(ec, "operation_type", None)):
                return
            # Don't count mutations that errored out.
            result = getattr(ec, "result", None)
            if result is not None and getattr(result, "errors", None):
                return
            ctx = getattr(ec, "context", None)
            request = getattr(ctx, "request", None)
            user_id = getattr(ctx, "user_id", None) or getattr(
                request, "user_id", None
            )
            if not user_id or request is None:
                return
            record_interaction(user_id, source_from_request(request))
        except Exception:  # noqa: BLE001 — metrics must not break a request
            logger.exception("InteractionTrackingExtension failed")

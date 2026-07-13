"""Public GraphQL endpoint for the marketing site.

A separate Strawberry schema and view because the main `/graphql/`
requires Supabase auth on every request. Visitors to continuu.it
reading a blog post don't have a session.
"""

from __future__ import annotations

import strawberry

from core.auth import _SanitizingGraphQLView

from .schema_public import CmsPublicQuery


public_schema = strawberry.Schema(query=CmsPublicQuery)


class PublicGraphQLView(_SanitizingGraphQLView):
    """GraphQL view with no auth check. Schema is reads-only.

    Inherits transient-DB-error scrubbing so the marketing site never receives
    raw psycopg internals on a stale-connection hiccup (see core/auth.py)."""

    pass

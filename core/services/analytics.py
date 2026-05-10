"""Re-export analytics computation under the services namespace.

The heavy lifting lives in `core.analytics` to keep import cycles tame
(the GraphQL layer has used that module since before the services layer
existed). This module is the public face for assistant tools.
"""

from __future__ import annotations

from ..analytics import AnalyticsRange, AnalyticsResult, compute_analytics

__all__ = ["AnalyticsRange", "AnalyticsResult", "compute_analytics"]

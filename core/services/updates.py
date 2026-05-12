"""Removed — replaced by `core.services.activities`.

User-authored notes are now `Activity` rows with `kind=NOTE`. The old
`Update` model and this service were deleted in migration 0009.
"""

raise ImportError(
    "core.services.updates was removed. Use core.services.activities "
    "(add_note / update_note / delete_note / list_activity)."
)

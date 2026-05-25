"""In-app banners shown at the top of the dashboard.

Two sources of notifications:

1. **Derived** — computed from user state (quota overages, etc.). Not
   stored, recomputed on every fetch.
2. **Announcements** — admin-managed CRUD: maintenance windows, product
   news, targeted messages. Stored in the `Announcement` table.

The public `notifications` GraphQL query merges both and returns a
priority-sorted list to the frontend's NotificationStack.

NOT to be confused with `core.notifications` — that package handles
out-of-app channels (Telegram, WhatsApp, email digests). This one is
strictly in-app banners.
"""

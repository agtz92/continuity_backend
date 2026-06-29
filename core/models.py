import uuid
from django.db import models
from django.db.models import Q


class ProjectStatus(models.TextChoices):
    IDEA = "idea", "Idea"
    ACTIVE = "active", "Active"
    STALLED = "stalled", "Stalled"
    PAUSED = "paused", "Paused"
    LAUNCHED = "launched", "Launched"
    KILLED = "killed", "Killed"
    ARCHIVED = "archived", "Archived"


class Priority(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(db_index=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class AppConfig(models.Model):
    """Global key/value config, typed via JSON. Powers the beta lifecycle
    knobs (enrollment_open, spot_cap, thresholds, dry_run, significant event
    kinds). Read through `core.services.app_config` (cached). NOT user-scoped.
    """

    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover - admin/debug convenience
        return f"{self.key}={self.value!r}"


class Category(TimestampedModel):
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, default="emerald")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "name"], name="unique_category_per_user"
            )
        ]


class Project(TimestampedModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    why = models.TextField(blank=True, default="")
    next_step = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=ProjectStatus.choices, default=ProjectStatus.IDEA
    )
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.MEDIUM
    )
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="projects",
    )
    last_activity = models.DateTimeField(auto_now_add=True)
    promoted_from_idea_at = models.DateTimeField(null=True, blank=True, db_index=True)
    due_date = models.DateTimeField(null=True, blank=True)

    # Closure notes — paused (see docs/_archive/state-closure/STATE_CLOSURE_FINAL.md §3). Text uses
    # default="" (never null) per the codebase convention; "never paused" is
    # expressed by paused_at IS NULL, not by empty text.
    paused_context = models.CharField(max_length=200, blank=True, default="")
    paused_next_action = models.CharField(max_length=200, blank=True, default="")
    paused_blocker = models.CharField(max_length=300, blank=True, default="")
    paused_at = models.DateTimeField(null=True, blank=True)

    # Closure notes — killed
    killed_reason = models.CharField(max_length=300, blank=True, default="")
    killed_learnings = models.CharField(max_length=300, blank=True, default="")
    killed_would_restart = models.CharField(max_length=200, blank=True, default="")
    killed_at = models.DateTimeField(null=True, blank=True)
    # Loop autopsy, Capa A: one-time reflection written when the project dies.
    killed_ai_reflection = models.TextField(blank=True, default="")

    # Stalled auto-detection (cron, 14 days; only active projects).
    stalled_at = models.DateTimeField(null=True, blank=True)

    # Manual ordering ("Mi orden" sort mode). 0 by default; the frontend's
    # reorder action assigns dense 0..N positions. Not used by Meta.ordering —
    # the clients sort client-side and only read `position` for the manual mode.
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-last_activity"]
        indexes = [
            models.Index(
                fields=["user_id", "status", "last_activity"],
                name="idx_project_status_activity",
            ),
            models.Index(
                fields=["status", "last_activity"],
                name="idx_project_stalled_sweep",
            ),
        ]


class Task(TimestampedModel):
    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks"
    )
    title = models.CharField(max_length=500)
    due_date = models.DateTimeField(null=True, blank=True)
    done = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    effort_hours = models.FloatField(null=True, blank=True)
    google_task_id = models.CharField(
        max_length=128, null=True, blank=True, db_index=True
    )
    # Calendar integration. Tasks have no time by default; when due_time is NULL
    # the task maps to an all-day calendar event on due_date. duration_minutes
    # only applies when due_time is set (start → start+duration). calendar_event_id
    # is the external event id (Google Calendar) for idempotent push/update.
    due_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    calendar_event_id = models.CharField(max_length=256, blank=True, default="")
    # State-closure parking: when a task's project is paused/killed/archived its
    # due date is snapshotted here and due_date/due_time are cleared, so the task
    # stops surfacing in daily views (Today / Tasks). On revive the UI offers to
    # restore from these columns (suggest, not auto). Cleared once the task is
    # rescheduled (a real due_date supersedes the snapshot) or the suggestion is
    # dismissed. See core/services/tasks.py park/restore helpers.
    parked_due_date = models.DateTimeField(null=True, blank=True)
    parked_due_time = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["done", "due_date", "-created"]
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "google_task_id"],
                condition=Q(google_task_id__isnull=False),
                name="uniq_user_google_task",
            ),
        ]


class Idea(TimestampedModel):
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")
    why = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created"]


class ProjectNote(TimestampedModel):
    """One of many free-form notes attached to a project. Distinct from
    `Update` (timeline of activity) and `Project.description/why/next_step`
    (single-value context fields). Title is optional — if blank, the UI
    derives a preview from the first line of the body."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="note_items"
    )
    title = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class QuickNote(TimestampedModel):
    """A notebook-style note. Unlike `Idea` (flat capture) or `ProjectNote`
    (sub-notes locked inside one project), a QuickNote is a top-level note that
    holds a list of collapsible `NoteSection` blocks (Notion-style toggles). It
    can be tagged with a `Category` and optionally linked to a `Project`, or
    live standalone. Both FKs are SET_NULL so deleting a category/project never
    deletes the note."""

    title = models.CharField(max_length=255, blank=True, default="")
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quick_notes",
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quick_notes",
    )
    pinned = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pinned", "-updated_at"]
        indexes = [
            models.Index(fields=["user_id", "-updated_at"]),
            models.Index(fields=["user_id", "category"]),
            models.Index(fields=["user_id", "project"]),
        ]


class NoteSection(TimestampedModel):
    """A collapsible block (toggle) inside a QuickNote. Body is free-form
    markdown. Ordered by `position`; `collapsed` is the default open/closed
    state the UI restores on load."""

    note = models.ForeignKey(
        QuickNote, on_delete=models.CASCADE, related_name="sections"
    )
    heading = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField(blank=True, default="")
    position = models.PositiveIntegerField(default=0)
    collapsed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "created"]
        indexes = [models.Index(fields=["note", "position"])]


class BackupMeta(models.Model):
    user_id = models.UUIDField(primary_key=True)
    last_backup = models.DateTimeField(null=True, blank=True)


class GraveyardInsight(models.Model):
    """Per-user cached cross-project autopsy of killed projects (Loop, Capa B).

    Recomputed only when a project dies (threshold: 3 kills) — reading it never
    calls the model. `is_stale` is set on revive so the next death recomputes.
    Singleton per user, same shape as BackupMeta/Profile."""

    user_id = models.UUIDField(primary_key=True)
    body = models.TextField(blank=True, default="")
    deaths_count = models.PositiveIntegerField(default=0)
    computed_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class StalledSweepState(models.Model):
    """Singleton (pk=1) recording when stalled auto-detection went live for this
    deployment. The cron stalls nothing until STALLED_THRESHOLD_DAYS after
    `cutoff_at`, so the first run on an existing database never avalanches old
    projects into 'stalled'. `cutoff_at` is set automatically on the first run —
    no env var or ops step needed (docs/_archive/state-closure/STATE_CLOSURE_FINAL.md §0.1, cutoff option)."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    cutoff_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class Profile(models.Model):
    user_id = models.UUIDField(primary_key=True)
    avatar = models.CharField(max_length=64, blank=True, default="")
    first_name = models.CharField(max_length=50, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)


class OnboardingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    SKIPPED = "skipped", "Skipped"


class OnboardingCompletionMode(models.TextChoices):
    FINISHED = "finished", "Finished"
    SKIPPED = "skipped", "Skipped"


class TourStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SEEN = "seen", "Seen"
    SKIPPED = "skipped", "Skipped"


class OnboardingProgress(models.Model):
    """Per-user onboarding state. Decoupled from AccountProfile (which is
    plan/billing-focused). Lazy-created on first read; the absence of a row
    means the user has not started onboarding yet.
    """

    user_id = models.UUIDField(primary_key=True)
    status = models.CharField(
        max_length=16,
        choices=OnboardingStatus.choices,
        default=OnboardingStatus.PENDING,
    )
    current_step = models.PositiveSmallIntegerField(default=1)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_via = models.CharField(
        max_length=8,
        choices=OnboardingCompletionMode.choices,
        blank=True,
        default="",
    )
    tour_status = models.CharField(
        max_length=16,
        choices=TourStatus.choices,
        default=TourStatus.PENDING,
    )
    tour_completed_at = models.DateTimeField(null=True, blank=True)
    # When the one-time example content (project/tasks/routine/idea) was seeded
    # for this user. NULL means "not yet decided". Set the moment we seed OR
    # the moment we decide not to (e.g. the user already has projects), so the
    # decision is made exactly once and deleting the examples never re-seeds.
    example_seeded_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UserPreferences(models.Model):
    """Per-user UI preferences. Lazy-created on first read; the absence of a
    row means the user has never customized anything and defaults apply.

    Today layout shape:
        {"hidden": ["done-today", ...], "order": ["today-focus", ...]}

    Stored as JSON so adding new sections doesn't require a migration —
    unknown ids are silently ignored on read, defaults fill the gap.
    """

    user_id = models.UUIDField(primary_key=True)
    today_layout = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class GoogleOAuthCredential(models.Model):
    user_id = models.UUIDField(primary_key=True)
    refresh_token = models.TextField()
    access_token = models.TextField(blank=True, default="")
    token_expiry = models.DateTimeField(null=True, blank=True)
    scopes = models.TextField(blank=True, default="")
    email = models.CharField(max_length=320, blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ICloudCalendarCredential(models.Model):
    """iCloud CalDAV credentials for the optional native-write integration.

    Apple has no calendar OAuth, so the user supplies their Apple ID + an
    app-specific password (generated at appleid.apple.com). The password is
    stored Fernet-encrypted (same scheme as GoogleOAuthCredential tokens).
    ``calendar_url`` is the chosen CalDAV calendar href to write into.
    """

    user_id = models.UUIDField(primary_key=True)
    apple_id = models.CharField(max_length=320, blank=True, default="")
    app_password = models.TextField()  # Fernet-encrypted
    calendar_url = models.CharField(max_length=500, blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ActivityKind(models.TextChoices):
    NOTE = "note", "Note"
    PROJECT_CREATED = "project_created", "Project created"
    PROJECT_DELETED = "project_deleted", "Project deleted"
    PROJECT_STATUS_CHANGED = "project_status_changed", "Project status changed"
    PROJECT_DUE_DATE_CHANGED = "project_due_date_changed", "Project due date changed"
    TASK_CREATED = "task_created", "Task created"
    TASK_COMPLETED = "task_completed", "Task completed"
    TASK_DELETED = "task_deleted", "Task deleted"
    TASK_DUE_DATE_CHANGED = "task_due_date_changed", "Task due date changed"
    IDEA_CREATED = "idea_created", "Idea created"
    IDEA_DELETED = "idea_deleted", "Idea deleted"
    IDEA_PROMOTED = "idea_promoted", "Idea promoted"
    ROUTINE_CREATED = "routine_created", "Routine created"
    ROUTINE_COMPLETED = "routine_completed", "Routine completed"
    ROUTINE_DELETED = "routine_deleted", "Routine deleted"
    QUICK_NOTE_CREATED = "quick_note_created", "Quick note created"
    QUICK_NOTE_DELETED = "quick_note_deleted", "Quick note deleted"


class RecurrenceType(models.TextChoices):
    ONCE = "once", "Once"
    WEEKLY_DAYS = "weekly_days", "Weekly days"
    EVERY_N = "every_n", "Every N"
    MONTHLY_DAY = "monthly_day", "Monthly day"


class IntervalUnit(models.TextChoices):
    DAYS = "days", "Days"
    WEEKS = "weeks", "Weeks"
    MONTHS = "months", "Months"


class Routine(TimestampedModel):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    recurrence_type = models.CharField(
        max_length=20, choices=RecurrenceType.choices
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    weekdays = models.JSONField(default=list, blank=True)
    interval_n = models.PositiveIntegerField(null=True, blank=True)
    interval_unit = models.CharField(
        max_length=10, choices=IntervalUnit.choices, blank=True, default=""
    )
    monthly_day = models.PositiveSmallIntegerField(null=True, blank=True)
    effort_hours = models.FloatField(null=True, blank=True)
    archived = models.BooleanField(default=False)
    # Calendar integration. NULL time_of_day → all-day recurring event; the
    # recurrence maps to a calendar RRULE. duration_minutes only applies when a
    # time is set. calendar_event_id is the external recurring-event id.
    time_of_day = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    calendar_event_id = models.CharField(max_length=256, blank=True, default="")
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="routines",
    )

    class Meta:
        ordering = ["archived", "-created"]
        indexes = [models.Index(fields=["user_id", "archived"])]


class TaskBlocker(TimestampedModel):
    """A blocker on a task. Exactly one of blocking_task or external_description
    is non-null — enforced at the service layer."""

    blocked_task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="blockers",
    )
    blocking_task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="blocking",
    )
    external_description = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["created"]


class RoutineOccurrence(TimestampedModel):
    routine = models.ForeignKey(
        Routine, on_delete=models.CASCADE, related_name="occurrences"
    )
    scheduled_date = models.DateField()
    completed_at = models.DateTimeField()
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-scheduled_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["routine", "scheduled_date"],
                name="unique_routine_occurrence_per_day",
            )
        ]
        indexes = [models.Index(fields=["user_id", "-scheduled_date"])]


class Activity(TimestampedModel):
    kind = models.CharField(
        max_length=32, choices=ActivityKind.choices, db_index=True
    )
    entity_id = models.UUIDField(null=True, blank=True)
    entity_title = models.CharField(max_length=500, blank=True, default="")
    project_id = models.UUIDField(null=True, blank=True)
    target_project_id = models.UUIDField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    previous_value = models.TextField(blank=True, default="")
    new_value = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["user_id", "-created"]),
            models.Index(fields=["user_id", "kind"]),
            models.Index(fields=["user_id", "project_id"]),
        ]


class InteractionSource(models.TextChoices):
    WEB = "web", "Web app"
    MOBILE = "mobile", "Mobile app"
    CONNECTOR = "connector", "Claude connector"
    UNKNOWN = "unknown", "Unknown"


class InteractionDay(models.Model):
    """Append-only per-user, per-source daily interaction counter.

    Privacy by design: stores ONLY counts — never message content, query
    text, IPs, user-agents or any payload. One "interaction" = one action
    with effect (a GraphQL mutation, an assistant message, or a connector
    tool call), bucketed by the channel it came from. Powers the admin
    usage metrics; safe to surface because it reveals volume, not content.
    """

    user_id = models.UUIDField()
    date = models.DateField()
    source = models.CharField(
        max_length=16,
        choices=InteractionSource.choices,
        default=InteractionSource.UNKNOWN,
    )
    count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "date", "source"],
                name="unique_interaction_per_user_day_source",
            )
        ]
        indexes = [
            models.Index(fields=["user_id", "-date"]),
            models.Index(fields=["date", "source"]),
        ]


# ---------------------------------------------------------------------------
# MCP connector OAuth 2.1 (see docs/mcp-connector/PLAN.md §4.2 / Fase 1)
#
# A minimal OAuth authorization server so Claude.ai can connect to /mcp/ as a
# remote connector. Public clients only (PKCE, no client secret). Codes and
# refresh tokens are stored **hashed** (sha256) so a DB leak can't replay them.
# Access tokens are stateless JWTs (not stored) — short-lived; revocation works
# by revoking the refresh token.
# ---------------------------------------------------------------------------


class OAuthClient(models.Model):
    """A dynamically-registered (RFC 7591) MCP client, e.g. Claude."""

    client_id = models.CharField(max_length=64, primary_key=True)
    client_name = models.CharField(max_length=255, blank=True, default="")
    redirect_uris = models.JSONField(default=list)
    token_endpoint_auth_method = models.CharField(max_length=32, default="none")
    created = models.DateTimeField(auto_now_add=True)


class OAuthAuthorizationCode(models.Model):
    """Short-lived authorization code, bound to a user + client + PKCE challenge."""

    code_hash = models.CharField(max_length=64, unique=True, db_index=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE)
    user_id = models.UUIDField()
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=255)
    code_challenge_method = models.CharField(max_length=12, default="S256")
    scope = models.CharField(max_length=255, blank=True, default="")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)


class OAuthRefreshToken(models.Model):
    """Long-lived refresh token (hashed). Revocable for the 'active connections' UI."""

    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE)
    user_id = models.UUIDField(db_index=True)
    scope = models.CharField(max_length=255, blank=True, default="")
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user_id", "client"])]


class OAuthConnectionEvent(models.Model):
    """Append-only audit trail of MCP connector lifecycle events.

    Security/incident-response log: who authorized which client, when tokens
    were refreshed, and when a connection was revoked (by the user or an admin).
    Counts only the event + client + timestamp — no payloads.
    """

    class Event(models.TextChoices):
        AUTHORIZED = "authorized", "Authorized"
        TOKEN_REFRESHED = "token_refreshed", "Token refreshed"
        REVOKED = "revoked", "Revoked by user"
        ADMIN_REVOKED = "admin_revoked", "Revoked by admin"

    user_id = models.UUIDField(db_index=True)
    client_id = models.CharField(max_length=64)
    client_name = models.CharField(max_length=255, blank=True, default="")
    event = models.CharField(max_length=32, choices=Event.choices)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["user_id", "-created"]),
            models.Index(fields=["-created"]),
        ]

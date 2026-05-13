import uuid
from django.db import models


class ProjectStatus(models.TextChoices):
    IDEA = "idea", "Idea"
    ACTIVE = "active", "Active"
    STALLED = "stalled", "Stalled"
    PAUSED = "paused", "Paused"
    LAUNCHED = "launched", "Launched"
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

    class Meta:
        ordering = ["-last_activity"]


class Task(TimestampedModel):
    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks"
    )
    title = models.CharField(max_length=500)
    due_date = models.DateTimeField(null=True, blank=True)
    done = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    effort_hours = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["done", "due_date", "-created"]


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


class BackupMeta(models.Model):
    user_id = models.UUIDField(primary_key=True)
    last_backup = models.DateTimeField(null=True, blank=True)


class Profile(models.Model):
    user_id = models.UUIDField(primary_key=True)
    avatar = models.CharField(max_length=64, blank=True, default="")
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

    class Meta:
        ordering = ["archived", "-created"]
        indexes = [models.Index(fields=["user_id", "archived"])]


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

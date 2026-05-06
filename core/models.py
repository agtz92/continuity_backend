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

    class Meta:
        ordering = ["done", "due_date", "-created"]


class Idea(TimestampedModel):
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")
    why = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created"]


class Update(TimestampedModel):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="updates"
    )
    note = models.TextField()
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]


class BackupMeta(models.Model):
    user_id = models.UUIDField(primary_key=True)
    last_backup = models.DateTimeField(null=True, blank=True)

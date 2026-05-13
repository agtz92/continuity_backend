"""Data model for the AI assistant.

Four models:

- AccountProfile — billing/quota gate. One per user, lazy-created on first
  chat. The `plan` column is the single source of truth for paid features;
  `context_version` busts the skinny-context cache when the user's data
  changes.
- Conversation — a chat thread. One user has many.
- Message — one turn within a conversation. `content` stores the Anthropic
  content-block array verbatim so history replays exactly.
- UsageDay — append-only daily counters powering the usage meter.
"""

from __future__ import annotations

import uuid

from django.db import models


class Plan(models.TextChoices):
    FREE = "free", "Free"
    PRO = "pro", "Pro"
    ADMIN = "admin", "Admin"


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"
    TOOL = "tool", "Tool"


class AccountProfile(models.Model):
    """Per-user billing / quota / cache-version row.

    Despite the name, this is *not* an auth user — Supabase owns those.
    Lazy-created the first time a user touches the assistant.
    """

    user_id = models.UUIDField(primary_key=True)
    plan = models.CharField(
        max_length=16, choices=Plan.choices, default=Plan.FREE
    )
    plan_renews_at = models.DateTimeField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=255, blank=True, default="")
    is_admin = models.BooleanField(default=False, db_index=True)
    context_version = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(db_index=True)
    title = models.CharField(max_length=255, blank=True, default="")
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user_id", "-updated_at"]),
        ]


class Message(models.Model):
    """One assistant/user/tool turn.

    `content` is the raw Anthropic content-block array (a JSON list of
    text/tool_use/tool_result dicts). Storing the wire format means
    history replays without any lossy reconstruction.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=16, choices=MessageRole.choices)
    content = models.JSONField()
    model = models.CharField(max_length=64, blank=True, default="")
    stop_reason = models.CharField(max_length=32, blank=True, default="")
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cache_read_in = models.IntegerField(default=0)
    cache_creation_in = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]
        indexes = [
            models.Index(fields=["conversation", "created"]),
        ]


class UsageDay(models.Model):
    """Append-only per-user daily counters."""

    user_id = models.UUIDField()
    date = models.DateField()
    messages_sent = models.IntegerField(default=0)
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cache_read_in = models.IntegerField(default=0)
    cost_usd_cents = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "date"], name="unique_usage_per_user_per_day"
            )
        ]
        indexes = [
            models.Index(fields=["user_id", "-date"]),
        ]

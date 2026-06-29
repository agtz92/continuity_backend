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
    STUDIO = "studio", "Studio"
    ADMIN = "admin", "Admin"


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"
    TOOL = "tool", "Tool"


class BetaStatus(models.TextChoices):
    """Lifecycle state of a beta-cohort member. Empty ("") for non-beta users.

    Independent of billing: `manually_paused` / `manually_killed` are admin
    actions that never touch `is_billing_exempt`; only the automatic reclaim
    flips exemption off. See docs/_archive/beta-lifecycle/PROPOSAL.md.
    """

    ACTIVE = "active", "Active"
    RECLAIMED = "reclaimed", "Reclaimed"
    MANUALLY_PAUSED = "manually_paused", "Manually paused"
    MANUALLY_KILLED = "manually_killed", "Manually killed"


class BillingExemptReason(models.TextChoices):
    """Why an account is billing-exempt. Decoupled from beta cohort — a user
    can be exempt as a friend/investor/partner without occupying a beta spot."""

    BETA = "beta", "Beta"
    FRIEND = "friend", "Friend"
    INVESTOR = "investor", "Investor"
    PARTNER = "partner", "Partner"
    MANUAL = "manual", "Manual"


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
    # Active price id within the current subscription. Lets us derive the
    # billing period (monthly/annual) and the plan without round-tripping
    # to Stripe on every settings/billing page load.
    stripe_price_id = models.CharField(max_length=255, blank=True, default="")
    # True when the user clicked "Downgrade to Free" — Stripe keeps the
    # subscription active until `plan_renews_at`, then auto-deletes it. We
    # mirror this so the UI can show "scheduled to cancel on X" + a
    # reactivate button without round-tripping to Stripe.
    cancel_at_period_end = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False, db_index=True)
    is_billing_exempt = models.BooleanField(default=False, db_index=True)
    # --- Billing exemption metadata (independent of beta cohort) ---
    billing_exempt_reason = models.CharField(
        max_length=16, choices=BillingExemptReason.choices, blank=True, default=""
    )
    # NULL = indefinite.
    billing_exempt_until = models.DateTimeField(null=True, blank=True)
    # --- Beta cohort (occupies a spot, owes feedback, lifetime deal) ---
    # Independent of is_billing_exempt: a beta member is exempt with
    # reason="beta", but exemption can also be granted for other reasons.
    beta_cohort = models.BooleanField(default=False, db_index=True)
    # "" for non-beta; "active" the moment beta_cohort flips true.
    beta_status = models.CharField(
        max_length=16, choices=BetaStatus.choices, blank=True, default="", db_index=True
    )
    beta_enrolled_at = models.DateTimeField(null=True, blank=True)
    # Set when the reclaim warning email is sent; cleared when the user becomes
    # active again. Reclaim only fires once this is >= grace days old.
    reclaim_warned_at = models.DateTimeField(null=True, blank=True)
    # True once a retention coupon has been offered+applied to this user.
    # Prevents repeat coupon abuse: if the user tries to cancel again later,
    # the offer step is skipped.
    had_retention_offer = models.BooleanField(default=False)
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
    # Count of messages that actually used the deep model (Sonnet). Drives
    # the per-day Sonnet cap — see core.assistant.quotas.deep_allowed.
    deep_messages = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "date"], name="unique_usage_per_user_per_day"
            )
        ]
        indexes = [
            models.Index(fields=["user_id", "-date"]),
        ]

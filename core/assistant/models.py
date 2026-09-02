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


class BillingSource(models.TextChoices):
    """Who issued the user's current paid entitlement.

    Empty means "nobody is charging for this plan" — free users, and also
    billing-exempt users, whose plan comes from `is_billing_exempt`.

    This column is what makes several payment channels safe: every writer
    goes through `core.billing.entitlements.apply_entitlement`, which refuses
    to let one source overwrite another source's live entitlement. See
    `docs/integracion-pagos-web-y-movil.md`.
    """

    #: RevenueCat Web Billing. Stripe is still the card processor underneath,
    #: but it is no longer the *biller* — the subscription, the plan changes
    #: and the customer portal all live in RevenueCat.
    WEB = "web", "Web (RevenueCat Web Billing)"
    APPLE = "apple", "App Store"
    GOOGLE = "google", "Google Play"


#: Sold by an app store. The user cancels or switches plan in the store's own
#: UI, and we deep-link them there.
STORE_SOURCES = frozenset({BillingSource.APPLE.value, BillingSource.GOOGLE.value})

#: Every source whose subscription is managed outside our own UI. Since the
#: web moved to RevenueCat's customer portal, that is all of them — we no
#: longer own a checkout or a cancel button for anyone. This is the set to
#: check before offering to sell, change or cancel a plan.
EXTERNALLY_MANAGED_SOURCES = STORE_SOURCES | frozenset({BillingSource.WEB.value})


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
    # Which channel sold the current paid plan. "" for free/exempt users.
    # Guards against a stale event from one source clobbering another's
    # entitlement — see core/billing/entitlements.py.
    billing_source = models.CharField(
        max_length=16, choices=BillingSource.choices, blank=True, default="",
        db_index=True,
    )
    # --- Current subscription, whoever sold it ---
    # One set of columns for all three channels. They used to be prefixed
    # `stripe_` (when Stripe was the only biller) plus a parallel `store_` set
    # for the app stores; that split made every reader branch on the source to
    # ask the same question twice. `billing_source` above says who, these say
    # what. See `docs/pagos-unificados/PLAN.md`.
    #
    #: Customer identifier in the issuer's system.
    billing_customer_id = models.CharField(max_length=255, blank=True, default="")
    #: Stable per-subscription id. RevenueCat/stores: original transaction id
    #: or purchase token. Indexed because store webhooks arrive keyed by it —
    #: they carry no notion of our user_id beyond what we sent at purchase.
    billing_transaction_id = models.CharField(
        max_length=255, blank=True, default="", db_index=True
    )
    #: Product/price identifier of the active plan. Encodes plan + period, so
    #: we can answer "Pro, annual" without round-tripping to the issuer on
    #: every billing page load.
    billing_product_id = models.CharField(max_length=255, blank=True, default="")
    # True when auto-renew was switched off. Access continues until
    # `plan_renews_at`; the issuer ends it then. We mirror it so the UI can
    # show "scheduled to cancel on X" without asking the issuer every time.
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

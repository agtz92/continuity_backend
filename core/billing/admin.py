"""Read-only view of what the stores actually sent us.

`StoreWebhookEvent`'s whole reason to exist is answering "I paid and the app
says Free" — but until now there was no way to look at it short of running SQL
against production, which is exactly when nobody wants to be writing SQL.

Deliberately read-only: these rows are the record of what a third party told
us. Editing one would destroy the only copy of the evidence, and `outcome` is
the webhook's decision, not something to fix by hand.
"""

from django.contrib import admin

from .models import StoreWebhookEvent


@admin.register(StoreWebhookEvent)
class StoreWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "received_at",
        "event_type",
        "source",
        "outcome",
        "product_id",
        "app_user_id",
    )
    # `outcome` first: it is the answer to "did this grant anything?".
    # "unusable" means we dropped the event — an unmapped store or a product
    # id that isn't in STORE_PRODUCT_*. "sandbox_ignored" means it was a test
    # purchase on a production deployment.
    list_filter = ("outcome", "source", "event_type")
    search_fields = ("event_id", "app_user_id", "product_id")
    date_hierarchy = "received_at"
    readonly_fields = (
        "event_id",
        "event_type",
        "source",
        "app_user_id",
        "product_id",
        "outcome",
        "payload",
        "received_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

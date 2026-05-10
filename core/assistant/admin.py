from django.contrib import admin

from .models import AccountProfile, Conversation, Message, UsageDay


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
    list_display = ("user_id", "plan", "plan_renews_at", "context_version", "updated_at")
    list_filter = ("plan",)
    search_fields = ("user_id", "stripe_customer_id")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "user_id", "title", "archived", "updated_at")
    list_filter = ("archived",)
    search_fields = ("id", "user_id", "title")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "model", "tokens_in", "tokens_out", "created")
    list_filter = ("role", "model")
    search_fields = ("id", "conversation__id")


@admin.register(UsageDay)
class UsageDayAdmin(admin.ModelAdmin):
    list_display = ("user_id", "date", "messages_sent", "tokens_in", "tokens_out", "cache_read_in")
    list_filter = ("date",)
    search_fields = ("user_id",)

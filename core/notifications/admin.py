from django.contrib import admin
from .models import NotificationSettings, Notification


@admin.register(NotificationSettings)
class NotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ("user_id", "timezone", "digest_enabled", "updated_at")
    list_filter = ("digest_enabled",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user_id", "channel", "kind", "status", "created", "sent_at")
    list_filter = ("status", "channel", "kind")
    search_fields = ("user_id", "dedupe_key")
    readonly_fields = ("created", "sent_at")

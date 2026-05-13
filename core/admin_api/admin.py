from django.contrib import admin

from .models import AdminAuditLog


@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created", "actor_user_id", "action", "target_type", "target_id")
    list_filter = ("action", "target_type")
    search_fields = ("actor_user_id", "target_id", "action")
    readonly_fields = (
        "id",
        "actor_user_id",
        "action",
        "target_type",
        "target_id",
        "payload",
        "created",
    )

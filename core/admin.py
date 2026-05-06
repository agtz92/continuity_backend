from django.contrib import admin
from .models import Project, Task, Idea, Update, BackupMeta


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "user_id", "last_activity")
    list_filter = ("status",)
    search_fields = ("name", "description")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "done", "due_date", "user_id")
    list_filter = ("done",)


@admin.register(Idea)
class IdeaAdmin(admin.ModelAdmin):
    list_display = ("title", "user_id", "created")


@admin.register(Update)
class UpdateAdmin(admin.ModelAdmin):
    list_display = ("project", "note", "date")


admin.site.register(BackupMeta)

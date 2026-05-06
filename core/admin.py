from django.contrib import admin
from .models import Project, Task, Idea, Update, BackupMeta, Category


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "priority", "category", "user_id", "last_activity")
    list_filter = ("status", "priority")
    search_fields = ("name", "description")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "user_id")


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

from django.contrib import admin
from .models import Activity, BackupMeta, Category, Idea, Project, ProjectNote, Task


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


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("kind", "entity_title", "project_id", "user_id", "created")
    list_filter = ("kind",)
    search_fields = ("entity_title", "note")
    readonly_fields = (
        "id", "user_id", "kind", "entity_id", "entity_title",
        "project_id", "target_project_id", "note",
        "previous_value", "new_value", "created",
    )


@admin.register(ProjectNote)
class ProjectNoteAdmin(admin.ModelAdmin):
    list_display = ("project", "title", "user_id", "updated_at")
    search_fields = ("title", "body")


admin.site.register(BackupMeta)

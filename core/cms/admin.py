from django.contrib import admin

from .models import BlogPost, MediaAsset, Page


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "status", "locale", "published_at", "updated_at")
    list_filter = ("status", "locale")
    search_fields = ("title", "slug", "tags")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "path", "status", "show_in_nav", "nav_order", "updated_at")
    list_filter = ("status", "show_in_nav", "locale")
    search_fields = ("title", "path")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "mime_type", "size_bytes", "uploaded_by_user_id", "created_at")
    search_fields = ("original_filename", "storage_path")
    readonly_fields = (
        "id",
        "storage_path",
        "public_url",
        "original_filename",
        "mime_type",
        "size_bytes",
        "width",
        "height",
        "uploaded_by_user_id",
        "created_at",
    )

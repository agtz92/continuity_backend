"""Content models served at continuu.it/blog and continuu.it/<slug>.

- BlogPost: a dated entry under /blog/<slug>.
- Page: a standalone page mounted at an explicit path (/about, /pricing).
- MediaAsset: uploaded image (or other file) referenced by content.

Content is stored as Tiptap JSON (`content_json`) — the source of truth
the editor reads back into the document. `content_html` is precomputed
at save time so the public site can SSR without rebuilding the doc on
every request. Only DRAFT/PUBLISHED/ARCHIVED states are surfaced; the
public schema filters to PUBLISHED.
"""

from __future__ import annotations

import uuid

from django.db import models


class PostStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class BlogPost(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=160, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    excerpt = models.TextField(blank=True, default="")
    content_json = models.JSONField(default=dict, blank=True)
    content_html = models.TextField(blank=True, default="")
    cover_image_url = models.URLField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=PostStatus.choices,
        default=PostStatus.DRAFT,
        db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    author_user_id = models.UUIDField()
    tags = models.JSONField(default=list, blank=True)
    seo_title = models.CharField(max_length=255, blank=True, default="")
    seo_description = models.CharField(max_length=320, blank=True, default="")
    locale = models.CharField(max_length=8, default="es", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-updated_at"]
        indexes = [
            models.Index(fields=["status", "locale", "-published_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - admin display
        return f"{self.title} ({self.slug})"


class Page(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    path = models.CharField(max_length=160, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    excerpt = models.TextField(blank=True, default="")
    content_json = models.JSONField(default=dict, blank=True)
    content_html = models.TextField(blank=True, default="")
    cover_image_url = models.URLField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=PostStatus.choices,
        default=PostStatus.DRAFT,
        db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    author_user_id = models.UUIDField()
    show_in_nav = models.BooleanField(default=False)
    nav_order = models.IntegerField(default=0)
    seo_title = models.CharField(max_length=255, blank=True, default="")
    seo_description = models.CharField(max_length=320, blank=True, default="")
    locale = models.CharField(max_length=8, default="es", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nav_order", "title"]

    def __str__(self) -> str:  # pragma: no cover - admin display
        return f"{self.title} ({self.path})"


class MediaAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    storage_path = models.CharField(max_length=512, unique=True)
    public_url = models.URLField()
    original_filename = models.CharField(max_length=255, blank=True, default="")
    mime_type = models.CharField(max_length=128, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    uploaded_by_user_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - admin display
        return f"{self.original_filename or self.storage_path}"

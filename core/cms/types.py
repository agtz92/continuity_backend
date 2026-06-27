"""Tipos e inputs GraphQL del CMS admin.

Extraídos de cms/schema_admin.py (ver AUDITORIA_CODIGO.md). Solo definiciones;
sin resolvers ni servicios. schema_admin.py los re-importa con `import *`.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import strawberry

from .models import BlogPost, HelpCategory, HelpResource, MediaAsset, Page  # noqa: F401

@strawberry.type
class AdminBlogPost:
    id: strawberry.ID
    slug: str
    title: str
    excerpt: str
    content_json: strawberry.scalars.JSON
    content_html: str
    cover_image_url: str
    status: str
    published_at: Optional[dt.datetime]
    author_user_id: strawberry.ID
    tags: list[str]
    seo_title: str
    seo_description: str
    locale: str
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, m: BlogPost) -> "AdminBlogPost":
        return cls(
            id=strawberry.ID(str(m.id)),
            slug=m.slug,
            title=m.title,
            excerpt=m.excerpt,
            content_json=m.content_json or {},
            content_html=m.content_html,
            cover_image_url=m.cover_image_url,
            status=m.status,
            published_at=m.published_at,
            author_user_id=strawberry.ID(str(m.author_user_id)),
            tags=list(m.tags or []),
            seo_title=m.seo_title,
            seo_description=m.seo_description,
            locale=m.locale,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )


@strawberry.type
class AdminBlogPostPage:
    posts: list[AdminBlogPost]
    page: int
    per_page: int
    has_next: bool


@strawberry.type
class AdminPage:
    id: strawberry.ID
    path: str
    title: str
    excerpt: str
    content_json: strawberry.scalars.JSON
    content_html: str
    cover_image_url: str
    status: str
    published_at: Optional[dt.datetime]
    show_in_nav: bool
    nav_order: int
    seo_title: str
    seo_description: str
    locale: str
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, m: Page) -> "AdminPage":
        return cls(
            id=strawberry.ID(str(m.id)),
            path=m.path,
            title=m.title,
            excerpt=m.excerpt,
            content_json=m.content_json or {},
            content_html=m.content_html,
            cover_image_url=m.cover_image_url,
            status=m.status,
            published_at=m.published_at,
            show_in_nav=m.show_in_nav,
            nav_order=m.nav_order,
            seo_title=m.seo_title,
            seo_description=m.seo_description,
            locale=m.locale,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )


@strawberry.type
class AdminMediaAsset:
    id: strawberry.ID
    storage_path: str
    public_url: str
    original_filename: str
    mime_type: str
    size_bytes: int
    width: Optional[int]
    height: Optional[int]
    uploaded_by_user_id: strawberry.ID
    created_at: dt.datetime

    @classmethod
    def from_model(cls, m: MediaAsset) -> "AdminMediaAsset":
        return cls(
            id=strawberry.ID(str(m.id)),
            storage_path=m.storage_path,
            public_url=m.public_url,
            original_filename=m.original_filename,
            mime_type=m.mime_type,
            size_bytes=m.size_bytes,
            width=m.width,
            height=m.height,
            uploaded_by_user_id=strawberry.ID(str(m.uploaded_by_user_id)),
            created_at=m.created_at,
        )


@strawberry.type
class AdminMediaAssetPage:
    assets: list[AdminMediaAsset]
    page: int
    per_page: int
    has_next: bool


@strawberry.type
class AdminHelpCategory:
    id: strawberry.ID
    slug: str
    name: str
    description: str
    icon: str
    order: int
    locale: str
    created_at: dt.datetime
    updated_at: dt.datetime
    resource_count: int

    @classmethod
    def from_model(cls, m: HelpCategory, resource_count: int | None = None) -> "AdminHelpCategory":
        return cls(
            id=strawberry.ID(str(m.id)),
            slug=m.slug,
            name=m.name,
            description=m.description,
            icon=m.icon,
            order=m.order,
            locale=m.locale,
            created_at=m.created_at,
            updated_at=m.updated_at,
            resource_count=(
                resource_count
                if resource_count is not None
                else m.resources.count()
            ),
        )


@strawberry.type
class AdminHelpResource:
    id: strawberry.ID
    slug: str
    title: str
    excerpt: str
    content_json: strawberry.scalars.JSON
    content_html: str
    cover_image_url: str
    category_id: strawberry.ID
    category_slug: str
    category_name: str
    status: str
    published_at: Optional[dt.datetime]
    author_user_id: strawberry.ID
    tags: list[str]
    seo_title: str
    seo_description: str
    locale: str
    order: int
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, m: HelpResource) -> "AdminHelpResource":
        return cls(
            id=strawberry.ID(str(m.id)),
            slug=m.slug,
            title=m.title,
            excerpt=m.excerpt,
            content_json=m.content_json or {},
            content_html=m.content_html,
            cover_image_url=m.cover_image_url,
            category_id=strawberry.ID(str(m.category_id)),
            category_slug=m.category.slug,
            category_name=m.category.name,
            status=m.status,
            published_at=m.published_at,
            author_user_id=strawberry.ID(str(m.author_user_id)),
            tags=list(m.tags or []),
            seo_title=m.seo_title,
            seo_description=m.seo_description,
            locale=m.locale,
            order=m.order,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )


@strawberry.type
class AdminHelpResourcePage:
    resources: list[AdminHelpResource]
    page: int
    per_page: int
    has_next: bool


# ---------- Inputs ----------


@strawberry.input
class BlogPostInput:
    title: str
    slug: str
    excerpt: Optional[str] = ""
    content_json: Optional[strawberry.scalars.JSON] = None
    cover_image_url: Optional[str] = ""
    tags: Optional[list[str]] = None
    seo_title: Optional[str] = ""
    seo_description: Optional[str] = ""
    locale: Optional[str] = "es"


@strawberry.input
class PageInput:
    title: str
    path: str
    excerpt: Optional[str] = ""
    content_json: Optional[strawberry.scalars.JSON] = None
    cover_image_url: Optional[str] = ""
    show_in_nav: Optional[bool] = False
    nav_order: Optional[int] = 0
    seo_title: Optional[str] = ""
    seo_description: Optional[str] = ""
    locale: Optional[str] = "es"


@strawberry.input
class MediaRegisterInput:
    storage_path: str
    public_url: str
    original_filename: Optional[str] = ""
    mime_type: Optional[str] = ""
    size_bytes: Optional[int] = 0
    width: Optional[int] = None
    height: Optional[int] = None


@strawberry.input
class HelpCategoryInput:
    name: str
    slug: str
    description: Optional[str] = ""
    icon: Optional[str] = ""
    order: Optional[int] = 0
    locale: Optional[str] = "es"


@strawberry.input
class HelpResourceInput:
    title: str
    slug: str
    category_id: strawberry.ID
    excerpt: Optional[str] = ""
    content_json: Optional[strawberry.scalars.JSON] = None
    cover_image_url: Optional[str] = ""
    tags: Optional[list[str]] = None
    seo_title: Optional[str] = ""
    seo_description: Optional[str] = ""
    locale: Optional[str] = "es"
    order: Optional[int] = 0


__all__ = [
    "AdminBlogPost",
    "AdminBlogPostPage",
    "AdminPage",
    "AdminMediaAsset",
    "AdminMediaAssetPage",
    "AdminHelpCategory",
    "AdminHelpResource",
    "AdminHelpResourcePage",
    "BlogPostInput",
    "PageInput",
    "MediaRegisterInput",
    "HelpCategoryInput",
    "HelpResourceInput",
]

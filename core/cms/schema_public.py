"""Public schema for the live site (continuu.it).

Reads only — and only PUBLISHED rows. No auth required, so the site
can SSR posts without forcing a Supabase session on visitors. The
admin-side `adminBlogPost*` resolvers are the write side.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

import strawberry
from django.core.cache import cache
from django.db.models import Count, Q
from graphql import GraphQLError
from strawberry.types import Info

from ..admin_api.supabase_admin import SupabaseAdminError, count_users
from .models import BlogPost, HelpCategory, HelpResource, Page, PostStatus

logger = logging.getLogger(__name__)

_USER_COUNT_CACHE_KEY = "public:platform_stats:user_count"
_USER_COUNT_TTL_SECONDS = 300


@strawberry.type
class PublicBlogPost:
    id: strawberry.ID
    slug: str
    title: str
    excerpt: str
    content_html: str
    cover_image_url: str
    published_at: Optional[dt.datetime]
    tags: list[str]
    seo_title: str
    seo_description: str
    locale: str


@strawberry.type
class PublicPage:
    id: strawberry.ID
    path: str
    title: str
    excerpt: str
    content_html: str
    cover_image_url: str
    published_at: Optional[dt.datetime]
    seo_title: str
    seo_description: str
    locale: str
    show_in_nav: bool
    nav_order: int


@strawberry.type
class PublicNavLink:
    path: str
    title: str
    nav_order: int


@strawberry.type
class PublicBlogPostPage:
    posts: list[PublicBlogPost]
    page: int
    per_page: int
    has_next: bool


@strawberry.type
class PublicHelpCategory:
    id: strawberry.ID
    slug: str
    name: str
    description: str
    icon: str
    order: int
    locale: str
    resource_count: int


@strawberry.type
class PublicHelpResource:
    id: strawberry.ID
    slug: str
    title: str
    excerpt: str
    content_html: str
    cover_image_url: str
    published_at: Optional[dt.datetime]
    tags: list[str]
    seo_title: str
    seo_description: str
    locale: str
    category_slug: str
    category_name: str


@strawberry.type
class PublicHelpResourcePage:
    resources: list[PublicHelpResource]
    page: int
    per_page: int
    has_next: bool


@strawberry.type
class PublicPlatformStats:
    user_count: int


def _to_public_help_category(m: HelpCategory, count: int | None = None) -> PublicHelpCategory:
    return PublicHelpCategory(
        id=strawberry.ID(str(m.id)),
        slug=m.slug,
        name=m.name,
        description=m.description,
        icon=m.icon,
        order=m.order,
        locale=m.locale,
        resource_count=count if count is not None else m.resources.filter(
            status=PostStatus.PUBLISHED
        ).count(),
    )


def _to_public_help_resource(
    m: HelpResource, *, include_content: bool = True
) -> PublicHelpResource:
    return PublicHelpResource(
        id=strawberry.ID(str(m.id)),
        slug=m.slug,
        title=m.title,
        excerpt=m.excerpt,
        # List views never render the body — deferring `content_html` keeps
        # this off both the DB read and the wire. Reading it here would
        # re-trigger a per-row query (N+1) on a deferred queryset.
        content_html=m.content_html if include_content else "",
        cover_image_url=m.cover_image_url,
        published_at=m.published_at,
        tags=list(m.tags or []),
        seo_title=m.seo_title,
        seo_description=m.seo_description,
        locale=m.locale,
        category_slug=m.category.slug,
        category_name=m.category.name,
    )


def _to_public_post(m: BlogPost, *, include_content: bool = True) -> PublicBlogPost:
    return PublicBlogPost(
        id=strawberry.ID(str(m.id)),
        slug=m.slug,
        title=m.title,
        excerpt=m.excerpt,
        # See `_to_public_help_resource`: list views defer `content_html`, so
        # don't read it here or we'd N+1 the deferred queryset.
        content_html=m.content_html if include_content else "",
        cover_image_url=m.cover_image_url,
        published_at=m.published_at,
        tags=list(m.tags or []),
        seo_title=m.seo_title,
        seo_description=m.seo_description,
        locale=m.locale,
    )


def _to_public_page(m: Page) -> PublicPage:
    return PublicPage(
        id=strawberry.ID(str(m.id)),
        path=m.path,
        title=m.title,
        excerpt=m.excerpt,
        content_html=m.content_html,
        cover_image_url=m.cover_image_url,
        published_at=m.published_at,
        seo_title=m.seo_title,
        seo_description=m.seo_description,
        locale=m.locale,
        show_in_nav=m.show_in_nav,
        nav_order=m.nav_order,
    )


@strawberry.type
class CmsPublicQuery:
    @strawberry.field(name="publicBlogPosts")
    def public_blog_posts(
        self,
        info: Info,
        locale: Optional[str] = None,
        tag: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> PublicBlogPostPage:
        per_page = max(1, min(per_page, 50))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = (
            BlogPost.objects.filter(status=PostStatus.PUBLISHED)
            .defer("content_html", "content_json")
            .order_by("-published_at")
        )
        if locale:
            qs = qs.filter(locale=locale)
        if tag:
            qs = qs.filter(tags__contains=[tag])

        items = list(qs[offset : offset + per_page + 1])
        has_next = len(items) > per_page
        items = items[:per_page]
        return PublicBlogPostPage(
            posts=[_to_public_post(m, include_content=False) for m in items],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="publicBlogPost")
    def public_blog_post(
        self, info: Info, slug: str, locale: Optional[str] = None
    ) -> Optional[PublicBlogPost]:
        qs = BlogPost.objects.filter(slug=slug, status=PostStatus.PUBLISHED)
        if locale:
            qs = qs.filter(locale=locale)
        m = qs.first()
        return _to_public_post(m) if m else None

    @strawberry.field(name="publicPage")
    def public_page(
        self, info: Info, path: str, locale: Optional[str] = None
    ) -> Optional[PublicPage]:
        if not path.startswith("/"):
            path = "/" + path
        qs = Page.objects.filter(path=path, status=PostStatus.PUBLISHED)
        if locale:
            qs = qs.filter(locale=locale)
        m = qs.first()
        return _to_public_page(m) if m else None

    @strawberry.field(name="publicNavPages")
    def public_nav_pages(
        self, info: Info, locale: Optional[str] = None
    ) -> list[PublicNavLink]:
        qs = Page.objects.filter(
            status=PostStatus.PUBLISHED, show_in_nav=True
        ).order_by("nav_order", "title")
        if locale:
            qs = qs.filter(locale=locale)
        return [
            PublicNavLink(path=p.path, title=p.title, nav_order=p.nav_order)
            for p in qs
        ]

    @strawberry.field(name="publicHelpCategories")
    def public_help_categories(
        self, info: Info, locale: Optional[str] = None
    ) -> list[PublicHelpCategory]:
        # One aggregated query instead of a COUNT per category (was N+1).
        qs = (
            HelpCategory.objects.annotate(
                published_count=Count(
                    "resources",
                    filter=Q(resources__status=PostStatus.PUBLISHED),
                )
            )
            .filter(published_count__gt=0)  # only categories with published content
            .order_by("order", "name")
        )
        if locale:
            qs = qs.filter(locale=locale)
        return [
            _to_public_help_category(cat, cat.published_count) for cat in qs
        ]

    @strawberry.field(name="publicHelpResources")
    def public_help_resources(
        self,
        info: Info,
        locale: Optional[str] = None,
        category_slug: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> PublicHelpResourcePage:
        per_page = max(1, min(per_page, 50))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = (
            HelpResource.objects.select_related("category")
            .defer("content_html", "content_json")
            .filter(status=PostStatus.PUBLISHED)
            .order_by("category__order", "order", "-published_at")
        )
        if locale:
            qs = qs.filter(locale=locale)
        if category_slug:
            qs = qs.filter(category__slug=category_slug)

        items = list(qs[offset : offset + per_page + 1])
        has_next = len(items) > per_page
        items = items[:per_page]
        return PublicHelpResourcePage(
            resources=[
                _to_public_help_resource(m, include_content=False) for m in items
            ],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="publicHelpResource")
    def public_help_resource(
        self, info: Info, slug: str, locale: Optional[str] = None
    ) -> Optional[PublicHelpResource]:
        qs = HelpResource.objects.select_related("category").filter(
            slug=slug, status=PostStatus.PUBLISHED
        )
        if locale:
            qs = qs.filter(locale=locale)
        m = qs.first()
        return _to_public_help_resource(m) if m else None

    @strawberry.field(name="publicPlatformStats")
    def public_platform_stats(self, info: Info) -> PublicPlatformStats:
        cached = cache.get(_USER_COUNT_CACHE_KEY)
        if isinstance(cached, int):
            return PublicPlatformStats(user_count=cached)
        try:
            count = count_users()
        except SupabaseAdminError as e:
            logger.warning("publicPlatformStats fallback: %s", e)
            count = 0
        cache.set(_USER_COUNT_CACHE_KEY, count, _USER_COUNT_TTL_SECONDS)
        return PublicPlatformStats(user_count=count)

"""Public schema for the live site (continuu.it).

Reads only — and only PUBLISHED rows. No auth required, so the site
can SSR posts without forcing a Supabase session on visitors. The
admin-side `adminBlogPost*` resolvers are the write side.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from .models import BlogPost, Page, PostStatus


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


def _to_public_post(m: BlogPost) -> PublicBlogPost:
    return PublicBlogPost(
        id=strawberry.ID(str(m.id)),
        slug=m.slug,
        title=m.title,
        excerpt=m.excerpt,
        content_html=m.content_html,
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

        qs = BlogPost.objects.filter(status=PostStatus.PUBLISHED).order_by(
            "-published_at"
        )
        if locale:
            qs = qs.filter(locale=locale)
        if tag:
            qs = qs.filter(tags__contains=[tag])

        items = list(qs[offset : offset + per_page + 1])
        has_next = len(items) > per_page
        items = items[:per_page]
        return PublicBlogPostPage(
            posts=[_to_public_post(m) for m in items],
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

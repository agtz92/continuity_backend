"""Admin-side CRUD over BlogPost / Page / MediaAsset.

Lives in the cms app (not admin_api) because it operates on cms models
and benefits from being close to them, but every resolver still goes
through `_admin_user_id` to enforce authorization.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Optional

import strawberry
from django.utils import timezone
from graphql import GraphQLError
from strawberry.types import Info

from core.admin_api.audit import record as audit_record
from core.admin_api.permissions import _admin_user_id

from .models import BlogPost, HelpCategory, HelpResource, MediaAsset, Page, PostStatus
from .rendering import render_tiptap


logger = logging.getLogger(__name__)


# ---------- Types ----------


# ---------- Types (extraídos a types.py, ver AUDITORIA_CODIGO.md) ----------
from .types import *  # noqa: F401,F403

# ---------- Helpers ----------


def _normalize_path(path: str) -> str:
    p = path.strip()
    if not p:
        raise GraphQLError("Path is required", extensions={"code": "BAD_INPUT"})
    if not p.startswith("/"):
        p = "/" + p
    # Reject paths reserved by other surfaces.
    reserved = {"/admin", "/login", "/blog", "/settings", "/api", "/_next"}
    if any(p == r or p.startswith(r + "/") for r in reserved):
        raise GraphQLError(
            f"Path {p!r} collides with a reserved route",
            extensions={"code": "BAD_INPUT"},
        )
    return p


# ---------- Query ----------


@strawberry.type
class CmsAdminQuery:
    @strawberry.field(name="adminBlogPosts")
    def admin_blog_posts(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 25,
        status: Optional[str] = None,
        locale: Optional[str] = None,
        search: Optional[str] = None,
    ) -> AdminBlogPostPage:
        _admin_user_id(info)
        per_page = max(1, min(per_page, 100))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = BlogPost.objects.all()
        if status:
            qs = qs.filter(status=status.lower())
        if locale:
            qs = qs.filter(locale=locale)
        if search:
            qs = qs.filter(title__icontains=search)

        items = list(qs[offset : offset + per_page + 1])
        has_next = len(items) > per_page
        items = items[:per_page]

        return AdminBlogPostPage(
            posts=[AdminBlogPost.from_model(m) for m in items],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="adminBlogPost")
    def admin_blog_post(self, info: Info, id: strawberry.ID) -> AdminBlogPost:
        _admin_user_id(info)
        try:
            m = BlogPost.objects.get(id=uuid.UUID(str(id)))
        except (BlogPost.DoesNotExist, ValueError):
            raise GraphQLError("Post not found", extensions={"code": "NOT_FOUND"})
        return AdminBlogPost.from_model(m)

    @strawberry.field(name="adminPages")
    def admin_pages(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 25,
        status: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> list[AdminPage]:
        _admin_user_id(info)
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = Page.objects.all()
        if status:
            qs = qs.filter(status=status.lower())
        if locale:
            qs = qs.filter(locale=locale)
        items = list(qs[offset : offset + per_page])
        return [AdminPage.from_model(m) for m in items]

    @strawberry.field(name="adminPage")
    def admin_page(self, info: Info, id: strawberry.ID) -> AdminPage:
        _admin_user_id(info)
        try:
            m = Page.objects.get(id=uuid.UUID(str(id)))
        except (Page.DoesNotExist, ValueError):
            raise GraphQLError("Page not found", extensions={"code": "NOT_FOUND"})
        return AdminPage.from_model(m)

    @strawberry.field(name="adminMediaAssets")
    def admin_media_assets(
        self, info: Info, page: int = 1, per_page: int = 50
    ) -> AdminMediaAssetPage:
        _admin_user_id(info)
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        offset = (page - 1) * per_page
        items = list(
            MediaAsset.objects.all()[offset : offset + per_page + 1]
        )
        has_next = len(items) > per_page
        items = items[:per_page]
        return AdminMediaAssetPage(
            assets=[AdminMediaAsset.from_model(m) for m in items],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="adminHelpCategories")
    def admin_help_categories(
        self, info: Info, locale: Optional[str] = None
    ) -> list[AdminHelpCategory]:
        _admin_user_id(info)
        qs = HelpCategory.objects.all()
        if locale:
            qs = qs.filter(locale=locale)
        return [AdminHelpCategory.from_model(m) for m in qs]

    @strawberry.field(name="adminHelpCategory")
    def admin_help_category(self, info: Info, id: strawberry.ID) -> AdminHelpCategory:
        _admin_user_id(info)
        try:
            m = HelpCategory.objects.get(id=uuid.UUID(str(id)))
        except (HelpCategory.DoesNotExist, ValueError):
            raise GraphQLError("Category not found", extensions={"code": "NOT_FOUND"})
        return AdminHelpCategory.from_model(m)

    @strawberry.field(name="adminHelpResources")
    def admin_help_resources(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 25,
        status: Optional[str] = None,
        locale: Optional[str] = None,
        category_id: Optional[strawberry.ID] = None,
        search: Optional[str] = None,
    ) -> AdminHelpResourcePage:
        _admin_user_id(info)
        per_page = max(1, min(per_page, 100))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = HelpResource.objects.select_related("category").all()
        if status:
            qs = qs.filter(status=status.lower())
        if locale:
            qs = qs.filter(locale=locale)
        if category_id:
            try:
                qs = qs.filter(category_id=uuid.UUID(str(category_id)))
            except ValueError:
                raise GraphQLError("Invalid categoryId", extensions={"code": "BAD_INPUT"})
        if search:
            qs = qs.filter(title__icontains=search)

        items = list(qs[offset : offset + per_page + 1])
        has_next = len(items) > per_page
        items = items[:per_page]
        return AdminHelpResourcePage(
            resources=[AdminHelpResource.from_model(m) for m in items],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="adminHelpResource")
    def admin_help_resource(self, info: Info, id: strawberry.ID) -> AdminHelpResource:
        _admin_user_id(info)
        try:
            m = HelpResource.objects.select_related("category").get(
                id=uuid.UUID(str(id))
            )
        except (HelpResource.DoesNotExist, ValueError):
            raise GraphQLError("Resource not found", extensions={"code": "NOT_FOUND"})
        return AdminHelpResource.from_model(m)


# ---------- Mutation ----------


@strawberry.type
class CmsAdminMutation:
    @strawberry.mutation(name="adminBlogPostCreate")
    def create_blog_post(self, info: Info, data: BlogPostInput) -> AdminBlogPost:
        actor = _admin_user_id(info)
        if not data.slug.strip():
            raise GraphQLError("Slug is required", extensions={"code": "BAD_INPUT"})
        if BlogPost.objects.filter(slug=data.slug).exists():
            raise GraphQLError(
                f"Slug '{data.slug}' is already in use",
                extensions={"code": "BAD_INPUT"},
            )
        content_json = data.content_json or {}
        post = BlogPost.objects.create(
            slug=data.slug.strip(),
            title=data.title,
            excerpt=data.excerpt or "",
            content_json=content_json,
            content_html=render_tiptap(content_json),
            cover_image_url=data.cover_image_url or "",
            tags=list(data.tags or []),
            seo_title=data.seo_title or "",
            seo_description=data.seo_description or "",
            locale=data.locale or "es",
            author_user_id=actor,
        )
        audit_record(
            actor_user_id=actor,
            action="blog_post.create",
            target_type="blog_post",
            target_id=post.id,
            payload={"slug": post.slug, "title": post.title},
        )
        return AdminBlogPost.from_model(post)

    @strawberry.mutation(name="adminBlogPostUpdate")
    def update_blog_post(
        self, info: Info, id: strawberry.ID, data: BlogPostInput
    ) -> AdminBlogPost:
        actor = _admin_user_id(info)
        try:
            post = BlogPost.objects.get(id=uuid.UUID(str(id)))
        except (BlogPost.DoesNotExist, ValueError):
            raise GraphQLError("Post not found", extensions={"code": "NOT_FOUND"})

        if data.slug and data.slug != post.slug:
            if BlogPost.objects.filter(slug=data.slug).exclude(pk=post.pk).exists():
                raise GraphQLError(
                    f"Slug '{data.slug}' is already in use",
                    extensions={"code": "BAD_INPUT"},
                )
            post.slug = data.slug.strip()

        before = {"title": post.title, "slug": post.slug}
        post.title = data.title
        post.excerpt = data.excerpt or ""
        if data.content_json is not None:
            post.content_json = data.content_json
            post.content_html = render_tiptap(data.content_json)
        if data.cover_image_url is not None:
            post.cover_image_url = data.cover_image_url
        if data.tags is not None:
            post.tags = list(data.tags)
        if data.seo_title is not None:
            post.seo_title = data.seo_title
        if data.seo_description is not None:
            post.seo_description = data.seo_description
        if data.locale:
            post.locale = data.locale
        post.save()

        audit_record(
            actor_user_id=actor,
            action="blog_post.update",
            target_type="blog_post",
            target_id=post.id,
            payload={"before": before, "after": {"title": post.title, "slug": post.slug}},
        )
        return AdminBlogPost.from_model(post)

    @strawberry.mutation(name="adminBlogPostPublish")
    def publish_blog_post(
        self, info: Info, id: strawberry.ID, published: bool
    ) -> AdminBlogPost:
        actor = _admin_user_id(info)
        try:
            post = BlogPost.objects.get(id=uuid.UUID(str(id)))
        except (BlogPost.DoesNotExist, ValueError):
            raise GraphQLError("Post not found", extensions={"code": "NOT_FOUND"})
        before_status = post.status
        if published:
            post.status = PostStatus.PUBLISHED
            if not post.published_at:
                post.published_at = timezone.now()
        else:
            post.status = PostStatus.DRAFT
        post.save(update_fields=["status", "published_at", "updated_at"])
        audit_record(
            actor_user_id=actor,
            action="blog_post.publish" if published else "blog_post.unpublish",
            target_type="blog_post",
            target_id=post.id,
            payload={"before": before_status, "after": post.status},
        )
        return AdminBlogPost.from_model(post)

    @strawberry.mutation(name="adminBlogPostDelete")
    def delete_blog_post(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        try:
            post = BlogPost.objects.get(id=uuid.UUID(str(id)))
        except (BlogPost.DoesNotExist, ValueError):
            raise GraphQLError("Post not found", extensions={"code": "NOT_FOUND"})
        slug = post.slug
        post.delete()
        audit_record(
            actor_user_id=actor,
            action="blog_post.delete",
            target_type="blog_post",
            target_id=id,
            payload={"slug": slug},
        )
        return True

    @strawberry.mutation(name="adminPageCreate")
    def create_page(self, info: Info, data: PageInput) -> AdminPage:
        actor = _admin_user_id(info)
        normalized = _normalize_path(data.path)
        if Page.objects.filter(path=normalized).exists():
            raise GraphQLError(
                f"Path '{normalized}' is already in use",
                extensions={"code": "BAD_INPUT"},
            )
        content_json = data.content_json or {}
        page = Page.objects.create(
            path=normalized,
            title=data.title,
            excerpt=data.excerpt or "",
            content_json=content_json,
            content_html=render_tiptap(content_json),
            cover_image_url=data.cover_image_url or "",
            show_in_nav=bool(data.show_in_nav),
            nav_order=data.nav_order or 0,
            seo_title=data.seo_title or "",
            seo_description=data.seo_description or "",
            locale=data.locale or "es",
            author_user_id=actor,
        )
        audit_record(
            actor_user_id=actor,
            action="page.create",
            target_type="page",
            target_id=page.id,
            payload={"path": page.path, "title": page.title},
        )
        return AdminPage.from_model(page)

    @strawberry.mutation(name="adminPageUpdate")
    def update_page(
        self, info: Info, id: strawberry.ID, data: PageInput
    ) -> AdminPage:
        actor = _admin_user_id(info)
        try:
            page = Page.objects.get(id=uuid.UUID(str(id)))
        except (Page.DoesNotExist, ValueError):
            raise GraphQLError("Page not found", extensions={"code": "NOT_FOUND"})
        normalized = _normalize_path(data.path)
        if normalized != page.path and Page.objects.filter(path=normalized).exclude(pk=page.pk).exists():
            raise GraphQLError(
                f"Path '{normalized}' is already in use",
                extensions={"code": "BAD_INPUT"},
            )
        before = {"title": page.title, "path": page.path}
        page.path = normalized
        page.title = data.title
        page.excerpt = data.excerpt or ""
        if data.content_json is not None:
            page.content_json = data.content_json
            page.content_html = render_tiptap(data.content_json)
        if data.cover_image_url is not None:
            page.cover_image_url = data.cover_image_url
        if data.show_in_nav is not None:
            page.show_in_nav = bool(data.show_in_nav)
        if data.nav_order is not None:
            page.nav_order = data.nav_order
        if data.seo_title is not None:
            page.seo_title = data.seo_title
        if data.seo_description is not None:
            page.seo_description = data.seo_description
        if data.locale:
            page.locale = data.locale
        page.save()

        audit_record(
            actor_user_id=actor,
            action="page.update",
            target_type="page",
            target_id=page.id,
            payload={"before": before, "after": {"title": page.title, "path": page.path}},
        )
        return AdminPage.from_model(page)

    @strawberry.mutation(name="adminPagePublish")
    def publish_page(
        self, info: Info, id: strawberry.ID, published: bool
    ) -> AdminPage:
        actor = _admin_user_id(info)
        try:
            page = Page.objects.get(id=uuid.UUID(str(id)))
        except (Page.DoesNotExist, ValueError):
            raise GraphQLError("Page not found", extensions={"code": "NOT_FOUND"})
        before_status = page.status
        if published:
            page.status = PostStatus.PUBLISHED
            if not page.published_at:
                page.published_at = timezone.now()
        else:
            page.status = PostStatus.DRAFT
        page.save(update_fields=["status", "published_at", "updated_at"])
        audit_record(
            actor_user_id=actor,
            action="page.publish" if published else "page.unpublish",
            target_type="page",
            target_id=page.id,
            payload={"before": before_status, "after": page.status},
        )
        return AdminPage.from_model(page)

    @strawberry.mutation(name="adminPageDelete")
    def delete_page(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        try:
            page = Page.objects.get(id=uuid.UUID(str(id)))
        except (Page.DoesNotExist, ValueError):
            raise GraphQLError("Page not found", extensions={"code": "NOT_FOUND"})
        path = page.path
        page.delete()
        audit_record(
            actor_user_id=actor,
            action="page.delete",
            target_type="page",
            target_id=id,
            payload={"path": path},
        )
        return True

    @strawberry.mutation(name="adminMediaRegister")
    def register_media(
        self, info: Info, data: MediaRegisterInput
    ) -> AdminMediaAsset:
        """Record an asset that was already uploaded to Supabase Storage.

        For Phase 2 we keep upload client-side using Supabase's regular
        Storage client + RLS — see frontend/src/lib/storage.ts. The
        admin user uploads, then calls this mutation with the resulting
        path + URL so the asset shows up in the media library.
        Signed-upload-URL emission can land later if RLS proves too
        permissive.
        """
        actor = _admin_user_id(info)
        if MediaAsset.objects.filter(storage_path=data.storage_path).exists():
            raise GraphQLError(
                "Asset already registered",
                extensions={"code": "BAD_INPUT"},
            )
        asset = MediaAsset.objects.create(
            storage_path=data.storage_path,
            public_url=data.public_url,
            original_filename=data.original_filename or "",
            mime_type=data.mime_type or "",
            size_bytes=data.size_bytes or 0,
            width=data.width,
            height=data.height,
            uploaded_by_user_id=actor,
        )
        audit_record(
            actor_user_id=actor,
            action="media.register",
            target_type="media_asset",
            target_id=asset.id,
            payload={"storage_path": asset.storage_path},
        )
        return AdminMediaAsset.from_model(asset)

    @strawberry.mutation(name="adminMediaDelete")
    def delete_media(self, info: Info, id: strawberry.ID) -> bool:
        """Delete only the DB row. Removing the file from Supabase
        Storage is the admin's responsibility for now."""
        actor = _admin_user_id(info)
        try:
            asset = MediaAsset.objects.get(id=uuid.UUID(str(id)))
        except (MediaAsset.DoesNotExist, ValueError):
            raise GraphQLError("Asset not found", extensions={"code": "NOT_FOUND"})
        path = asset.storage_path
        asset.delete()
        audit_record(
            actor_user_id=actor,
            action="media.delete",
            target_type="media_asset",
            target_id=id,
            payload={"storage_path": path},
        )
        return True

    # ---- Help categories ----

    @strawberry.mutation(name="adminHelpCategoryCreate")
    def create_help_category(
        self, info: Info, data: HelpCategoryInput
    ) -> AdminHelpCategory:
        actor = _admin_user_id(info)
        slug = (data.slug or "").strip()
        if not slug:
            raise GraphQLError("Slug is required", extensions={"code": "BAD_INPUT"})
        if HelpCategory.objects.filter(slug=slug).exists():
            raise GraphQLError(
                f"Slug '{slug}' is already in use",
                extensions={"code": "BAD_INPUT"},
            )
        cat = HelpCategory.objects.create(
            slug=slug,
            name=data.name,
            description=data.description or "",
            icon=data.icon or "",
            order=data.order or 0,
            locale=data.locale or "es",
        )
        audit_record(
            actor_user_id=actor,
            action="help_category.create",
            target_type="help_category",
            target_id=cat.id,
            payload={"slug": cat.slug, "name": cat.name},
        )
        return AdminHelpCategory.from_model(cat, resource_count=0)

    @strawberry.mutation(name="adminHelpCategoryUpdate")
    def update_help_category(
        self, info: Info, id: strawberry.ID, data: HelpCategoryInput
    ) -> AdminHelpCategory:
        actor = _admin_user_id(info)
        try:
            cat = HelpCategory.objects.get(id=uuid.UUID(str(id)))
        except (HelpCategory.DoesNotExist, ValueError):
            raise GraphQLError("Category not found", extensions={"code": "NOT_FOUND"})
        slug = (data.slug or "").strip()
        if slug and slug != cat.slug:
            if HelpCategory.objects.filter(slug=slug).exclude(pk=cat.pk).exists():
                raise GraphQLError(
                    f"Slug '{slug}' is already in use",
                    extensions={"code": "BAD_INPUT"},
                )
            cat.slug = slug
        before = {"name": cat.name, "slug": cat.slug}
        cat.name = data.name
        if data.description is not None:
            cat.description = data.description
        if data.icon is not None:
            cat.icon = data.icon
        if data.order is not None:
            cat.order = data.order
        if data.locale:
            cat.locale = data.locale
        cat.save()
        audit_record(
            actor_user_id=actor,
            action="help_category.update",
            target_type="help_category",
            target_id=cat.id,
            payload={"before": before, "after": {"name": cat.name, "slug": cat.slug}},
        )
        return AdminHelpCategory.from_model(cat)

    @strawberry.mutation(name="adminHelpCategoryDelete")
    def delete_help_category(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        try:
            cat = HelpCategory.objects.get(id=uuid.UUID(str(id)))
        except (HelpCategory.DoesNotExist, ValueError):
            raise GraphQLError("Category not found", extensions={"code": "NOT_FOUND"})
        if cat.resources.exists():
            raise GraphQLError(
                "Cannot delete a category that contains resources",
                extensions={"code": "BAD_INPUT"},
            )
        slug = cat.slug
        cat.delete()
        audit_record(
            actor_user_id=actor,
            action="help_category.delete",
            target_type="help_category",
            target_id=id,
            payload={"slug": slug},
        )
        return True

    # ---- Help resources ----

    @strawberry.mutation(name="adminHelpResourceCreate")
    def create_help_resource(
        self, info: Info, data: HelpResourceInput
    ) -> AdminHelpResource:
        actor = _admin_user_id(info)
        slug = (data.slug or "").strip()
        if not slug:
            raise GraphQLError("Slug is required", extensions={"code": "BAD_INPUT"})
        if HelpResource.objects.filter(slug=slug).exists():
            raise GraphQLError(
                f"Slug '{slug}' is already in use",
                extensions={"code": "BAD_INPUT"},
            )
        try:
            category = HelpCategory.objects.get(id=uuid.UUID(str(data.category_id)))
        except (HelpCategory.DoesNotExist, ValueError):
            raise GraphQLError("Category not found", extensions={"code": "BAD_INPUT"})
        content_json = data.content_json or {}
        resource = HelpResource.objects.create(
            slug=slug,
            title=data.title,
            excerpt=data.excerpt or "",
            content_json=content_json,
            content_html=render_tiptap(content_json),
            cover_image_url=data.cover_image_url or "",
            category=category,
            tags=list(data.tags or []),
            seo_title=data.seo_title or "",
            seo_description=data.seo_description or "",
            locale=data.locale or "es",
            order=data.order or 0,
            author_user_id=actor,
        )
        audit_record(
            actor_user_id=actor,
            action="help_resource.create",
            target_type="help_resource",
            target_id=resource.id,
            payload={"slug": resource.slug, "title": resource.title},
        )
        return AdminHelpResource.from_model(resource)

    @strawberry.mutation(name="adminHelpResourceUpdate")
    def update_help_resource(
        self, info: Info, id: strawberry.ID, data: HelpResourceInput
    ) -> AdminHelpResource:
        actor = _admin_user_id(info)
        try:
            resource = HelpResource.objects.select_related("category").get(
                id=uuid.UUID(str(id))
            )
        except (HelpResource.DoesNotExist, ValueError):
            raise GraphQLError("Resource not found", extensions={"code": "NOT_FOUND"})

        slug = (data.slug or "").strip()
        if slug and slug != resource.slug:
            if HelpResource.objects.filter(slug=slug).exclude(pk=resource.pk).exists():
                raise GraphQLError(
                    f"Slug '{slug}' is already in use",
                    extensions={"code": "BAD_INPUT"},
                )
            resource.slug = slug

        if data.category_id and str(data.category_id) != str(resource.category_id):
            try:
                new_cat = HelpCategory.objects.get(
                    id=uuid.UUID(str(data.category_id))
                )
            except (HelpCategory.DoesNotExist, ValueError):
                raise GraphQLError(
                    "Category not found", extensions={"code": "BAD_INPUT"}
                )
            resource.category = new_cat

        before = {"title": resource.title, "slug": resource.slug}
        resource.title = data.title
        resource.excerpt = data.excerpt or ""
        if data.content_json is not None:
            resource.content_json = data.content_json
            resource.content_html = render_tiptap(data.content_json)
        if data.cover_image_url is not None:
            resource.cover_image_url = data.cover_image_url
        if data.tags is not None:
            resource.tags = list(data.tags)
        if data.seo_title is not None:
            resource.seo_title = data.seo_title
        if data.seo_description is not None:
            resource.seo_description = data.seo_description
        if data.locale:
            resource.locale = data.locale
        if data.order is not None:
            resource.order = data.order
        resource.save()

        audit_record(
            actor_user_id=actor,
            action="help_resource.update",
            target_type="help_resource",
            target_id=resource.id,
            payload={"before": before, "after": {"title": resource.title, "slug": resource.slug}},
        )
        return AdminHelpResource.from_model(resource)

    @strawberry.mutation(name="adminHelpResourcePublish")
    def publish_help_resource(
        self, info: Info, id: strawberry.ID, published: bool
    ) -> AdminHelpResource:
        actor = _admin_user_id(info)
        try:
            resource = HelpResource.objects.select_related("category").get(
                id=uuid.UUID(str(id))
            )
        except (HelpResource.DoesNotExist, ValueError):
            raise GraphQLError("Resource not found", extensions={"code": "NOT_FOUND"})
        before_status = resource.status
        if published:
            resource.status = PostStatus.PUBLISHED
            if not resource.published_at:
                resource.published_at = timezone.now()
        else:
            resource.status = PostStatus.DRAFT
        resource.save(update_fields=["status", "published_at", "updated_at"])
        audit_record(
            actor_user_id=actor,
            action="help_resource.publish" if published else "help_resource.unpublish",
            target_type="help_resource",
            target_id=resource.id,
            payload={"before": before_status, "after": resource.status},
        )
        return AdminHelpResource.from_model(resource)

    @strawberry.mutation(name="adminHelpResourceDelete")
    def delete_help_resource(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        try:
            resource = HelpResource.objects.get(id=uuid.UUID(str(id)))
        except (HelpResource.DoesNotExist, ValueError):
            raise GraphQLError("Resource not found", extensions={"code": "NOT_FOUND"})
        slug = resource.slug
        resource.delete()
        audit_record(
            actor_user_id=actor,
            action="help_resource.delete",
            target_type="help_resource",
            target_id=id,
            payload={"slug": slug},
        )
        return True

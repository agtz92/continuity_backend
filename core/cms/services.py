"""Lógica de negocio del CMS admin: CRUD + publish sobre BlogPost / Page /
MediaAsset / HelpCategory / HelpResource.

Extraído de `schema_admin.py` para sacar el ORM, las validaciones y el render de
los resolvers (ver AUDITORIA_CODIGO.md): los resolvers quedan finos
(auth → servicio → `AdminX.from_model`). Cada función de escritura recibe `actor`
(id del admin, de `_admin_user_id`) y emite el `audit_record` correspondiente.
Las funciones levantan `GraphQLError` con los **mismos** `code`s que antes
(NOT_FOUND / BAD_INPUT) para no cambiar el contrato GraphQL; devuelven instancias
de modelo (el mapeo a tipo GraphQL se queda en el resolver).
"""

from __future__ import annotations

import uuid

import strawberry
from django.utils import timezone
from graphql import GraphQLError

from core.admin_api.audit import record as audit_record

from .models import BlogPost, HelpCategory, HelpResource, MediaAsset, Page, PostStatus
from .rendering import render_tiptap
from .types import (
    BlogPostInput,
    HelpCategoryInput,
    HelpResourceInput,
    MediaRegisterInput,
    PageInput,
)


# ---------- Helpers ----------


def normalize_path(path: str) -> str:
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


# ---------- BlogPost ----------


def get_blog_post(id: strawberry.ID) -> BlogPost:
    try:
        return BlogPost.objects.get(id=uuid.UUID(str(id)))
    except (BlogPost.DoesNotExist, ValueError):
        raise GraphQLError("Post not found", extensions={"code": "NOT_FOUND"})


def create_blog_post(actor: str, data: BlogPostInput) -> BlogPost:
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
    return post


def update_blog_post(actor: str, id: strawberry.ID, data: BlogPostInput) -> BlogPost:
    post = get_blog_post(id)

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
    return post


def set_blog_post_published(actor: str, id: strawberry.ID, published: bool) -> BlogPost:
    post = get_blog_post(id)
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
    return post


def delete_blog_post(actor: str, id: strawberry.ID) -> bool:
    post = get_blog_post(id)
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


# ---------- Page ----------


def get_page(id: strawberry.ID) -> Page:
    try:
        return Page.objects.get(id=uuid.UUID(str(id)))
    except (Page.DoesNotExist, ValueError):
        raise GraphQLError("Page not found", extensions={"code": "NOT_FOUND"})


def create_page(actor: str, data: PageInput) -> Page:
    normalized = normalize_path(data.path)
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
    return page


def update_page(actor: str, id: strawberry.ID, data: PageInput) -> Page:
    page = get_page(id)
    normalized = normalize_path(data.path)
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
    return page


def set_page_published(actor: str, id: strawberry.ID, published: bool) -> Page:
    page = get_page(id)
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
    return page


def delete_page(actor: str, id: strawberry.ID) -> bool:
    page = get_page(id)
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


# ---------- MediaAsset ----------


def register_media(actor: str, data: MediaRegisterInput) -> MediaAsset:
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
    return asset


def delete_media(actor: str, id: strawberry.ID) -> bool:
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


# ---------- HelpCategory ----------


def get_help_category(id: strawberry.ID) -> HelpCategory:
    try:
        return HelpCategory.objects.get(id=uuid.UUID(str(id)))
    except (HelpCategory.DoesNotExist, ValueError):
        raise GraphQLError("Category not found", extensions={"code": "NOT_FOUND"})


def create_help_category(actor: str, data: HelpCategoryInput) -> HelpCategory:
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
    return cat


def update_help_category(
    actor: str, id: strawberry.ID, data: HelpCategoryInput
) -> HelpCategory:
    cat = get_help_category(id)
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
    return cat


def delete_help_category(actor: str, id: strawberry.ID) -> bool:
    cat = get_help_category(id)
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


# ---------- HelpResource ----------


def get_help_resource(id: strawberry.ID) -> HelpResource:
    try:
        return HelpResource.objects.select_related("category").get(
            id=uuid.UUID(str(id))
        )
    except (HelpResource.DoesNotExist, ValueError):
        raise GraphQLError("Resource not found", extensions={"code": "NOT_FOUND"})


def create_help_resource(actor: str, data: HelpResourceInput) -> HelpResource:
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
    return resource


def update_help_resource(
    actor: str, id: strawberry.ID, data: HelpResourceInput
) -> HelpResource:
    resource = get_help_resource(id)

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
    return resource


def set_help_resource_published(
    actor: str, id: strawberry.ID, published: bool
) -> HelpResource:
    resource = get_help_resource(id)
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
    return resource


def delete_help_resource(actor: str, id: strawberry.ID) -> bool:
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

"""Admin-side CRUD over BlogPost / Page / MediaAsset / Help*.

Lives in the cms app (not admin_api) because it operates on cms models
and benefits from being close to them, but every resolver still goes
through `_admin_user_id` to enforce authorization.

Los resolvers son finos: autorizan, delegan en `core.cms.services` (ORM +
validaciones + render + auditoría) y mapean el modelo al tipo GraphQL con
`AdminX.from_model`. Las queries de **lista** conservan su paginación aquí
(no tienen lógica de negocio que extraer). Ver AUDITORIA_CODIGO.md.
"""

from __future__ import annotations

import uuid
from typing import Optional

import strawberry
from graphql import GraphQLError
from strawberry.types import Info

from core.admin_api.permissions import _admin_user_id

from . import services
from .models import BlogPost, HelpCategory, HelpResource, MediaAsset, Page

# ---------- Types (extraídos a types.py, ver AUDITORIA_CODIGO.md) ----------
from .types import *  # noqa: F401,F403


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
        return AdminBlogPost.from_model(services.get_blog_post(id))

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
        return AdminPage.from_model(services.get_page(id))

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
        return AdminHelpCategory.from_model(services.get_help_category(id))

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
        return AdminHelpResource.from_model(services.get_help_resource(id))


# ---------- Mutation ----------


@strawberry.type
class CmsAdminMutation:
    # ---- Blog posts ----

    @strawberry.mutation(name="adminBlogPostCreate")
    def create_blog_post(self, info: Info, data: BlogPostInput) -> AdminBlogPost:
        actor = _admin_user_id(info)
        return AdminBlogPost.from_model(services.create_blog_post(actor, data))

    @strawberry.mutation(name="adminBlogPostUpdate")
    def update_blog_post(
        self, info: Info, id: strawberry.ID, data: BlogPostInput
    ) -> AdminBlogPost:
        actor = _admin_user_id(info)
        return AdminBlogPost.from_model(services.update_blog_post(actor, id, data))

    @strawberry.mutation(name="adminBlogPostPublish")
    def publish_blog_post(
        self, info: Info, id: strawberry.ID, published: bool
    ) -> AdminBlogPost:
        actor = _admin_user_id(info)
        return AdminBlogPost.from_model(
            services.set_blog_post_published(actor, id, published)
        )

    @strawberry.mutation(name="adminBlogPostDelete")
    def delete_blog_post(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        return services.delete_blog_post(actor, id)

    # ---- Pages ----

    @strawberry.mutation(name="adminPageCreate")
    def create_page(self, info: Info, data: PageInput) -> AdminPage:
        actor = _admin_user_id(info)
        return AdminPage.from_model(services.create_page(actor, data))

    @strawberry.mutation(name="adminPageUpdate")
    def update_page(
        self, info: Info, id: strawberry.ID, data: PageInput
    ) -> AdminPage:
        actor = _admin_user_id(info)
        return AdminPage.from_model(services.update_page(actor, id, data))

    @strawberry.mutation(name="adminPagePublish")
    def publish_page(
        self, info: Info, id: strawberry.ID, published: bool
    ) -> AdminPage:
        actor = _admin_user_id(info)
        return AdminPage.from_model(services.set_page_published(actor, id, published))

    @strawberry.mutation(name="adminPageDelete")
    def delete_page(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        return services.delete_page(actor, id)

    # ---- Media ----

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
        return AdminMediaAsset.from_model(services.register_media(actor, data))

    @strawberry.mutation(name="adminMediaDelete")
    def delete_media(self, info: Info, id: strawberry.ID) -> bool:
        """Delete only the DB row. Removing the file from Supabase
        Storage is the admin's responsibility for now."""
        actor = _admin_user_id(info)
        return services.delete_media(actor, id)

    # ---- Help categories ----

    @strawberry.mutation(name="adminHelpCategoryCreate")
    def create_help_category(
        self, info: Info, data: HelpCategoryInput
    ) -> AdminHelpCategory:
        actor = _admin_user_id(info)
        return AdminHelpCategory.from_model(
            services.create_help_category(actor, data), resource_count=0
        )

    @strawberry.mutation(name="adminHelpCategoryUpdate")
    def update_help_category(
        self, info: Info, id: strawberry.ID, data: HelpCategoryInput
    ) -> AdminHelpCategory:
        actor = _admin_user_id(info)
        return AdminHelpCategory.from_model(
            services.update_help_category(actor, id, data)
        )

    @strawberry.mutation(name="adminHelpCategoryDelete")
    def delete_help_category(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        return services.delete_help_category(actor, id)

    # ---- Help resources ----

    @strawberry.mutation(name="adminHelpResourceCreate")
    def create_help_resource(
        self, info: Info, data: HelpResourceInput
    ) -> AdminHelpResource:
        actor = _admin_user_id(info)
        return AdminHelpResource.from_model(
            services.create_help_resource(actor, data)
        )

    @strawberry.mutation(name="adminHelpResourceUpdate")
    def update_help_resource(
        self, info: Info, id: strawberry.ID, data: HelpResourceInput
    ) -> AdminHelpResource:
        actor = _admin_user_id(info)
        return AdminHelpResource.from_model(
            services.update_help_resource(actor, id, data)
        )

    @strawberry.mutation(name="adminHelpResourcePublish")
    def publish_help_resource(
        self, info: Info, id: strawberry.ID, published: bool
    ) -> AdminHelpResource:
        actor = _admin_user_id(info)
        return AdminHelpResource.from_model(
            services.set_help_resource_published(actor, id, published)
        )

    @strawberry.mutation(name="adminHelpResourceDelete")
    def delete_help_resource(self, info: Info, id: strawberry.ID) -> bool:
        actor = _admin_user_id(info)
        return services.delete_help_resource(actor, id)

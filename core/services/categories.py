"""Category services."""

from __future__ import annotations

import uuid

from ..models import Category
from ..quotas import check_entity_quota
from ._cache import bump_context_version
from .projects import NotFoundError


def list_categories(user_id: uuid.UUID) -> list[Category]:
    return list(Category.objects.filter(user_id=user_id).order_by("name"))


def get_category(user_id: uuid.UUID, category_id) -> Category:
    obj = Category.objects.filter(pk=category_id, user_id=user_id).first()
    if obj is None:
        raise NotFoundError("Category not found")
    return obj


def create_category(
    user_id: uuid.UUID, *, name: str, color: str = "emerald"
) -> Category:
    existing = Category.objects.filter(user_id=user_id, name=name).first()
    if existing is None:
        check_entity_quota(user_id, "categories")
    category, _ = Category.objects.get_or_create(
        user_id=user_id,
        name=name,
        defaults={"color": color or "emerald"},
    )
    bump_context_version(user_id)
    return category


def update_category(
    user_id: uuid.UUID, category_id, *, name: str, color: str = ""
) -> Category:
    category = get_category(user_id, category_id)
    category.name = name
    if color:
        category.color = color
    category.save()
    bump_context_version(user_id)
    return category


def delete_category(user_id: uuid.UUID, category_id) -> None:
    Category.objects.filter(pk=category_id, user_id=user_id).delete()
    bump_context_version(user_id)

"""Admin and public GraphQL flows for help categories and resources."""

import pytest

from core.assistant.models import AccountProfile
from core.cms.models import HelpCategory, HelpResource, PostStatus


CREATE_CATEGORY = """
    mutation($data: HelpCategoryInput!) {
        adminHelpCategoryCreate(data: $data) {
            id slug name order
        }
    }
"""

UPDATE_CATEGORY = """
    mutation($id: ID!, $data: HelpCategoryInput!) {
        adminHelpCategoryUpdate(id: $id, data: $data) {
            id slug name order
        }
    }
"""

DELETE_CATEGORY = """
    mutation($id: ID!) { adminHelpCategoryDelete(id: $id) }
"""

LIST_CATEGORIES = """
    query { adminHelpCategories { id slug name resourceCount } }
"""

CREATE_RESOURCE = """
    mutation($data: HelpResourceInput!) {
        adminHelpResourceCreate(data: $data) {
            id slug title status contentHtml categoryId
        }
    }
"""

PUBLISH_RESOURCE = """
    mutation($id: ID!, $published: Boolean!) {
        adminHelpResourcePublish(id: $id, published: $published) {
            id status publishedAt
        }
    }
"""

PUBLIC_HELP_CATEGORIES = """
    query { publicHelpCategories { slug name resourceCount } }
"""

PUBLIC_HELP_RESOURCES = """
    query($categorySlug: String) {
        publicHelpResources(categorySlug: $categorySlug) {
            resources { slug title categorySlug }
            hasNext
        }
    }
"""

PUBLIC_HELP_RESOURCE = """
    query($slug: String!) {
        publicHelpResource(slug: $slug) {
            slug title contentHtml categorySlug
        }
    }
"""


def _admin(user_id):
    AccountProfile.objects.update_or_create(
        user_id=user_id, defaults={"is_admin": True}
    )


def _doc_for(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


@pytest.mark.django_db
def test_create_category_requires_admin(execute_query, user_a):
    result = execute_query(
        CREATE_CATEGORY,
        user_id=user_a,
        variable_values={"data": {"name": "Intro", "slug": "intro"}},
    )
    assert result.errors is not None
    assert not HelpCategory.objects.filter(slug="intro").exists()


@pytest.mark.django_db
def test_create_category_and_resource_renders_html(execute_query, user_a):
    _admin(user_a)
    cat = execute_query(
        CREATE_CATEGORY,
        user_id=user_a,
        variable_values={
            "data": {"name": "Primeros pasos", "slug": "primeros-pasos", "order": 1}
        },
    )
    assert cat.errors is None, cat.errors
    category_id = cat.data["adminHelpCategoryCreate"]["id"]

    res = execute_query(
        CREATE_RESOURCE,
        user_id=user_a,
        variable_values={
            "data": {
                "title": "Cómo empezar",
                "slug": "como-empezar",
                "categoryId": category_id,
                "contentJson": _doc_for("Bienvenida"),
            }
        },
    )
    assert res.errors is None, res.errors
    resource = HelpResource.objects.get(slug="como-empezar")
    assert resource.status == PostStatus.DRAFT
    assert "<p>Bienvenida</p>" in resource.content_html
    assert resource.category_id is not None


@pytest.mark.django_db
def test_create_resource_rejects_duplicate_slug(execute_query, user_a):
    _admin(user_a)
    cat = HelpCategory.objects.create(slug="c", name="C")
    payload = {
        "data": {
            "title": "A",
            "slug": "dup",
            "categoryId": str(cat.id),
            "contentJson": _doc_for("a"),
        }
    }
    execute_query(CREATE_RESOURCE, user_id=user_a, variable_values=payload)
    payload["data"]["title"] = "B"
    result = execute_query(CREATE_RESOURCE, user_id=user_a, variable_values=payload)
    assert result.errors is not None


@pytest.mark.django_db
def test_cannot_delete_category_with_resources(execute_query, user_a):
    _admin(user_a)
    cat = HelpCategory.objects.create(slug="c", name="C")
    HelpResource.objects.create(
        slug="r",
        title="R",
        category=cat,
        content_json={},
        content_html="",
        author_user_id=user_a,
    )
    result = execute_query(
        DELETE_CATEGORY,
        user_id=user_a,
        variable_values={"id": str(cat.id)},
    )
    assert result.errors is not None
    assert HelpCategory.objects.filter(pk=cat.pk).exists()


@pytest.mark.django_db
def test_publish_flow_visible_in_public_schema(
    execute_query, execute_public_query, user_a
):
    _admin(user_a)
    cat = HelpCategory.objects.create(slug="setup", name="Setup", order=1)
    create = execute_query(
        CREATE_RESOURCE,
        user_id=user_a,
        variable_values={
            "data": {
                "title": "Visible",
                "slug": "visible-resource",
                "categoryId": str(cat.id),
                "contentJson": _doc_for("body"),
            }
        },
    )
    assert create.errors is None, create.errors
    resource_id = create.data["adminHelpResourceCreate"]["id"]

    # Draft → category not visible because it has 0 published resources
    public = execute_public_query(PUBLIC_HELP_CATEGORIES)
    assert public.data["publicHelpCategories"] == []
    public_res = execute_public_query(
        PUBLIC_HELP_RESOURCES, variable_values={"categorySlug": "setup"}
    )
    assert public_res.data["publicHelpResources"]["resources"] == []

    # Publish
    pub = execute_query(
        PUBLISH_RESOURCE,
        user_id=user_a,
        variable_values={"id": resource_id, "published": True},
    )
    assert pub.errors is None, pub.errors
    assert pub.data["adminHelpResourcePublish"]["status"] == "published"

    # Now category shows up with count = 1
    public = execute_public_query(PUBLIC_HELP_CATEGORIES)
    cats = public.data["publicHelpCategories"]
    assert len(cats) == 1 and cats[0]["slug"] == "setup" and cats[0]["resourceCount"] == 1

    # Public resource fetch by slug
    one = execute_public_query(
        PUBLIC_HELP_RESOURCE, variable_values={"slug": "visible-resource"}
    )
    assert one.data["publicHelpResource"]["categorySlug"] == "setup"
    assert "<p>body</p>" in one.data["publicHelpResource"]["contentHtml"]


@pytest.mark.django_db
def test_list_categories_returns_resource_count(execute_query, user_a):
    _admin(user_a)
    cat = HelpCategory.objects.create(slug="a", name="A")
    HelpResource.objects.create(
        slug="r1",
        title="R1",
        category=cat,
        content_json={},
        content_html="",
        author_user_id=user_a,
    )
    HelpResource.objects.create(
        slug="r2",
        title="R2",
        category=cat,
        content_json={},
        content_html="",
        author_user_id=user_a,
    )
    result = execute_query(LIST_CATEGORIES, user_id=user_a)
    assert result.errors is None, result.errors
    found = next(
        c for c in result.data["adminHelpCategories"] if c["slug"] == "a"
    )
    assert found["resourceCount"] == 2

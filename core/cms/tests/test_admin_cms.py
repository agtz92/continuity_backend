"""Admin CMS mutations and queries.

Permission gate, slug/path uniqueness, publish flow, and that the
content is rendered to HTML on save.
"""

import pytest

from core.assistant.models import AccountProfile
from core.cms.models import BlogPost, Page, PostStatus


CREATE_POST = """
    mutation($data: BlogPostInput!) {
        adminBlogPostCreate(data: $data) {
            id slug title status contentHtml
        }
    }
"""

UPDATE_POST = """
    mutation($id: ID!, $data: BlogPostInput!) {
        adminBlogPostUpdate(id: $id, data: $data) {
            id slug title contentHtml
        }
    }
"""

PUBLISH_POST = """
    mutation($id: ID!, $published: Boolean!) {
        adminBlogPostPublish(id: $id, published: $published) {
            id status publishedAt
        }
    }
"""

DELETE_POST = """
    mutation($id: ID!) { adminBlogPostDelete(id: $id) }
"""

LIST_POSTS = """
    query { adminBlogPosts { posts { id slug title status } page hasNext } }
"""

CREATE_PAGE = """
    mutation($data: PageInput!) {
        adminPageCreate(data: $data) {
            id path title status
        }
    }
"""

PUBLIC_POST = """
    query($slug: String!) {
        publicBlogPost(slug: $slug) { slug title contentHtml }
    }
"""

PUBLIC_POSTS = """
    query { publicBlogPosts { posts { slug title } hasNext } }
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
def test_create_post_requires_admin(execute_query, user_a):
    result = execute_query(
        CREATE_POST,
        user_id=user_a,
        variable_values={
            "data": {"title": "Hi", "slug": "hi", "contentJson": _doc_for("body")}
        },
    )
    assert result.errors is not None
    assert not BlogPost.objects.filter(slug="hi").exists()


@pytest.mark.django_db
def test_create_post_persists_and_renders_html(execute_query, user_a):
    _admin(user_a)
    result = execute_query(
        CREATE_POST,
        user_id=user_a,
        variable_values={
            "data": {
                "title": "First",
                "slug": "first-post",
                "excerpt": "summary",
                "contentJson": _doc_for("Hello world"),
                "tags": ["news", "es"],
            }
        },
    )
    assert result.errors is None, result.errors
    post = BlogPost.objects.get(slug="first-post")
    assert post.status == PostStatus.DRAFT
    assert "<p>Hello world</p>" in post.content_html
    assert post.tags == ["news", "es"]


@pytest.mark.django_db
def test_create_post_rejects_duplicate_slug(execute_query, user_a):
    _admin(user_a)
    execute_query(
        CREATE_POST,
        user_id=user_a,
        variable_values={"data": {"title": "A", "slug": "x", "contentJson": _doc_for("a")}},
    )
    result = execute_query(
        CREATE_POST,
        user_id=user_a,
        variable_values={"data": {"title": "B", "slug": "x", "contentJson": _doc_for("b")}},
    )
    assert result.errors is not None


@pytest.mark.django_db
def test_publish_flow_visible_in_public_schema(
    execute_query, execute_public_query, user_a
):
    _admin(user_a)
    create = execute_query(
        CREATE_POST,
        user_id=user_a,
        variable_values={
            "data": {
                "title": "Visible",
                "slug": "visible",
                "contentJson": _doc_for("body"),
            }
        },
    )
    post_id = create.data["adminBlogPostCreate"]["id"]

    # Draft → not visible publicly
    public = execute_public_query(PUBLIC_POSTS)
    assert public.data["publicBlogPosts"]["posts"] == []

    # Publish
    pub = execute_query(
        PUBLISH_POST,
        user_id=user_a,
        variable_values={"id": post_id, "published": True},
    )
    assert pub.errors is None, pub.errors
    assert pub.data["adminBlogPostPublish"]["status"] == "published"

    # Now visible publicly
    public = execute_public_query(PUBLIC_POSTS)
    posts = public.data["publicBlogPosts"]["posts"]
    assert len(posts) == 1
    assert posts[0]["slug"] == "visible"

    detail = execute_public_query(PUBLIC_POST, variable_values={"slug": "visible"})
    assert detail.data["publicBlogPost"]["title"] == "Visible"

    # Unpublish → hidden again
    execute_query(
        PUBLISH_POST,
        user_id=user_a,
        variable_values={"id": post_id, "published": False},
    )
    public = execute_public_query(PUBLIC_POSTS)
    assert public.data["publicBlogPosts"]["posts"] == []


@pytest.mark.django_db
def test_page_rejects_reserved_path(execute_query, user_a):
    _admin(user_a)
    result = execute_query(
        CREATE_PAGE,
        user_id=user_a,
        variable_values={
            "data": {"title": "Hijack", "path": "/admin", "contentJson": _doc_for("x")}
        },
    )
    assert result.errors is not None
    assert not Page.objects.filter(path="/admin").exists()


@pytest.mark.django_db
def test_page_normalizes_and_creates(execute_query, user_a):
    _admin(user_a)
    result = execute_query(
        CREATE_PAGE,
        user_id=user_a,
        variable_values={
            "data": {"title": "About", "path": "about", "contentJson": _doc_for("a")}
        },
    )
    assert result.errors is None, result.errors
    assert Page.objects.filter(path="/about").exists()


@pytest.mark.django_db
def test_update_post_changes_content_html(execute_query, user_a):
    _admin(user_a)
    create = execute_query(
        CREATE_POST,
        user_id=user_a,
        variable_values={
            "data": {"title": "T", "slug": "t", "contentJson": _doc_for("v1")}
        },
    )
    post_id = create.data["adminBlogPostCreate"]["id"]
    update = execute_query(
        UPDATE_POST,
        user_id=user_a,
        variable_values={
            "id": post_id,
            "data": {"title": "T", "slug": "t", "contentJson": _doc_for("v2 updated")},
        },
    )
    assert update.errors is None, update.errors
    assert "v2 updated" in update.data["adminBlogPostUpdate"]["contentHtml"]


@pytest.mark.django_db
def test_delete_post_removes_row(execute_query, user_a):
    _admin(user_a)
    create = execute_query(
        CREATE_POST,
        user_id=user_a,
        variable_values={
            "data": {"title": "D", "slug": "d", "contentJson": _doc_for("v")}
        },
    )
    post_id = create.data["adminBlogPostCreate"]["id"]
    delete = execute_query(
        DELETE_POST, user_id=user_a, variable_values={"id": post_id}
    )
    assert delete.errors is None
    assert delete.data["adminBlogPostDelete"] is True
    assert not BlogPost.objects.filter(slug="d").exists()

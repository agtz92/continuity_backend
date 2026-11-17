"""The GraphQL view must carry the JWT `aal` claim to the resolver context."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory

from core.auth import JWTAuthGraphQLView, authenticate_request


def _auth(claims):
    req = RequestFactory().post("/graphql/", HTTP_AUTHORIZATION="Bearer t")
    with patch("core.auth.verify_supabase_jwt", return_value=claims), patch(
        "core.auth.is_ratelimited", return_value=False
    ):
        early = authenticate_request(
            req, ip_group="g", ip_rate="1/s", user_group="u", user_rate="1/s"
        )
    assert early is None
    return req


def test_aal2_reaches_context():
    uid = uuid.uuid4()
    req = _auth({"sub": str(uid), "aal": "aal2"})
    assert req.user_id == uid
    assert req.auth_aal == "aal2"


def test_get_context_copies_aal():
    req = _auth({"sub": str(uuid.uuid4()), "aal": "aal2"})
    from core.schema import schema

    view = JWTAuthGraphQLView(schema=schema)
    with patch("strawberry.django.views.GraphQLView.get_context", return_value=SimpleNamespace()):
        ctx = view.get_context(req, None)
    assert ctx.aal == "aal2"
    assert ctx.user_id == req.user_id


def test_missing_aal_is_none():
    req = _auth({"sub": str(uuid.uuid4())})
    assert req.auth_aal is None

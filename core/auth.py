import uuid
from typing import Optional

import jwt
from django.conf import settings
from django.http import JsonResponse
from strawberry.django.views import GraphQLView


class JWTAuthError(Exception):
    pass


def verify_supabase_jwt(token: str) -> dict:
    if not settings.SUPABASE_JWT_SECRET:
        raise JWTAuthError("Server is missing SUPABASE_JWT_SECRET")
    try:
        return jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise JWTAuthError("Token expired") from e
    except jwt.InvalidTokenError as e:
        raise JWTAuthError(f"Invalid token: {e}") from e


def extract_user_id(request) -> Optional[uuid.UUID]:
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return None
    claims = verify_supabase_jwt(token)
    sub = claims.get("sub")
    return uuid.UUID(sub) if sub else None


class JWTAuthGraphQLView(GraphQLView):
    """GraphQL view that requires a valid Supabase JWT and exposes user_id on context."""

    def dispatch(self, request, *args, **kwargs):
        # Allow GraphiQL GET in DEBUG without auth — convenience for local dev.
        if request.method == "GET" and settings.DEBUG:
            return super().dispatch(request, *args, **kwargs)
        try:
            user_id = extract_user_id(request)
        except JWTAuthError as e:
            return JsonResponse({"errors": [{"message": str(e)}]}, status=401)
        if user_id is None:
            return JsonResponse(
                {"errors": [{"message": "Authentication required"}]}, status=401
            )
        request.user_id = user_id
        return super().dispatch(request, *args, **kwargs)

    def get_context(self, request, response=None):
        context = super().get_context(request, response)
        context.user_id = getattr(request, "user_id", None)
        return context

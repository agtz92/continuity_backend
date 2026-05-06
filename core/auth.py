import uuid
from typing import Optional

import jwt
from jwt import PyJWKClient
from django.conf import settings
from django.http import JsonResponse
from strawberry.django.views import GraphQLView


class JWTAuthError(Exception):
    pass


_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> Optional[PyJWKClient]:
    """Lazily build a JWKS client for verifying Supabase asymmetric JWTs."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client
    if not settings.SUPABASE_URL:
        return None
    jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    _jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
    return _jwks_client


def verify_supabase_jwt(token: str) -> dict:
    """Verify a Supabase JWT.

    Tries the modern asymmetric path (ES256/RS256/EdDSA via JWKS) first,
    then falls back to legacy HS256 with a shared secret. Either path is
    enough — set SUPABASE_URL for the modern path or SUPABASE_JWT_SECRET
    for the legacy one.
    """
    last_error: Optional[Exception] = None

    client = _get_jwks_client()
    if client is not None:
        try:
            signing_key = client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=["ES256", "RS256", "EdDSA"],
                audience="authenticated",
                options={"require": ["exp", "sub"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise JWTAuthError("Token expired") from e
        except jwt.InvalidTokenError as e:
            last_error = e  # try HS256 fallback
        except Exception as e:
            last_error = e

    if settings.SUPABASE_JWT_SECRET:
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
            last_error = e

    if last_error is not None:
        raise JWTAuthError(f"Invalid token: {last_error}")
    raise JWTAuthError(
        "Server is missing SUPABASE_URL (preferred) or SUPABASE_JWT_SECRET"
    )


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

from django.contrib import admin
from django.urls import include, path, re_path
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from core.schema import schema
from core.auth import JWTAuthGraphQLView
from core.cms.views import PublicGraphQLView, public_schema
from core.mcp.views import McpView
from core.mcp.oauth import views as oauth_views
from core import google_tasks_views
from core import calendar_views


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql/", csrf_exempt(JWTAuthGraphQLView.as_view(schema=schema))),
    # Acepta /mcp y /mcp/ sin redirect 301 (Claude normaliza la URL sin slash
    # y los clientes MCP no siguen redirects en el POST).
    re_path(r"^mcp/?$", McpView.as_view()),
    # MCP OAuth 2.1 (discovery + DCR + authorize + token).
    path(
        ".well-known/oauth-protected-resource",
        oauth_views.protected_resource_metadata,
    ),
    path(
        ".well-known/oauth-protected-resource/mcp",
        oauth_views.protected_resource_metadata,
    ),
    path(
        ".well-known/oauth-authorization-server",
        oauth_views.authorization_server_metadata,
    ),
    path("oauth/register", csrf_exempt(oauth_views.register)),
    path("oauth/authorize", oauth_views.authorize),
    path("oauth/authorize/approve", csrf_exempt(oauth_views.approve)),
    path("oauth/token", csrf_exempt(oauth_views.token)),
    path(
        "public-graphql/",
        csrf_exempt(PublicGraphQLView.as_view(schema=public_schema)),
    ),
    path("api/", include("core.notifications.urls")),
    path("api/assistant/", include("core.assistant.urls")),
    path("api/billing/", include("core.billing.urls")),
    path(
        "api/google/oauth/callback",
        google_tasks_views.oauth_callback,
        name="google-oauth-callback",
    ),
    path(
        "api/calendar/feed/<str:token>.ics",
        calendar_views.ics_feed,
        name="calendar-ics-feed",
    ),
    path("healthz", healthcheck),
    path("", healthcheck),
]

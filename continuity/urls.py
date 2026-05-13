from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from core.schema import schema
from core.auth import JWTAuthGraphQLView
from core.cms.views import PublicGraphQLView, public_schema


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql/", csrf_exempt(JWTAuthGraphQLView.as_view(schema=schema))),
    path(
        "public-graphql/",
        csrf_exempt(PublicGraphQLView.as_view(schema=public_schema)),
    ),
    path("api/", include("core.notifications.urls")),
    path("api/assistant/", include("core.assistant.urls")),
    path("healthz", healthcheck),
    path("", healthcheck),
]

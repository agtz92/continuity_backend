from django.contrib import admin
from django.urls import path
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from core.schema import schema
from core.auth import JWTAuthGraphQLView


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql/", csrf_exempt(JWTAuthGraphQLView.as_view(schema=schema))),
    path("healthz", healthcheck),
    path("", healthcheck),
]

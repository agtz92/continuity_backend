from django.contrib import admin
from django.urls import path
from django.http import JsonResponse
from strawberry.django.views import GraphQLView

from core.schema import schema
from core.auth import JWTAuthGraphQLView


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql/", JWTAuthGraphQLView.as_view(schema=schema)),
    path("healthz", healthcheck),
    path("", healthcheck),
]

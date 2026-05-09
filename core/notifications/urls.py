from django.urls import path
from . import views

urlpatterns = [
    path(
        "telegram/webhook/<str:secret>/",
        views.telegram_webhook,
        name="telegram_webhook",
    ),
]

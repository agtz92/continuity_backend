from django.urls import path

from .store_webhooks import store_webhook


urlpatterns = [
    # RevenueCat entrega aquí los eventos de los tres canales (web, App Store,
    # Google Play). El nombre de ruta se conserva por compatibilidad con el
    # webhook que ya pueda estar configurado en el dashboard.
    path("store-webhook/", store_webhook, name="store-webhook"),
    path("revenuecat/", store_webhook, name="revenuecat-webhook"),
]

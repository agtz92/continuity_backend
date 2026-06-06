from .base import NotificationProvider, DeliveryResult, ProviderError
from .telegram import TelegramProvider

__all__ = [
    "NotificationProvider",
    "DeliveryResult",
    "ProviderError",
    "TelegramProvider",
    "get_provider",
]


def get_provider(channel: str) -> NotificationProvider:
    """Factory: channel string -> Provider instance."""
    if channel == "telegram":
        return TelegramProvider()
    if channel == "whatsapp":
        from .whatsapp import TwilioWhatsAppProvider  # lazy import — Fase 4
        return TwilioWhatsAppProvider()
    if channel == "expo":
        from .expo import ExpoProvider  # lazy import — push (Fase 8)
        return ExpoProvider()
    raise ProviderError(f"Unknown channel: {channel}")

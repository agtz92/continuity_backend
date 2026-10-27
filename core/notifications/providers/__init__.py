from .base import NotificationProvider, DeliveryResult, ProviderError

__all__ = [
    "NotificationProvider",
    "DeliveryResult",
    "ProviderError",
    "get_provider",
]


def get_provider(channel: str) -> NotificationProvider:
    """Factory: channel string -> Provider instance. Push (Expo) is the only
    channel since Telegram was removed (2026-10)."""
    if channel == "expo":
        from .expo import ExpoProvider
        return ExpoProvider()
    raise ProviderError(f"Unknown channel: {channel}")

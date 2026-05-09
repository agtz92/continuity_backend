from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class ProviderError(Exception):
    """Raised by providers for unrecoverable send failures."""


@dataclass
class DeliveryResult:
    success: bool
    external_message_id: str = ""
    error: str = ""


class NotificationProvider(ABC):
    """Channel-agnostic interface. Each channel implements send()."""

    channel: str  # "telegram", "whatsapp", ...

    @abstractmethod
    def send(self, external_id: str, body: str, *, kind: Optional[str] = None) -> DeliveryResult:
        """Deliver `body` to `external_id` (chat_id, phone, etc.).

        `kind` is passed for providers that need to pick a template (WhatsApp HSM).
        Telegram ignores it.
        """
        raise NotImplementedError

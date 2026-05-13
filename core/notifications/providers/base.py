from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Sequence, TypedDict


class ProviderError(Exception):
    """Raised by providers for unrecoverable send failures."""


@dataclass
class DeliveryResult:
    success: bool
    external_message_id: str = ""
    error: str = ""


class InlineButton(TypedDict):
    """A button shown under the message. Maps 1:1 to Telegram inline_keyboard
    URL buttons. Other channels degrade gracefully (e.g. WhatsApp appends the
    URL inline, since free-form messages can't carry rich keyboards)."""

    text: str
    url: str


class NotificationProvider(ABC):
    """Channel-agnostic interface. Each channel implements send()."""

    channel: str  # "telegram", "whatsapp", ...

    @abstractmethod
    def send(
        self,
        external_id: str,
        body: str,
        *,
        kind: Optional[str] = None,
        buttons: Optional[Sequence[InlineButton]] = None,
    ) -> DeliveryResult:
        """Deliver `body` to `external_id` (chat_id, phone, etc.).

        `kind` is passed for providers that need to pick a template (WhatsApp HSM).
        Telegram ignores it. `buttons`, when present, render as a one-button-per-row
        inline keyboard on Telegram.
        """
        raise NotImplementedError

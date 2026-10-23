from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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


@dataclass
class PushContent:
    """The phone-sized version of a notification.

    Builders write this next to the long Telegram body so push never receives
    the full digest. Plain text (no MarkdownV2). `category` names an action set
    the mobile app registers (`task_focus`, `tasks_bulk`); `android_channel` lets
    Android users silence each kind separately; `quiet` delivers without sound
    (iOS "passive"); `data` rides along to the app (e.g. the task ids the action
    buttons act on).
    """

    title: str
    body: str
    path: str = "/today"
    category: str = ""
    android_channel: str = ""
    quiet: bool = False
    data: dict = field(default_factory=dict)


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
        push: Optional[PushContent] = None,
    ) -> DeliveryResult:
        """Deliver `body` to `external_id` (chat_id, phone, etc.).

        `kind` is passed for providers that need to pick a template (WhatsApp HSM).
        Telegram ignores it. `buttons`, when present, render as a one-button-per-row
        inline keyboard on Telegram. `push` is the short version only the
        Expo provider reads; chat channels ignore it.
        """
        raise NotImplementedError

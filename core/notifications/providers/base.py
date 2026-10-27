from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class ProviderError(Exception):
    """Raised by providers for unrecoverable send failures."""


@dataclass
class DeliveryResult:
    success: bool
    external_message_id: str = ""
    error: str = ""


@dataclass
class PushContent:
    """What a push shows: plain-text title plus one or two lines.

    `category` names an action set
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

    channel: str  # "expo"

    @abstractmethod
    def send(
        self,
        external_id: str,
        push: PushContent,
        *,
        kind: Optional[str] = None,
    ) -> DeliveryResult:
        """Deliver `push` to `external_id` (a device token). `kind` rides along
        in the payload so the app knows what it received."""
        raise NotImplementedError

"""Strawberry GraphQL surface for notifications.

Exposes:
- query notificationSettings → user settings + linked channels
- mutation updateNotificationSettings(...)
- mutation requestChannelLink(channel) → { token, deepLink, expiresAt }
- mutation disconnectChannel(channel) → bool
"""

from __future__ import annotations

import datetime as dt
import enum
import secrets
import uuid
from typing import List, Optional

import strawberry
from django.conf import settings as django_settings
from django.utils import timezone
from graphql import GraphQLError
from strawberry.types import Info

from .models import (
    Channel,
    NotificationLink,
    NotificationSettings as SettingsModel,
)

LINK_TOKEN_TTL = dt.timedelta(minutes=15)


def _user_id(info: Info) -> uuid.UUID:
    uid = getattr(info.context, "user_id", None)
    if not uid:
        raise GraphQLError("Not authenticated", extensions={"code": "UNAUTHENTICATED"})
    return uid


@strawberry.enum
class NotificationChannel(enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


@strawberry.type
class NotificationLinkType:
    channel: str
    connected: bool
    verified_at: Optional[dt.datetime]


@strawberry.type
class NotificationSettingsType:
    locale: str
    theme: str
    palette: str
    timezone: str
    digest_enabled: bool
    digest_day_of_week: int
    digest_hour: int
    sleeping_alerts_enabled: bool
    due_reminders_enabled: bool
    due_reminder_lead_hours: int
    manual_enabled: bool
    is_admin: bool
    links: List[NotificationLinkType]


@strawberry.type
class ChannelLinkRequest:
    token: str
    deep_link: str
    expires_at: dt.datetime


@strawberry.input
class NotificationSettingsInput:
    locale: Optional[str] = None
    theme: Optional[str] = None
    palette: Optional[str] = None
    timezone: Optional[str] = None
    digest_enabled: Optional[bool] = None
    digest_day_of_week: Optional[int] = None
    digest_hour: Optional[int] = None
    sleeping_alerts_enabled: Optional[bool] = None
    due_reminders_enabled: Optional[bool] = None
    due_reminder_lead_hours: Optional[int] = None
    manual_enabled: Optional[bool] = None


SUPPORTED_LOCALES = {"en", "es"}
SUPPORTED_THEMES = {"light", "dark", "system"}
SUPPORTED_PALETTES = {
    "default",
    "pink",
    "business",
    "neon",
    "green",
    "turquoise",
    "cute",
    "midnight",
    "boho",
    "complimentary",
    "sunset",
    "retro",
}


def _to_gql(s: SettingsModel) -> NotificationSettingsType:
    links_qs = NotificationLink.objects.filter(user_id=s.user_id)
    return NotificationSettingsType(
        locale=s.locale,
        theme=s.theme,
        palette=s.palette,
        timezone=s.timezone,
        digest_enabled=s.digest_enabled,
        digest_day_of_week=s.digest_day_of_week,
        digest_hour=s.digest_hour,
        sleeping_alerts_enabled=s.sleeping_alerts_enabled,
        due_reminders_enabled=s.due_reminders_enabled,
        due_reminder_lead_hours=s.due_reminder_lead_hours,
        manual_enabled=s.manual_enabled,
        is_admin=s.is_admin,
        links=[
            NotificationLinkType(
                channel=link.channel,
                connected=bool(link.verified_at),
                verified_at=link.verified_at,
            )
            for link in links_qs
        ],
    )


def _get_or_create_settings(user_id: uuid.UUID) -> SettingsModel:
    default_tz = getattr(
        django_settings, "NOTIFICATIONS_DEFAULT_TIMEZONE", "America/Mexico_City"
    )
    s, _ = SettingsModel.objects.get_or_create(
        user_id=user_id, defaults={"timezone": default_tz}
    )
    return s


@strawberry.type
class NotificationsQuery:
    @strawberry.field
    def notification_settings(self, info: Info) -> NotificationSettingsType:
        uid = _user_id(info)
        return _to_gql(_get_or_create_settings(uid))


@strawberry.type
class NotificationsMutation:
    @strawberry.mutation
    def update_notification_settings(
        self, info: Info, data: NotificationSettingsInput
    ) -> NotificationSettingsType:
        uid = _user_id(info)
        s = _get_or_create_settings(uid)

        # Apply only fields the client sent (None means "leave alone")
        if data.locale is not None:
            if data.locale not in SUPPORTED_LOCALES:
                raise GraphQLError(
                    f"Unsupported locale: {data.locale}",
                    extensions={"code": "INVALID_LOCALE"},
                )
            s.locale = data.locale
        if data.theme is not None:
            if data.theme not in SUPPORTED_THEMES:
                raise GraphQLError(
                    f"Unsupported theme: {data.theme}",
                    extensions={"code": "INVALID_THEME"},
                )
            s.theme = data.theme
        if data.palette is not None:
            if data.palette not in SUPPORTED_PALETTES:
                raise GraphQLError(
                    f"Unsupported palette: {data.palette}",
                    extensions={"code": "INVALID_PALETTE"},
                )
            s.palette = data.palette
        if data.timezone is not None:
            s.timezone = data.timezone
        if data.digest_enabled is not None:
            s.digest_enabled = data.digest_enabled
        if data.digest_day_of_week is not None:
            s.digest_day_of_week = max(0, min(6, data.digest_day_of_week))
        if data.digest_hour is not None:
            s.digest_hour = max(0, min(23, data.digest_hour))
        if data.sleeping_alerts_enabled is not None:
            s.sleeping_alerts_enabled = data.sleeping_alerts_enabled
        if data.due_reminders_enabled is not None:
            s.due_reminders_enabled = data.due_reminders_enabled
        if data.due_reminder_lead_hours is not None:
            s.due_reminder_lead_hours = max(1, min(168, data.due_reminder_lead_hours))
        if data.manual_enabled is not None:
            s.manual_enabled = data.manual_enabled
        s.save()
        return _to_gql(s)

    @strawberry.mutation
    def request_channel_link(
        self, info: Info, channel: NotificationChannel
    ) -> ChannelLinkRequest:
        uid = _user_id(info)
        if channel != NotificationChannel.TELEGRAM:
            raise GraphQLError(
                "Only Telegram is implemented in Phase 1",
                extensions={"code": "NOT_IMPLEMENTED"},
            )

        bot_username = getattr(django_settings, "TELEGRAM_BOT_USERNAME", "")
        if not bot_username:
            raise GraphQLError(
                "Server is missing TELEGRAM_BOT_USERNAME",
                extensions={"code": "SERVER_MISCONFIGURED"},
            )

        token = secrets.token_urlsafe(24)
        expires = timezone.now() + LINK_TOKEN_TTL

        # Delete any existing UNverified link for this channel (clean slate),
        # but keep verified ones — those are reissued via disconnect first.
        existing = NotificationLink.objects.filter(
            user_id=uid, channel=channel.value
        ).first()
        if existing and existing.verified_at is None:
            existing.link_token = token
            existing.link_token_expires = expires
            existing.save(update_fields=["link_token", "link_token_expires"])
        elif existing is None:
            NotificationLink.objects.create(
                user_id=uid,
                channel=channel.value,
                link_token=token,
                link_token_expires=expires,
            )
        else:
            # Already verified — caller should disconnect first
            raise GraphQLError(
                "Channel is already connected. Disconnect first.",
                extensions={"code": "ALREADY_CONNECTED"},
            )

        deep_link = f"https://t.me/{bot_username}?start={token}"
        return ChannelLinkRequest(token=token, deep_link=deep_link, expires_at=expires)

    @strawberry.mutation
    def disconnect_channel(self, info: Info, channel: NotificationChannel) -> bool:
        uid = _user_id(info)
        NotificationLink.objects.filter(user_id=uid, channel=channel.value).delete()
        return True

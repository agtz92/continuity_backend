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
import zoneinfo
from typing import List, Optional

import strawberry
from django.conf import settings as django_settings
from django.utils import timezone
from graphql import GraphQLError
from strawberry.types import Info

from .models import (
    Channel,
    ExpoPushToken,
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
    daily_digest_enabled: bool
    daily_digest_hour: int
    sleeping_alerts_enabled: bool  # deprecated alias of stalled_alerts_enabled
    stalled_alerts_enabled: bool
    due_reminders_enabled: bool
    due_reminder_hour: int
    manual_enabled: bool
    push_enabled: bool
    is_admin: bool
    calendar_sync_enabled: bool
    calendar_sync_tasks: bool
    calendar_sync_routines: bool
    calendar_feed_token: str
    google_calendar_id: str
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
    daily_digest_enabled: Optional[bool] = None
    daily_digest_hour: Optional[int] = None
    sleeping_alerts_enabled: Optional[bool] = None  # deprecated alias
    stalled_alerts_enabled: Optional[bool] = None
    due_reminders_enabled: Optional[bool] = None
    due_reminder_hour: Optional[int] = None
    manual_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    calendar_sync_enabled: Optional[bool] = None
    calendar_sync_tasks: Optional[bool] = None
    calendar_sync_routines: Optional[bool] = None
    google_calendar_id: Optional[str] = None


SUPPORTED_LOCALES = {"en", "es"}
SUPPORTED_THEMES = {"continuuit", "light", "dark", "system"}
SUPPORTED_PALETTES = {
    "default",
    "continuuit",
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
SUPPORTED_TIMEZONES = zoneinfo.available_timezones()


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
        daily_digest_enabled=s.daily_digest_enabled,
        daily_digest_hour=s.daily_digest_hour,
        sleeping_alerts_enabled=s.sleeping_alerts_enabled,
        stalled_alerts_enabled=s.sleeping_alerts_enabled,
        due_reminders_enabled=s.due_reminders_enabled,
        due_reminder_hour=s.due_reminder_hour,
        manual_enabled=s.manual_enabled,
        push_enabled=s.push_enabled,
        is_admin=s.is_admin,
        calendar_sync_enabled=s.calendar_sync_enabled,
        calendar_sync_tasks=s.calendar_sync_tasks,
        calendar_sync_routines=s.calendar_sync_routines,
        calendar_feed_token=s.calendar_feed_token,
        google_calendar_id=s.google_calendar_id,
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
            if data.timezone not in SUPPORTED_TIMEZONES:
                raise GraphQLError(
                    f"Unsupported timezone: {data.timezone}",
                    extensions={"code": "INVALID_TIMEZONE"},
                )
            s.timezone = data.timezone
        if data.digest_enabled is not None:
            s.digest_enabled = data.digest_enabled
        if data.digest_day_of_week is not None:
            s.digest_day_of_week = max(0, min(6, data.digest_day_of_week))
        if data.digest_hour is not None:
            s.digest_hour = max(0, min(23, data.digest_hour))
        if data.daily_digest_enabled is not None:
            s.daily_digest_enabled = data.daily_digest_enabled
        if data.daily_digest_hour is not None:
            s.daily_digest_hour = max(0, min(23, data.daily_digest_hour))
        if data.sleeping_alerts_enabled is not None:
            s.sleeping_alerts_enabled = data.sleeping_alerts_enabled
        if data.stalled_alerts_enabled is not None:
            # Alias maps onto the same column during expand→migrate→contract.
            s.sleeping_alerts_enabled = data.stalled_alerts_enabled
        if data.due_reminders_enabled is not None:
            s.due_reminders_enabled = data.due_reminders_enabled
        if data.due_reminder_hour is not None:
            s.due_reminder_hour = max(0, min(23, data.due_reminder_hour))
        if data.manual_enabled is not None:
            s.manual_enabled = data.manual_enabled
        if data.push_enabled is not None:
            s.push_enabled = data.push_enabled
        if data.calendar_sync_enabled is not None:
            s.calendar_sync_enabled = data.calendar_sync_enabled
        if data.calendar_sync_tasks is not None:
            s.calendar_sync_tasks = data.calendar_sync_tasks
        if data.calendar_sync_routines is not None:
            s.calendar_sync_routines = data.calendar_sync_routines
        if data.google_calendar_id is not None:
            s.google_calendar_id = data.google_calendar_id.strip()[:128]
        s.save()
        return _to_gql(s)

    @strawberry.mutation
    def register_push_token(self, info: Info, token: str, device_id: str) -> bool:
        """Store/refresh the Expo push token for the caller's device.

        Keyed by (user_id, device_id) so re-registering the same device updates
        the token in place. Returns True. Matches the mobile client's
        registerPushToken(token, deviceId).
        """
        uid = _user_id(info)
        token = (token or "").strip()
        device_id = (device_id or "").strip()
        if not token or not device_id:
            raise GraphQLError(
                "token and deviceId are required",
                extensions={"code": "INVALID_INPUT"},
            )
        ExpoPushToken.objects.update_or_create(
            user_id=uid, device_id=device_id, defaults={"token": token}
        )
        return True

    @strawberry.mutation
    def unregister_push_token(self, info: Info, device_id: str) -> bool:
        """Remove the caller's Expo push token for a device (logout / opt-out)."""
        uid = _user_id(info)
        ExpoPushToken.objects.filter(user_id=uid, device_id=(device_id or "").strip()).delete()
        return True

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

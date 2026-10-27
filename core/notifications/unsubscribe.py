"""Unsubscribe from lifecycle emails (welcome / inactivity / re-engage).

Every lifecycle email carries a signed link and the `List-Unsubscribe` +
`List-Unsubscribe-Post` headers (RFC 8058), so Gmail/Apple Mail show their own
"Unsubscribe" button. The token is the user id signed with SECRET_KEY: no login
is needed and nothing guessable is in the URL.

GET shows a confirm button and changes nothing, because mail scanners prefetch
links; POST (the button, or the mail client's one-click request) turns
`NotificationSettings.lifecycle_emails_enabled` off. Turning it back on is a
toggle in Settings → Notifications.
"""

from __future__ import annotations

import html
import uuid
from typing import Optional

from django.conf import settings
from django.core import signing
from django.http import HttpResponse, HttpResponseNotAllowed
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .models import NotificationSettings

_SALT = "continuity.email-unsubscribe"

# Account notices: they tell the user about their account (losing a beta spot),
# so they are not opt-out-able and carry no unsubscribe link.
TRANSACTIONAL_EMAIL_IDS = frozenset({"reclaim_warn", "reclaim_final"})


def make_token(user_id: uuid.UUID) -> str:
    return signing.dumps(str(user_id), salt=_SALT, compress=True)


def read_token(token: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(signing.loads(token, salt=_SALT))
    except (signing.BadSignature, ValueError, TypeError):
        return None


def unsubscribe_url(user_id: uuid.UUID) -> str:
    base = getattr(settings, "BACKEND_PUBLIC_URL", "").rstrip("/")
    return f"{base}{reverse('email-unsubscribe')}?t={make_token(user_id)}"


def is_opted_out(user_id: uuid.UUID) -> bool:
    return NotificationSettings.objects.filter(
        user_id=user_id, lifecycle_emails_enabled=False
    ).exists()


def footer(user_id: uuid.UUID, locale: str) -> tuple[str, str, dict[str, str]]:
    """(html, text, headers) to append to a lifecycle email."""
    url = unsubscribe_url(user_id)
    if locale == "es":
        lead, label = "¿No quieres más correos como este?", "Darme de baja"
    else:
        lead, label = "Don't want emails like this?", "Unsubscribe"
    footer_html = (
        '<p style="color:#888;font-size:12px">'
        f'{html.escape(lead)} <a href="{html.escape(url)}">{html.escape(label)}</a></p>'
    )
    footer_text = f"{lead} {label}: {url}"
    headers = {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    return footer_html, footer_text, headers


_COPY = {
    "en": {
        "title": "Unsubscribe",
        "ask": "Stop receiving continuu.it emails about your activity (welcome, reminders when you've been away)?",
        "button": "Unsubscribe",
        "done": "Done. You won't get these emails any more. You can turn them back on in Settings → Notifications.",
        "invalid": "This link isn't valid. You can turn these emails off in Settings → Notifications.",
    },
    "es": {
        "title": "Darse de baja",
        "ask": "¿Dejar de recibir los correos de continuu.it sobre tu actividad (bienvenida, avisos cuando llevas tiempo sin entrar)?",
        "button": "Darme de baja",
        "done": "Listo. Ya no recibirás estos correos. Puedes volver a activarlos en Ajustes → Notificaciones.",
        "invalid": "Este enlace no es válido. Puedes desactivar estos correos en Ajustes → Notificaciones.",
    },
}


def _page(locale: str, message: str, form_token: str = "", status: int = 200) -> HttpResponse:
    c = _COPY[locale]
    form = ""
    if form_token:
        form = (
            '<form method="post">'
            f'<input type="hidden" name="t" value="{html.escape(form_token)}">'
            f'<button type="submit">{html.escape(c["button"])}</button></form>'
        )
    body = (
        f'<!doctype html><html lang="{locale}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex"><title>{html.escape(c["title"])} · continuu.it</title>'
        "<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;"
        "color:#222}button{font:inherit;padding:.6rem 1.2rem;border-radius:.5rem;border:1px solid #222;"
        "background:#fff;cursor:pointer}</style></head><body>"
        f"<h1>{html.escape(c['title'])}</h1><p>{html.escape(message)}</p>{form}</body></html>"
    )
    return HttpResponse(body, status=status)


def _locale_for(user_id: Optional[uuid.UUID]) -> str:
    if user_id is None:
        return "en"
    loc = (
        NotificationSettings.objects.filter(user_id=user_id)
        .values_list("locale", flat=True)
        .first()
        or "en"
    )
    return "es" if str(loc).split("-")[0].lower() == "es" else "en"


@csrf_exempt
def unsubscribe_view(request):
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    # One-click POSTs from mail clients keep the token in the query string.
    token = request.POST.get("t") or request.GET.get("t", "")
    user_id = read_token(token)
    locale = _locale_for(user_id)
    if user_id is None:
        return _page(locale, _COPY[locale]["invalid"], status=400)
    if request.method == "GET":
        return _page(locale, _COPY[locale]["ask"], form_token=token)
    s, _ = NotificationSettings.objects.get_or_create(user_id=user_id)
    if s.lifecycle_emails_enabled:
        s.lifecycle_emails_enabled = False
        s.save(update_fields=["lifecycle_emails_enabled", "updated_at"])
    return _page(locale, _COPY[locale]["done"])

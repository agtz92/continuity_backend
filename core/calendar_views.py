"""Public ICS calendar feed endpoint.

Hit by calendar clients (iCloud/iOS, Google, Outlook) when they refresh a
subscribed calendar. No auth header travels with those requests, so the secret
``token`` in the path is the credential. The token is high-entropy and rotatable
from the plugin UI.
"""

from __future__ import annotations

import logging

from django.http import HttpResponse, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .services import calendar_feed

logger = logging.getLogger(__name__)


@csrf_exempt
@require_GET
def ics_feed(request, token: str):
    user_id = calendar_feed.user_for_token(token)
    if user_id is None:
        return HttpResponseNotFound("Unknown calendar feed")
    try:
        body = calendar_feed.build_ics(user_id)
    except Exception:
        logger.exception("Failed to build ICS feed")
        return HttpResponse("Failed to build calendar", status=500)
    resp = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = 'inline; filename="continuity.ics"'
    # Let clients cache briefly; they each poll on their own cadence anyway.
    resp["Cache-Control"] = "private, max-age=300"
    return resp

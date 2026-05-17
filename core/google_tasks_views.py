"""Django view for the Google Tasks plugin OAuth callback.

The authorization URL is built via GraphQL mutation (``googleTasksAuthUrl``)
so the JWT travels in the Authorization header. The callback below is hit by
Google's redirect — a server-to-browser redirect with no auth header — so it
relies on the HMAC-signed ``state`` parameter for user identity.
"""

from __future__ import annotations

import logging
import urllib.parse

from django.conf import settings
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .services import google_tasks as gt_svc

logger = logging.getLogger(__name__)


@csrf_exempt
@require_GET
def oauth_callback(request):
    error = request.GET.get("error")
    state = request.GET.get("state", "")
    code = request.GET.get("code", "")

    frontend_base = settings.GOOGLE_OAUTH_FRONTEND_BASE_URL.rstrip("/")

    if error:
        return HttpResponseRedirect(
            f"{frontend_base}/settings/plugins/google-tasks"
            f"?google_error={urllib.parse.quote(error)}"
        )
    if not code or not state:
        return HttpResponseBadRequest("Missing code or state")

    try:
        _user_id, return_to = gt_svc.exchange_code_and_store(code, state)
    except gt_svc.InvalidStateError as e:
        logger.warning("Google OAuth state rejected: %s", e)
        return HttpResponseBadRequest("Invalid state")
    except gt_svc.GoogleTasksError as e:
        logger.exception("Google OAuth callback failed")
        return HttpResponseRedirect(
            f"{frontend_base}/settings/plugins/google-tasks"
            f"?google_error={urllib.parse.quote(str(e))}"
        )

    if not return_to.startswith("/"):
        return_to = "/settings/plugins/google-tasks"

    return HttpResponseRedirect(
        f"{frontend_base}{return_to}?google_connected=1"
    )

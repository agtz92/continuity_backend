"""Django view for the Google OAuth callback (Google Tasks / Calendar plugins).

The authorization URL is built via GraphQL mutation (``googleTasksAuthUrl``)
so the JWT travels in the Authorization header. Google's redirect back here
carries no auth header, so this view must NOT store tokens: it can't know who
is sitting at the browser. Trusting the ``uid`` inside ``state`` let anyone
send their own consent link to someone else and capture that person's Google
token (audit 2026-11-05).

So the view only checks the state's signature and hands ``code`` + ``state``
to the frontend page in ``state.ret``. That page, logged in, calls the
``completeGoogleOAuth`` mutation, which exchanges the code only if the
state was issued to the logged-in user.
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

DEFAULT_RETURN = "/settings/plugins/google-tasks"


@csrf_exempt
@require_GET
def oauth_callback(request):
    error = request.GET.get("error")
    state = request.GET.get("state", "")
    code = request.GET.get("code", "")

    frontend_base = settings.GOOGLE_OAUTH_FRONTEND_BASE_URL.rstrip("/")

    if error:
        return HttpResponseRedirect(
            f"{frontend_base}{DEFAULT_RETURN}"
            f"?google_error={urllib.parse.quote(error)}"
        )
    if not code or not state:
        return HttpResponseBadRequest("Missing code or state")

    try:
        return_to = gt_svc.return_path_for_state(state)
    except gt_svc.InvalidStateError as e:
        logger.warning("Google OAuth state rejected: %s", e)
        return HttpResponseBadRequest("Invalid state")

    query = urllib.parse.urlencode({"google_code": code, "google_state": state})
    return HttpResponseRedirect(f"{frontend_base}{return_to}?{query}")

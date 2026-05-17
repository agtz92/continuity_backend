"""Django views for the Google Tasks plugin OAuth dance.

GraphQL handles everything user-facing (list, import, disconnect). These two
endpoints exist only because Google's OAuth flow redirects through the
browser, which can't be modeled as a GraphQL mutation:

  GET /api/google/oauth/start    -> requires a logged-in Continuity user;
                                    redirects them to Google for consent.
  GET /api/google/oauth/callback -> Google redirects here with ?code & ?state;
                                    we swap the code for tokens and bounce
                                    the user back to the frontend.
"""

from __future__ import annotations

import logging
import urllib.parse

from django.conf import settings
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .auth import authenticate_request
from .services import google_tasks as gt_svc

logger = logging.getLogger(__name__)


@csrf_exempt
@require_GET
def oauth_start(request):
    early = authenticate_request(
        request,
        ip_group="google_oauth:ip",
        ip_rate=settings.GRAPHQL_RATE_LIMIT_IP,
        user_group="google_oauth:user",
        user_rate=settings.GRAPHQL_RATE_LIMIT_USER,
        method="GET",
    )
    if early is not None:
        return early

    return_to = request.GET.get("return") or "/settings/plugins/google-tasks"
    if not return_to.startswith("/"):
        # Avoid open redirects — only allow same-origin paths.
        return_to = "/settings/plugins/google-tasks"

    try:
        url = gt_svc.build_authorization_url(request.user_id, return_to)
    except gt_svc.GoogleTasksError as e:
        return JsonResponse({"error": str(e)}, status=500)
    return HttpResponseRedirect(url)


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

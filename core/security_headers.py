"""Content-Security-Policy for every backend response.

Django 5.1 has no built-in CSP, so this middleware sets one. The backend mostly
answers JSON (GraphQL, REST, SSE), where a CSP costs nothing and stops a JSON or
error page from being turned into a document that runs scripts or gets framed.

Two policies:
- ``API_POLICY`` (default): nothing may load except inline styles, which the
  hand-built HTML pages need (email unsubscribe, ``core/notifications/unsubscribe.py``).
  Their forms post to themselves, hence ``form-action 'self'``.
- ``ADMIN_POLICY`` for ``/admin/``: Django admin loads its own CSS/JS/images
  from ``/static/`` (WhiteNoise) and uses inline ``style=`` attributes.

A view that already set its own header keeps it.
"""

API_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

ADMIN_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            policy = ADMIN_POLICY if request.path.startswith("/admin/") else API_POLICY
            response["Content-Security-Policy"] = policy
        return response

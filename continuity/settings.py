import sys
from pathlib import Path
from decouple import config, Csv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="dev-only-insecure-key")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="*", cast=Csv())

SUPABASE_URL = config("SUPABASE_URL", default="").rstrip("/")
SUPABASE_JWT_SECRET = config("SUPABASE_JWT_SECRET", default="")  # legacy HS256 fallback
SUPABASE_SERVICE_ROLE_KEY = config("SUPABASE_SERVICE_ROLE_KEY", default="")  # admin-only

# Resend — product/lifecycle emails (welcome + beta lifecycle). Auth emails
# (confirm/magic-link/reset) stay in Supabase. Empty key = no real sends
# (only dry_run rows are logged).
RESEND_API_KEY = config("RESEND_API_KEY", default="")
EMAIL_FROM = config("EMAIL_FROM", default="Alfredo <alfredo@continuu.it>")

# Google Tasks (plugin: importa tareas desde Google Tasks)
GOOGLE_OAUTH_CLIENT_ID = config("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = config("GOOGLE_OAUTH_CLIENT_SECRET", default="")
GOOGLE_OAUTH_REDIRECT_URI = config("GOOGLE_OAUTH_REDIRECT_URI", default="")
GOOGLE_OAUTH_FRONTEND_BASE_URL = config(
    "GOOGLE_OAUTH_FRONTEND_BASE_URL", default="http://localhost:3000"
)

# Public base URL of THIS backend — used to build the absolute ICS calendar
# feed URL the user subscribes to (iCloud/iOS, Google, Outlook).
BACKEND_PUBLIC_URL = config(
    "BACKEND_PUBLIC_URL", default="http://localhost:8000"
)
# Scopes for the Google Calendar push (plugin). Separate from Google Tasks.
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]
# Incremental auth means the token Google returns may carry MORE scopes than the
# single flow requested (tasks + calendar combined). Relax oauthlib's strict
# scope-equality check so the code exchange doesn't raise on that.
import os as _os  # noqa: E402

_os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Notifications
TELEGRAM_BOT_TOKEN = config("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_BOT_USERNAME = config("TELEGRAM_BOT_USERNAME", default="")
TELEGRAM_WEBHOOK_SECRET = config("TELEGRAM_WEBHOOK_SECRET", default="")
TWILIO_ACCOUNT_SID = config("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = config("TWILIO_AUTH_TOKEN", default="")
TWILIO_WHATSAPP_FROM = config("TWILIO_WHATSAPP_FROM", default="")
NOTIFICATIONS_DEFAULT_TIMEZONE = config(
    "NOTIFICATIONS_DEFAULT_TIMEZONE", default="America/Mexico_City"
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "core",
    "core.notifications.apps.NotificationsConfig",
    "core.assistant.apps.AssistantConfig",
    "core.admin_api.apps.AdminApiConfig",
    "core.cms.apps.CmsConfig",
    "core.billing.apps.BillingConfig",
    "core.announcements.apps.AnnouncementsConfig",
    "core.feedback.apps.FeedbackConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "continuity.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "continuity.wsgi.application"

# Tests must NEVER touch the real (Supabase) database. conftest.py sets an
# in-memory SQLite DATABASE_URL, but pytest-django imports this settings module
# before the project conftest runs, so that env override can lose the race and
# DATABASES would get built against Postgres. Detecting pytest here pins SQLite
# regardless of import order — `pytest` is only in sys.modules during test runs
# (never under gunicorn/runserver in production).
if "pytest" in sys.modules:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    _DATABASE_URL = config("DATABASE_URL", default="sqlite:///db.sqlite3")
    DATABASES = {
        "default": dj_database_url.config(
            default=_DATABASE_URL,
            conn_max_age=600,
            ssl_require=_DATABASE_URL.startswith("postgres") and not DEBUG,
        )
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

# Allow the custom client-attribution header (web/mobile) through CORS preflight.
# Without this, browser requests carrying `X-Continuity-Client` would be blocked
# cross-origin. See core/services/interactions.py + docs/admin-metrics/INTERACTIONS.md.
from corsheaders.defaults import default_headers as _cors_default_headers

CORS_ALLOW_HEADERS = (*_cors_default_headers, "x-continuity-client")

CSRF_TRUSTED_ORIGINS = [o for o in CORS_ALLOWED_ORIGINS if o.startswith("http")]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ratelimit",
    }
}

GRAPHQL_RATE_LIMIT_USER = config("GRAPHQL_RATE_LIMIT_USER", default="120/m")
GRAPHQL_RATE_LIMIT_IP = config("GRAPHQL_RATE_LIMIT_IP", default="300/m")

# MCP connector (/mcp/) — protects our infra (Postgres/compute), not an AI bill,
# since the model runs on the user's Claude. See docs/mcp-connector/PLAN.md §2.
MCP_RATE_LIMIT_USER = config("MCP_RATE_LIMIT_USER", default="120/m")
MCP_RATE_LIMIT_IP = config("MCP_RATE_LIMIT_IP", default="300/m")
# Per-plan user rate for the connector (higher plans = more throughput).
# Unknown plans fall back to MCP_RATE_LIMIT_USER.
MCP_RATE_LIMIT_BY_PLAN = {
    "free": config("MCP_RATE_LIMIT_FREE", default="30/m"),
    "pro": config("MCP_RATE_LIMIT_PRO", default="120/m"),
    "studio": config("MCP_RATE_LIMIT_STUDIO", default="300/m"),
    "admin": config("MCP_RATE_LIMIT_ADMIN", default="600/m"),
}

# MCP OAuth 2.1 (Fase 1). The consent page lives in the frontend; access tokens
# are JWTs signed with our own key (sub = Supabase UUID). See PLAN.md §4.2.
FRONTEND_BASE_URL = config("FRONTEND_BASE_URL", default=GOOGLE_OAUTH_FRONTEND_BASE_URL)
MCP_OAUTH_SIGNING_KEY = config("MCP_OAUTH_SIGNING_KEY", default=SECRET_KEY)
MCP_OAUTH_ACCESS_TTL = config("MCP_OAUTH_ACCESS_TTL", default=3600, cast=int)
MCP_OAUTH_REFRESH_TTL = config(
    "MCP_OAUTH_REFRESH_TTL", default=60 * 60 * 24 * 30, cast=int
)
MCP_OAUTH_CODE_TTL = config("MCP_OAUTH_CODE_TTL", default=300, cast=int)

# AI assistant
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")
ASSISTANT_MODEL_FAST = config(
    "ASSISTANT_MODEL_FAST", default="claude-haiku-4-5-20251001"
)
ASSISTANT_MODEL_DEEP = config(
    "ASSISTANT_MODEL_DEEP", default="claude-sonnet-4-6"
)
# Max messages per user per day that may use the deep model (Sonnet).
# Once hit, deep-mode requests silently fall back to Haiku. 0 disables
# deep mode entirely.
ASSISTANT_DEEP_DAILY_CAP = config(
    "ASSISTANT_DEEP_DAILY_CAP", default=10, cast=int
)
ASSISTANT_MAX_TOKENS_OUT = config("ASSISTANT_MAX_TOKENS_OUT", default=1024, cast=int)
# The write tier emits long brainstorming plans plus many tool calls in a
# single turn; 4096 still occasionally truncates mid-tool-use on big
# project brainstorms. 8192 gives comfortable headroom so paid tiers
# (pro/studio/admin) virtually never hit `max_tokens`.
ASSISTANT_MAX_TOKENS_OUT_WRITE = config(
    "ASSISTANT_MAX_TOKENS_OUT_WRITE", default=8192, cast=int
)
ASSISTANT_MAX_TOOL_ITERATIONS = config(
    "ASSISTANT_MAX_TOOL_ITERATIONS", default=6, cast=int
)
# The write tier (pro/admin) chains more tools — brainstorming a project
# means create_project followed by many create_task calls — so it needs a
# higher ceiling than the read-only tier.
ASSISTANT_MAX_TOOL_ITERATIONS_WRITE = config(
    "ASSISTANT_MAX_TOOL_ITERATIONS_WRITE", default=16, cast=int
)
ASSISTANT_MAX_INPUT_TOKENS = config(
    "ASSISTANT_MAX_INPUT_TOKENS", default=8000, cast=int
)
ASSISTANT_MAX_HISTORY_MESSAGES = config(
    "ASSISTANT_MAX_HISTORY_MESSAGES", default=12, cast=int
)
ASSISTANT_MAX_INPUT_CHARS = config(
    "ASSISTANT_MAX_INPUT_CHARS", default=4000, cast=int
)
ASSISTANT_RATE_LIMIT_USER = config(
    "ASSISTANT_RATE_LIMIT_USER", default="30/m"
)
ASSISTANT_RATE_LIMIT_BURST = config(
    "ASSISTANT_RATE_LIMIT_BURST", default="5/10s"
)
ASSISTANT_RATE_LIMIT_IP = config("ASSISTANT_RATE_LIMIT_IP", default="60/m")

# Stripe billing
STRIPE_SECRET_KEY = config("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = config("STRIPE_WEBHOOK_SECRET", default="")
STRIPE_PRICE_PRO_MONTHLY = config("STRIPE_PRICE_PRO_MONTHLY", default="")
STRIPE_PRICE_PRO_ANNUAL = config("STRIPE_PRICE_PRO_ANNUAL", default="")
STRIPE_PRICE_STUDIO_MONTHLY = config("STRIPE_PRICE_STUDIO_MONTHLY", default="")
STRIPE_PRICE_STUDIO_ANNUAL = config("STRIPE_PRICE_STUDIO_ANNUAL", default="")
# Monetary amounts (integer cents) for the prices above. Used by the admin
# billing overview to estimate MRR/ARR without round-tripping to Stripe. Keep
# these in sync with Stripe Dashboard → Product catalog → Prices.
STRIPE_PRICE_PRO_MONTHLY_AMOUNT_CENTS = config(
    "STRIPE_PRICE_PRO_MONTHLY_AMOUNT_CENTS", default=0, cast=int
)
STRIPE_PRICE_PRO_ANNUAL_AMOUNT_CENTS = config(
    "STRIPE_PRICE_PRO_ANNUAL_AMOUNT_CENTS", default=0, cast=int
)
STRIPE_PRICE_STUDIO_MONTHLY_AMOUNT_CENTS = config(
    "STRIPE_PRICE_STUDIO_MONTHLY_AMOUNT_CENTS", default=0, cast=int
)
STRIPE_PRICE_STUDIO_ANNUAL_AMOUNT_CENTS = config(
    "STRIPE_PRICE_STUDIO_ANNUAL_AMOUNT_CENTS", default=0, cast=int
)
STRIPE_CURRENCY = config("STRIPE_CURRENCY", default="usd")
# Where success/cancel/portal redirects send the user back.
BILLING_FRONTEND_BASE_URL = config(
    "BILLING_FRONTEND_BASE_URL", default="http://localhost:3000"
)
# Retention coupons (Stripe Dashboard → Products → Coupons). The cancellation
# flow maps the user's reason to one of these. Leave empty to disable the
# offer step for that bracket.
STRIPE_COUPON_RETENTION_30_3M = config("STRIPE_COUPON_RETENTION_30_3M", default="")
STRIPE_COUPON_RETENTION_25_3M = config("STRIPE_COUPON_RETENTION_25_3M", default="")
STRIPE_COUPON_RETENTION_20_3M = config("STRIPE_COUPON_RETENTION_20_3M", default="")

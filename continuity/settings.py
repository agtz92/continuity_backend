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

# Google Tasks (plugin: importa tareas desde Google Tasks)
GOOGLE_OAUTH_CLIENT_ID = config("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = config("GOOGLE_OAUTH_CLIENT_SECRET", default="")
GOOGLE_OAUTH_REDIRECT_URI = config("GOOGLE_OAUTH_REDIRECT_URI", default="")
GOOGLE_OAUTH_FRONTEND_BASE_URL = config(
    "GOOGLE_OAUTH_FRONTEND_BASE_URL", default="http://localhost:3000"
)

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

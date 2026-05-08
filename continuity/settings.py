from pathlib import Path
from decouple import config, Csv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="dev-only-insecure-key")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)

# Production hosts that should ALWAYS be allowed regardless of what the
# DJANGO_ALLOWED_HOSTS env var contains. The leading dot covers the apex
# (`continuu.it`) and any subdomain (e.g. `www.`, `api.`).
_BASELINE_ALLOWED_HOSTS = [".continuu.it"]
ALLOWED_HOSTS = list(
    dict.fromkeys(
        config("DJANGO_ALLOWED_HOSTS", default="*", cast=Csv())
        + _BASELINE_ALLOWED_HOSTS
    )
)

SUPABASE_URL = config("SUPABASE_URL", default="").rstrip("/")
SUPABASE_JWT_SECRET = config("SUPABASE_JWT_SECRET", default="")  # legacy HS256 fallback

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "core",
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

# Production frontends that should ALWAYS be allowed in CORS regardless
# of what the CORS_ALLOWED_ORIGINS env var contains. Both apex and www
# variants are listed so neither one can drop off accidentally.
_BASELINE_CORS_ORIGINS = [
    "https://www.continuu.it",
    "https://continuu.it",
]
CORS_ALLOWED_ORIGINS = list(
    dict.fromkeys(
        config("CORS_ALLOWED_ORIGINS", default="http://localhost:3000", cast=Csv())
        + _BASELINE_CORS_ORIGINS
    )
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

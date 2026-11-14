"""
Django settings for Maison Tisane.

Every secret is read from the environment. Nothing confidential is written here.
Local development reads a .env file (never committed); the host supplies real
environment variables, which .env must never override.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# override=False matters: on Render the real environment variables win, even if a
# stray .env ever reached the image.
load_dotenv(BASE_DIR / ".env", override=False)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str) -> list[str]:
    raw = os.environ.get(name) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

DEBUG = (os.environ.get("DEBUG") or "").strip() == "1"

# A development fallback key keeps a fresh clone runnable. In production an
# absent SECRET_KEY is a hard error rather than a silent weak default.
SECRET_KEY = os.environ.get("SECRET_KEY") or ""
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-local-development-only-do-not-deploy"
    else:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "SECRET_KEY is not set. Set it in the host environment before starting "
            "with DEBUG off. Generate one with: "
            'python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"'
        )

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
if DEBUG:
    # Lesson from a previous build: a local .env listing only the production host
    # made every local request a DisallowedHost. In debug, localhost always works.
    for host in ("localhost", "127.0.0.1", "[::1]", "testserver"):
        if host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(host)

# Vercel deployment compatibility
if os.environ.get("VERCEL") or os.environ.get("VERCEL_URL"):
    for v_host in (".vercel.app", "localhost", "127.0.0.1"):
        if v_host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(v_host)
    v_url = os.environ.get("VERCEL_URL")
    if v_url and v_url not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(v_url)

if not ALLOWED_HOSTS:
    raise RuntimeError(
        "ALLOWED_HOSTS is empty. Set it to your hostname, without the scheme, "
        "for example: ALLOWED_HOSTS=maison-tisane.onrender.com"
    )

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if os.environ.get("VERCEL") or os.environ.get("VERCEL_URL"):
    if "https://*.vercel.app" not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")
    v_url = os.environ.get("VERCEL_URL")
    if v_url and f"https://{v_url}" not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(f"https://{v_url}")

SITE_URL = (os.environ.get("SITE_URL") or "http://localhost:8000").rstrip("/")

# Bumping this invalidates every service worker cache.
APP_VERSION = os.environ.get("APP_VERSION") or "1.0.0"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    # Request logging sits outermost so it sees every response, including those
    # produced by the middleware below it.
    "core.middleware.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "maison.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context.site",
            ],
        },
    },
]

WSGI_APPLICATION = "maison.wsgi.application"

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

# `or` rather than dj_database_url.config(): an empty DATABASE_URL= line in .env
# is a string, which config() accepted and turned into a dummy backend. This
# reads an empty value as "no value" and falls back to SQLite.
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
if not DATABASE_URL:
    if os.environ.get("VERCEL"):
        import shutil
        tmp_db = "/tmp/db.sqlite3"
        orig_db = BASE_DIR / "db.sqlite3"
        if not os.path.exists(tmp_db) and os.path.exists(orig_db):
            try:
                shutil.copyfile(orig_db, tmp_db)
            except Exception:
                pass
        DATABASE_URL = f"sqlite:///{tmp_db}"
    else:
        DATABASE_URL = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"

# ssl_require only when the URL is a real Postgres URL and NOT a Render internal
# host (dpg-*), which uses private networking without TLS.
_is_postgres = DATABASE_URL.startswith("postgres")
_is_render_internal = "dpg-" in DATABASE_URL
DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=_is_postgres and not _is_render_internal,
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# External API timeout (used for Gemini, MongoDB, Open-Meteo)
# --------------------------------------------------------------------------

EXTERNAL_API_TIMEOUT = float(os.environ.get("EXTERNAL_API_TIMEOUT") or "3")

# --------------------------------------------------------------------------
# MongoDB (chat logs, feedback, users, and user_events)
# --------------------------------------------------------------------------

MONGODB_URI = os.environ.get("MONGODB_URI") or ""
MONGODB_DB = os.environ.get("MONGODB_DB") or "maison"
# Derived from EXTERNAL_API_TIMEOUT so one setting controls all external
# service timeouts.
MONGODB_TIMEOUT_MS = int(EXTERNAL_API_TIMEOUT * 1000)
# After a failure, skip Mongo entirely for this many seconds so a dead database
# never adds latency to a request.
MONGODB_BREAKER_SECONDS = int(os.environ.get("MONGODB_BREAKER_SECONDS") or "30")

# --------------------------------------------------------------------------
# Assistant and third-party calls
# --------------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or ""
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash"
GEMINI_TIMEOUT = EXTERNAL_API_TIMEOUT

TICKET_API_TOKEN = os.environ.get("TICKET_API_TOKEN") or ""

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 9}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/accounts/"
LOGOUT_REDIRECT_URL = "/"

# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static files
# --------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Compressed, not Manifest: a manifest miss raises during template
        # rendering, which would take down the 500 page itself.
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

WHITENOISE_MAX_AGE = 31536000 if not DEBUG else 0

# --------------------------------------------------------------------------
# Cache (used for rate limiting and the weather cache)
# --------------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "maison-default",
        "TIMEOUT": 300,
    }
}

# --------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------

# Render terminates TLS at its proxy, so trust its forwarded scheme header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

FORCE_HTTPS = (os.environ.get("FORCE_HTTPS") or "").strip() == "1"
SECURE_SSL_REDIRECT = FORCE_HTTPS
SESSION_COOKIE_SECURE = FORCE_HTTPS or (not DEBUG)
CSRF_COOKIE_SECURE = FORCE_HTTPS or (not DEBUG)

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

if FORCE_HTTPS or not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

CSRF_FAILURE_VIEW = "core.views.csrf_failure"

# Django masks settings named *_KEY, *_SECRET, *_PASSWORD and so on, but not
# *_URI. A previous build leaked the MongoDB password through the debug page.
DEFAULT_EXCEPTION_REPORTER_FILTER = "core.errors.WideExceptionReporterFilter"

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain",
        },
    },
    "loggers": {
        # One line per request, written by core.middleware.RequestLogMiddleware.
        "requests": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "maison": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}

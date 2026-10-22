"""Django settings for Blueprint to CAD.

Every deployment-specific value comes from the environment. Development and
tests fall back to SQLite, an in-process cache and a local outbox directory so
the API can run without Docker.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent.parent


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None or value == "" else int(value)


def env_list(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


TESTING = "pytest" in sys.modules or env_bool("DJANGO_TESTING")
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set")

PRODUCT_NAME = env("PRODUCT_NAME", "Blueprint to CAD")
APP_VERSION = env("APP_VERSION", "0.1.0")
GIT_SHA = env("GIT_SHA", "dev")

# Public origin as seen by browsers, e.g. https://3d.8westit.com
PUBLIC_URL = (env("PUBLIC_URL", "http://localhost:5173") or "").rstrip("/")
_public = urlparse(PUBLIC_URL)
if _public.scheme not in {"http", "https"} or not _public.hostname:
    raise ImproperlyConfigured("PUBLIC_URL must be an absolute http(s) URL")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS") or [_public.hostname, "localhost", "127.0.0.1"]
if TESTING:
    ALLOWED_HOSTS.append("testserver")
CSRF_TRUSTED_ORIGINS = [PUBLIC_URL, *env_list("CSRF_EXTRA_TRUSTED_ORIGINS")]

# TLS terminates at Cloudflare (or another proxy). The bundled nginx forwards
# X-Forwarded-Proto and an X-Client-IP header it computes itself.
BEHIND_PROXY = env_bool("BEHIND_PROXY", False)
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    ALLAUTH_TRUSTED_CLIENT_IP_HEADER = "X-Client-IP"

COOKIE_SECURE = env_bool("COOKIE_SECURE", _public.scheme == "https")
SESSION_COOKIE_SECURE = COOKIE_SECURE
CSRF_COOKIE_SECURE = COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the SPA reads it to send X-CSRFToken
SESSION_COOKIE_NAME = "bpcad_session"
CSRF_COOKIE_NAME = "bpcad_csrftoken"
SESSION_COOKIE_AGE = env_int("SESSION_DAYS", 7) * 24 * 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "allauth",
    "allauth.account",
    "allauth.headless",
    "allauth.usersessions",
    "core",
    "accounts",
    "orgs",
    "projects",
    "jobs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "allauth.usersessions.middleware.UserSessionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

if env("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("POSTGRES_HOST"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "NAME": env("POSTGRES_DB", "bpcad"),
            "USER": env("POSTGRES_USER", "bpcad"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "var" / "dev.sqlite3",
        }
    }

REDIS_URL = env("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env("CACHE_URL", REDIS_URL.rsplit("/", 1)[0] + "/1"),
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS: list[dict] = []  # no customer passwords: email code login only
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "America/Chicago")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = Path(env("STATIC_ROOT", str(BASE_DIR / "var" / "static")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# --- Private file storage --------------------------------------------------
# FILES_ROOT holds original drawings and generated artifacts. It is never served
# directly; downloads go through an authenticated view (optionally handed to
# nginx with X-Accel-Redirect).
FILES_ROOT = Path(env("FILES_ROOT", str(BASE_DIR / "var" / "files")))
STAGING_ROOT = Path(env("STAGING_ROOT", str(FILES_ROOT / "staging")))
OUTBOX_DIR = Path(env("OUTBOX_DIR", str(BASE_DIR / "var" / "outbox")))
FILE_UPLOAD_TEMP_DIR = str(FILES_ROOT / "tmp")
for _directory in (FILES_ROOT / "tmp", STAGING_ROOT):
    try:
        _directory.mkdir(parents=True, exist_ok=True)
    except OSError:  # read-only image build steps; the volume exists at runtime
        pass
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o640
USE_X_ACCEL_REDIRECT = env_bool("USE_X_ACCEL_REDIRECT", False)
X_ACCEL_PREFIX = "/_protected/"
FEATURE_SPEC_DIR = Path(env("FEATURE_SPEC_DIR", str(REPO_ROOT / "packages" / "feature-spec")))

# Pilot limits (organisation records can lower or raise them per shop).
DEFAULT_MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 25)
DEFAULT_MAX_PDF_PAGES = env_int("MAX_PDF_PAGES", 20)
MAX_IMAGE_PIXELS = env_int("MAX_IMAGE_PIXELS", 150_000_000)
DISK_ALERT_PERCENT = env_int("DISK_ALERT_PERCENT", 85)
QUEUE_ALERT_MINUTES = env_int("QUEUE_ALERT_MINUTES", 30)
BACKUP_ALERT_HOURS = env_int("BACKUP_ALERT_HOURS", 26)
JOB_DEFAULT_DEADLINE_SECONDS = env_int("JOB_DEADLINE_SECONDS", 15 * 60)

# invite_only: accounts are created only by accepting an invitation.
# open: anyone with a verified email may create their own (separate) workspace.
SIGNUP_MODE = env("SIGNUP_MODE", "invite_only")
if SIGNUP_MODE not in {"invite_only", "open"}:
    raise ImproperlyConfigured("SIGNUP_MODE must be invite_only or open")
INVITATION_DAYS = env_int("INVITATION_DAYS", 7)

# --- Email -------------------------------------------------------------------
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", f"{PRODUCT_NAME} <no-reply@{_public.hostname}>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = ""
if env("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST")
    EMAIL_PORT = env_int("EMAIL_PORT", 587)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", EMAIL_PORT == 587)
    EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465)
    EMAIL_TIMEOUT = 20
    EMAIL_DELIVERY = "smtp"
else:
    # No relay configured: messages are written to a private outbox directory
    # readable only from the server (manage.py outbox).
    EMAIL_BACKEND = "core.mail.OutboxEmailBackend"
    EMAIL_DELIVERY = "outbox"
if TESTING:
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# --- django-allauth: email + one-time code, no passwords ----------------------
ACCOUNT_ADAPTER = "accounts.adapter.AccountAdapter"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED = True
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_TIMEOUT = 10 * 60
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_MAX_ATTEMPTS = 3
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_LOGIN_BY_CODE_TIMEOUT = 10 * 60
ACCOUNT_LOGIN_BY_CODE_MAX_ATTEMPTS = 3
ACCOUNT_LOGIN_BY_CODE_SUPPORTS_RESEND = 3
_SIX_DIGITS = {"numeric": True, "length": 6, "dashed": False}
ACCOUNT_LOGIN_BY_CODE_FORMAT = _SIX_DIGITS
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_FORMAT = _SIX_DIGITS
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_CHANGE_EMAIL = True
ACCOUNT_RATE_LIMITS = {
    # one new code per address per minute is the sixty-second resend delay
    "request_login_code": "20/m/ip,1/m/key",
    "login_failed": "10/m/ip,5/5m/key",
    "signup": "10/m/ip",
    "confirm_email": "1/m/key",
}
LOGIN_CODE_RESEND_COOLDOWN_SECONDS = 60
HEADLESS_ONLY = True
HEADLESS_CLIENTS = ("browser",)
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": f"{PUBLIC_URL}/login",
    "account_reset_password": f"{PUBLIC_URL}/login",
    "account_reset_password_from_key": f"{PUBLIC_URL}/login",
    "account_signup": f"{PUBLIC_URL}/login",
}
USERSESSIONS_TRACK_ACTIVITY = True

# --- REST framework -------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
        "user": "1200/min",
        "uploads": env("UPLOAD_RATE", "120/hour"),
        "invitations": "60/hour",
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

# --- Celery -----------------------------------------------------------------------
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 2 * 3600}
CELERY_TASK_ROUTES = {
    "jobs.run_intake": {"queue": "extract"},
    "cad.*": {"queue": "cad"},
}
CELERY_BEAT_SCHEDULE = {
    "reconcile-jobs": {"task": "jobs.reconcile", "schedule": 60.0},
    "check-alerts": {"task": "jobs.check_alerts", "schedule": 15 * 60.0},
    "purge-staging": {"task": "jobs.purge_staging", "schedule": 3600.0},
}
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        # request bodies and auth codes are never logged
        "django.request": {"level": "WARNING"},
        "django.security": {"level": "WARNING"},
    },
}

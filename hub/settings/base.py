"""Base settings — shared by dev and prod. Mockup-first: plain and readable."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("HUB_SECRET_KEY", "dev-only-insecure-key")
DEBUG = False
ALLOWED_HOSTS = os.environ.get("HUB_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "daphne",  # ASGI runserver
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "drf_spectacular",
    "channels",
    "django_otp",
    "django_otp.plugins.otp_totp",
    # otp_static removed 2026-08-03 (round 2): recovery codes live in
    # core.RecoveryCode (sha256-hashed); keeping the plugin would let match_token
    # accept legacy plaintext StaticToken rows as second factors.
    # hub apps (§D4 layout)
    "core",
    "vault",
    "catalog",
    "scanner",
    "provision",
    "deploys",
    "reconcile",
    "providers",
    "monitor",
    "scaling",
    "realtime",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "core.middleware.EnrollmentRequiredMiddleware",  # §6.10 server-side 2FA gate
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "hub.urls"
WSGI_APPLICATION = "hub.wsgi.application"
ASGI_APPLICATION = "hub.asgi.application"

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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "hub"),
        "USER": os.environ.get("POSTGRES_USER", "hub"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sessions (§A1: cookie auth, not JWT; CircleCI-lesson TTLs) ---
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12          # absolute ~12 h
SESSION_SAVE_EVERY_REQUEST = True           # rolling idle timeout base
HUB_SESSION_IDLE_TIMEOUT = 60 * 30          # enforced by middleware in a later slice
CSRF_COOKIE_SAMESITE = "Lax"

# --- DRF + schema (§4.5: serializers are the source of truth) ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",  # browsable API off (§B10)
    ],
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Deploy Hub API",
    "VERSION": "0.0.1",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Redis (§B4: inside the crown-jewel boundary) ---
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
if REDIS_PASSWORD:
    REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:6379/0"
else:
    REDIS_URL = f"redis://{REDIS_HOST}:6379/0"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# --- Celery (§B4: JSON only, never pickle; §6.8 queue split) ---
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_DEFAULT_QUEUE = "deploys"
CELERY_TASK_ROUTES = {
    "monitor.*": {"queue": "probes"},
    "reconcile.*": {"queue": "probes"},
    "scaling.*": {"queue": "control"},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

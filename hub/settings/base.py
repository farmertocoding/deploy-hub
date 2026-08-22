"""Base settings — shared by dev and prod. Mockup-first: plain and readable."""
import os
from pathlib import Path

from celery.schedules import crontab

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
    "wizard",   # §D4 amendment 2026-08-09 — see wizard/__init__.py
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
        # R18-SEC-1: JSONRenderer with the containment class escaped on the way out.
        # Still no browsable API (§B10) — this is that renderer, at the seam where the
        # API's bytes reach a device. `hub/renderers.py` says why it is here rather than
        # in a serializer field.
        "hub.renderers.ContainedJSONRenderer",
    ],
    # Rejected input is an attack signal, not just a 400 (§4.5).
    "EXCEPTION_HANDLER": "core.exception_handlers.audited_exception_handler",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Deploy Hub API",
    "VERSION": "0.0.1",
    "SERVE_INCLUDE_SCHEMA": False,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "wizard.views.pin_patched_answers_required",
    ],
}

# How many proxies sit in front of the Hub (Caddy = 1; Cloudflare + Caddy = 2).
# X-Forwarded-For is caller-controlled, so we count hops from the right rather than
# trusting the leftmost entry — otherwise any client can forge its own source IP.
HUB_TRUSTED_PROXY_HOPS = int(os.environ.get("HUB_TRUSTED_PROXY_HOPS", "0"))

# --- Vault (§6.9 envelope encryption) ---
# Rung ① of the KEK placement ladder: a 32-byte keyfile outside the DB and excluded
# from backups. Rungs ② (YubiKey unlock) and ③ (cloud KMS) are Phase 4 and change only
# VAULT_KEK_BACKEND — ciphertexts and schema are identical (D-006).
VAULT_KEK_BACKEND = os.environ.get("HUB_VAULT_KEK_BACKEND", "local")
VAULT_KEYFILE = os.environ.get("HUB_VAULT_KEYFILE", "/etc/deploy-hub/vault.key")
VAULT_KEYFILE_REQUIRE_MODE = True
# The in-memory test KEK is opt-in and off by default; prod.py hard-fails on it.
VAULT_ALLOW_FAKE_KEK = False

# Fleet reconciler kill switch. Per-site Site.reconcile_enabled still applies when
# this is True. Default on: an unset env must not park the fleet.
HUB_RECONCILE_ENABLED = os.environ.get("HUB_RECONCILE_ENABLED", "true").strip().lower() not in {
    "0", "false", "no", "off",
}

# --- Test plane (§B9 credential wall) ---
# Prod default is False. Tests flip this with override_settings; do not flip it here.
HUB_TEST_MODE = os.environ.get("HUB_TEST_MODE", "").strip().lower() in {
    "1", "true", "yes", "on",
}
HUB_TEST_ZONE_SLUGS = [
    slug.strip()
    for slug in os.environ.get("HUB_TEST_ZONE_SLUGS", "hub-test").split(",")
    if slug.strip()
]

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
    "deploys.tasks.poll_git": {"queue": "probes"},
}
CELERY_BEAT_SCHEDULE = {
    "sweep-stale-deployments": {
        "task": "deploys.tasks.sweep_stale_deployments",
        "schedule": 30.0,
    },
    "poll-git-heads": {
        "task": "deploys.tasks.poll_git",
        "schedule": 120.0,
    },
    "reconcile-tick-all": {
        "task": "reconcile.tasks.tick_all",
        "schedule": 90.0,
    },
    "collect-all-targets": {
        "task": "monitor.tasks.collect_all",
        "schedule": 60.0,
    },
    "detect-missed-drills": {
        "task": "monitor.tasks.detect_missed_drills",
        "schedule": 3600.0,
    },
    "drill-hub-down-monthly": {
        "task": "monitor.tasks.run_hub_down_drill",
        "schedule": 30 * 86400,
        "kwargs": {"duration_s": 1800},
    },
    "drill-reaper-weekly": {
        "task": "monitor.tasks.run_reaper_drill",
        "schedule": 7 * 86400,
    },
    "drill-restore-monthly": {
        "task": "monitor.tasks.run_restore_clean_drill",
        "schedule": 30 * 86400,
    },
    "cf-token-scope-daily": {
        "task": "monitor.tasks.audit_cf_token_scope",
        "schedule": 86400.0,
    },
    "probe-uptime": {
        "task": "monitor.tasks.probe_uptime",
        "schedule": 60.0,
    },
    "cert-expiry-daily": {
        "task": "monitor.tasks.scan_cert_expiry",
        "schedule": 86400.0,
    },
    "alert-repeat-unacked": {
        "task": "monitor.tasks.repeat_unacked",
        "schedule": 300.0,
    },
    "alert-group-p2": {
        "task": "monitor.tasks.deliver_grouped",
        "schedule": 300.0,
    },
    "digest-daily": {
        "task": "monitor.tasks.build_digest",
        "schedule": crontab(hour=8, minute=0),
    },
    "digest-weekly": {
        "task": "monitor.tasks.build_weekly_rollup",
        "schedule": crontab(hour=8, minute=0, day_of_week="monday"),
    },
}
# crontab entries honour TIME_ZONE (digest 08:00 local, weekly Monday).
CELERY_TIMEZONE = TIME_ZONE

# --- Pager (D-036) ---
# Default fake so no test (and no unset-env boot) can page anyone.
HUB_PAGER_BACKEND = os.environ.get("HUB_PAGER_BACKEND", "fake")
HUB_NTFY_BASE_URL = os.environ.get("HUB_NTFY_BASE_URL", "https://ntfy.sh")
HUB_NTFY_TOPIC_P1_REF = os.environ.get("HUB_NTFY_TOPIC_P1_REF", "ntfy-topic-p1")
HUB_NTFY_TOPIC_P2_REF = os.environ.get("HUB_NTFY_TOPIC_P2_REF", "ntfy-topic-p2")
HUB_NTFY_PUBLISHER_HUB_REF = os.environ.get(
    "HUB_NTFY_PUBLISHER_HUB_REF", "ntfy-pub-hub",
)
HUB_NTFY_PUBLISHER_HEALTHCHECKS_REF = os.environ.get(
    "HUB_NTFY_PUBLISHER_HEALTHCHECKS_REF", "ntfy-pub-healthchecks",
)
HUB_NTFY_SUBSCRIBER_REF = os.environ.get("HUB_NTFY_SUBSCRIBER_REF", "ntfy-sub")
# Empty: ntfy account API is not configured; revoke marks the vault ref and
# files a P2 Finding with the one manual step.
HUB_NTFY_ACCOUNT_TOKEN_REF = os.environ.get("HUB_NTFY_ACCOUNT_TOKEN_REF", "")
HUB_PUBLIC_URL = os.environ.get("HUB_PUBLIC_URL", "https://hub.local")

# Email assumption (D-037): Django's mail backend — locmem in tests (the
# test runner swaps EMAIL_BACKEND), env-configured SMTP (HUB_SMTP_*) in
# prod. A failed send files a Finding and never blocks the push path.
HUB_SMTP_HOST = os.environ.get("HUB_SMTP_HOST", "")
HUB_SMTP_PORT = int(os.environ.get("HUB_SMTP_PORT", "587") or "587")
HUB_SMTP_USER = os.environ.get("HUB_SMTP_USER", "")
HUB_SMTP_PASSWORD = os.environ.get("HUB_SMTP_PASSWORD", "")
HUB_SMTP_USE_TLS = os.environ.get("HUB_SMTP_USE_TLS", "true").strip().lower() in {
    "1", "true", "yes", "on",
}
HUB_ALERT_FROM = os.environ.get("HUB_ALERT_FROM", "hub@localhost")
HUB_ALERT_TO = os.environ.get("HUB_ALERT_TO", "ops@localhost")
DEFAULT_FROM_EMAIL = HUB_ALERT_FROM
if HUB_SMTP_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = HUB_SMTP_HOST
    EMAIL_PORT = HUB_SMTP_PORT
    EMAIL_HOST_USER = HUB_SMTP_USER
    EMAIL_HOST_PASSWORD = HUB_SMTP_PASSWORD
    EMAIL_USE_TLS = HUB_SMTP_USE_TLS
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# --- Dead-man + canary (alert-protocol §5, D-039) ---
# A vault owner-id ref (the Target.ssh_key_ref pattern) — never the receiver
# URL itself. The URL is a secret-bearing capability; it lives only in the
# vault and appears in no setting, log, task arg or Finding body.
HUB_DEADMAN_URL_REF = os.environ.get("HUB_DEADMAN_URL_REF", "deadman-ping")
# The known-good external endpoint the canary rule probes BEFORE any
# mass-outage declaration (§5.3). Not a secret.
HUB_CANARY_URL = os.environ.get("HUB_CANARY_URL", "https://one.one.one.one/")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

"""Prod settings — the Hub must pass its own §5 scanner (§B10)."""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

# A missing HUB_SECRET_KEY must be a hard boot failure, never a silent fallback to
# the public dev key (round-1 security finding: session/CSRF forgery otherwise).
if not os.environ.get("HUB_SECRET_KEY"):
    raise ImproperlyConfigured("HUB_SECRET_KEY must be set in prod.")

DEBUG = False

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

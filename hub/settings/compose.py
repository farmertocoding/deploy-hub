"""Compose stack — fail-closed vault/DEBUG, HTTP on 127.0.0.1:8000.

prod.py is the security backstop (no FakeKEK, DEBUG off, HUB_TEST_MODE pinned).
This module only relaxes TLS cookie/redirect flags because docker-compose.yml
publishes Daphne as HTTP on loopback, with no terminator in-tree. Put Caddy or
Tailscale in front and boot hub.settings.prod instead.
"""
import os

# Loopback compose is not an Object-Lock runtime. Prod still requires a bucket.
os.environ.setdefault("HUB_REQUIRE_AUDIT_SHIP", "0")
os.environ.setdefault("HUB_REQUIRE_LIVE_PAGER", "0")
os.environ.setdefault("HUB_PUBLIC_URL", "https://hub.local")

from .prod import *  # noqa: E402,F401,F403

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# The vite SPA (5173) proxies /api to this loopback Daphne. Browser Origin is
# the vite origin; prod CSRF/WebAuthn origins are the public https host.
# Without these, login and webauthn/login/begin 403 Origin checking failed.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
OTP_WEBAUTHN_RP_ID = "localhost"
OTP_WEBAUTHN_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8000",
]

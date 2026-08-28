"""Compose stack — fail-closed vault/DEBUG, HTTP on 127.0.0.1:8000.

prod.py is the security backstop (no FakeKEK, DEBUG off, HUB_TEST_MODE pinned).
This module only relaxes TLS cookie/redirect flags because docker-compose.yml
publishes Daphne as HTTP on loopback, with no terminator in-tree. Put Caddy or
Tailscale in front and boot hub.settings.prod instead.
"""
from .prod import *  # noqa: F401,F403

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

"""Prod settings — the Hub must pass its own §5 scanner (§B10)."""
import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

# A missing HUB_SECRET_KEY must be a hard boot failure, never a silent fallback to
# the public dev key (round-1 security finding: session/CSRF forgery otherwise).
if not os.environ.get("HUB_SECRET_KEY"):
    raise ImproperlyConfigured("HUB_SECRET_KEY must be set in prod.")
if not os.environ.get("HUB_TASK_ENVELOPE_SECRET"):
    raise ImproperlyConfigured("HUB_TASK_ENVELOPE_SECRET must be set in prod.")
if os.environ.get("HUB_TASK_ENVELOPE_SECRET") == os.environ.get("HUB_SECRET_KEY"):
    raise ImproperlyConfigured(
        "HUB_TASK_ENVELOPE_SECRET must differ from HUB_SECRET_KEY."
    )
_require_audit = os.environ.get("HUB_REQUIRE_AUDIT_SHIP", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
if _require_audit and not (os.environ.get("HUB_AUDIT_S3_BUCKET") or "").strip():
    raise ImproperlyConfigured("HUB_AUDIT_S3_BUCKET must be set in prod.")
_require_pager = os.environ.get("HUB_REQUIRE_LIVE_PAGER", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
if _require_pager and os.environ.get("HUB_PAGER_BACKEND", "fake").strip().lower() in {
    "", "fake",
}:
    raise ImproperlyConfigured(
        "HUB_PAGER_BACKEND must be a live pager in prod (not fake).",
    )
if os.environ.get("HUB_VAULT_KEK_BACKEND", "local") == "local":
    _keyfile = os.environ.get("HUB_VAULT_KEYFILE", "/etc/deploy-hub/vault.key")
    _allow_empty = os.environ.get("HUB_ALLOW_EMPTY_VAULT_KEYFILE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if not _keyfile and not _allow_empty:
        raise ImproperlyConfigured(
            "HUB_VAULT_KEYFILE must be set in prod for local KEK.",
        )

DEBUG = False

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# The vault must be backed by a real KEK in prod. A fake KEK here would mean every
# stored secret is encrypted under a key that is literally in the source tree.
if os.environ.get("HUB_VAULT_KEK_BACKEND", "local") == "fake":
    raise ImproperlyConfigured("HUB_VAULT_KEK_BACKEND=fake is not permitted in prod.")
VAULT_ALLOW_FAKE_KEK = False

# Pinned hard, never env-derived (task 18 review follow-up): base.py reads
# HUB_TEST_MODE from the environment, and the §B9 wall plus worker_entry's
# HUB_TEST_DATABASE rebind gate both key off it — two stray env vars on a prod
# box must not be able to repoint a worker's database or open the test plane.
HUB_TEST_MODE = False

# WebAuthn RP ID / origins must be the real Hub hostname. base.py defaults
# localhost for laptop pytest; a prod box inheriting that cannot complete
# a hardware ceremony (H3).
if not (os.environ.get("HUB_PUBLIC_URL") or "").strip():
    raise ImproperlyConfigured("HUB_PUBLIC_URL must be set in prod.")
_raw_public_url = os.environ.get("HUB_PUBLIC_URL").strip()
_public = urlparse(_raw_public_url)
_host = (_public.hostname or "").lower()
if _public.scheme != "https" or _host in {"localhost", "127.0.0.1", "::1"} or not _host:
    raise ImproperlyConfigured(
        "HUB_PUBLIC_URL must be https with a non-loopback host in prod "
        f"(got {_raw_public_url!r})."
    )
OTP_WEBAUTHN_RP_ID = _host
OTP_WEBAUTHN_ALLOWED_ORIGINS = [f"https://{_public.netloc}"]

# D-066: do not default the AWS vault-ref or test-plane allowlists on. The
# operator sets HUB_AWS_CREDENTIALS_REF; empty stays empty. Allowlists stay
# whatever base.py read (default "") — never a baked-in account/region.

# Phase 5.5 C6: do not default INTAKE_URL or PARTNER_API_ENABLED on.

# Email: HUB_SMTP_* is the prod contract (D-037). base.py wires Django's
# SMTP backend when HUB_SMTP_HOST is set; a failed send files a Finding
# and never blocks the push path.

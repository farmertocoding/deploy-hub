"""One scrubber for the nightly failure bundle and the pager (D-036).

Redacts assignment-like SECRET/KEY/TOKEN/PASSWORD/URL values, the vault
test marker, Bearer headers, ntfy.sh/<topic> URLs, vault refs, and bare
high-entropy token/base64-ish runs.
"""
from __future__ import annotations

import re

# Assignment-like NAME=value / name: value where the name carries a secret-ish
# token. Hyphens allowed so CLOUDFLARE_API_TOKEN and similar still match.
_SECRETISH = re.compile(
    r"(?i)\b([A-Za-z0-9_-]*(?:SECRET|KEY|TOKEN|PASSWORD|URL)[A-Za-z0-9_-]*)"
    r"\s*[:=]\s*\S+"
)
_VAULT_MARKER = re.compile(r"VAULT-TEST-PLAINTEXT-MARKER(?:=\S+)?")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_NTFY_URL = re.compile(r"https?://ntfy\.sh/[A-Za-z0-9._~-]+")
_VAULT_REF = re.compile(r"(?i)\bvault:[A-Za-z0-9._:-]+")
# Bare high-entropy run: >=20 chars of token/base64 alphabet carrying at least
# one lowercase, one uppercase AND one digit.
_TOKENISH = re.compile(r"[A-Za-z0-9+/_=.-]{20,}")


def _mixed_class(run):
    return (
        any(c.islower() for c in run)
        and any(c.isupper() for c in run)
        and any(c.isdigit() for c in run)
    )


def scrub(text):
    text = _SECRETISH.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = _VAULT_MARKER.sub("<redacted>", text)
    text = _BEARER.sub("Bearer <redacted>", text)
    text = _NTFY_URL.sub("https://ntfy.sh/<redacted>", text)
    text = _VAULT_REF.sub("vault:<redacted>", text)
    return _TOKENISH.sub(
        lambda m: "<redacted>" if _mixed_class(m.group(0)) else m.group(0), text)

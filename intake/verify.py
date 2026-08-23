"""Ed25519 edge verifier. Fail-closed: missing/invalid signature never authenticates.

Canonical string and headers follow design-note §7 C4. Cheap edge checks only:
5-minute timestamp window plus signature. Nonce cache, idempotency, and quota
are Hub-authoritative. Consumes the shared vector file independently; does not
import Hub modules.
"""
import base64
import hashlib
import json
import time
from pathlib import Path

WINDOW_S = 300
VECTORS_PATH = (
    Path(__file__).resolve().parent.parent
    / "conformance"
    / "fixtures"
    / "partner-signature-vectors.json"
)


class SignatureRejected(Exception):
    status = 401


def load_shared_vectors():
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def canonical_string(method, path, body, timestamp, nonce):
    if not isinstance(body, (bytes, bytearray)):
        body = b"" if body is None else str(body).encode("utf-8")
    digest = hashlib.sha256(bytes(body)).hexdigest()
    return f"{method}\n{path}\n{digest}\n{timestamp}\n{nonce}"


def _unix(now):
    if now is None:
        return int(time.time())
    if hasattr(now, "timestamp"):
        return int(now.timestamp())
    return int(now)


def verify(method, path, body, headers, public_keys, now=None):
    ts = (headers.get("X-Partner-Timestamp") or "").strip()
    nonce = (headers.get("X-Partner-Nonce") or "").strip()
    key_id = (headers.get("X-Partner-Key-Id") or "").strip()
    sig_b64 = (headers.get("X-Partner-Signature") or "").strip()
    if not (ts and nonce and key_id and sig_b64):
        raise SignatureRejected("missing signature headers")
    try:
        ts_i = int(ts)
    except (TypeError, ValueError):
        raise SignatureRejected("invalid timestamp") from None
    if abs(_unix(now) - ts_i) > WINDOW_S:
        raise SignatureRejected("expired")
    key = public_keys.get(key_id)
    if key is None:
        raise SignatureRejected("unknown key")
    try:
        signature = base64.b64decode(sig_b64.encode("ascii"), validate=True)
        message = canonical_string(method, path, body, ts, nonce).encode("ascii")
        key.verify(signature, message)
    except SignatureRejected:
        raise
    except Exception:
        raise SignatureRejected("invalid signature") from None

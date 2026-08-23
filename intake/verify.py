"""Ed25519 edge verifier. Fail-closed: missing/invalid signature never authenticates.

Canonical string and headers follow design-note §7 C4. Timestamp window, nonce
TTL, and the shared vector file land in Task 3.
"""
import base64
import hashlib


class SignatureRejected(Exception):
    status = 401


def canonical_string(method, path, body, timestamp, nonce):
    if not isinstance(body, (bytes, bytearray)):
        body = b"" if body is None else str(body).encode("utf-8")
    digest = hashlib.sha256(bytes(body)).hexdigest()
    return f"{method}\n{path}\n{digest}\n{timestamp}\n{nonce}"


def verify(method, path, body, headers, public_keys):
    ts = (headers.get("X-Partner-Timestamp") or "").strip()
    nonce = (headers.get("X-Partner-Nonce") or "").strip()
    key_id = (headers.get("X-Partner-Key-Id") or "").strip()
    sig_b64 = (headers.get("X-Partner-Signature") or "").strip()
    if not (ts and nonce and key_id and sig_b64):
        raise SignatureRejected("missing signature headers")
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

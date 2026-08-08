"""vault.service — the only code path that encrypts or decrypts secret material.

One path, unit-tested, no hand-rolled crypto anywhere else in the repo (§6.9). A grep
test asserts AESGCM is imported only under vault/.
"""
import hashlib
import os

from django.utils import timezone

from .kek import KEKError, get_backend
from .models import Secret

DEK_BYTES = 32   # AES-256
NONCE_BYTES = 12  # GCM standard


class VaultDecryptError(RuntimeError):
    """Decryption failed: wrong key, tampered row, or a swapped ciphertext.

    Deliberately loud. The rejected django-fernet-encrypted-fields swallowed this and
    returned None, which turns "someone edited the DB" into "the field looks empty".
    """


def _fingerprint(plaintext: bytes) -> str:
    return hashlib.sha256(plaintext).hexdigest()[:16]


def put(*, kind, owner_type, owner_id, plaintext: bytes, actor=None) -> Secret:
    """Encrypt and store. A fresh DEK is generated for every call, always."""
    if not isinstance(plaintext, bytes):
        raise TypeError("plaintext must be bytes — encode explicitly at the call site")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    backend = get_backend()
    dek = os.urandom(DEK_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    aad = f"{kind}|{owner_type}|{owner_id}".encode()
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)

    secret = Secret.objects.create(
        kind=kind,
        owner_type=owner_type,
        owner_id=str(owner_id),
        ciphertext=ciphertext,
        wrapped_dek=backend.wrap(dek),
        nonce=nonce,
        kek_id=backend.kek_id,
        fingerprint=_fingerprint(plaintext),
        created_by=actor,
    )
    _audit("vault-secret-created", secret, actor=actor)
    return secret


def get(secret: Secret, *, actor=None, reason="") -> bytes:
    """Decrypt. Stamps last_used_at and writes an AuditEvent — every *use* is recorded
    (§7.4), which is the whole point of routing reads through a function."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    backend = get_backend()
    try:
        dek = backend.unwrap(bytes(secret.wrapped_dek))
        plaintext = AESGCM(dek).decrypt(
            bytes(secret.nonce), bytes(secret.ciphertext), secret.aad
        )
    except KEKError as exc:
        _audit("vault-secret-decrypt-failed", secret, actor=actor, severity="security")
        raise VaultDecryptError(f"could not unwrap DEK for secret {secret.pk}") from exc
    except Exception as exc:  # InvalidTag — wrong AAD, tampered ciphertext, swapped row
        _audit("vault-secret-decrypt-failed", secret, actor=actor, severity="security")
        raise VaultDecryptError(
            f"authentication failed decrypting secret {secret.pk} — "
            f"the row may have been tampered with"
        ) from exc

    Secret.objects.filter(pk=secret.pk).update(last_used_at=timezone.now())
    _audit("vault-secret-used", secret, actor=actor, reason=reason)
    return plaintext


def rewrap(secret: Secret, *, actor=None) -> Secret:
    """Re-wrap this row's DEK under the currently configured KEK.

    KEK rotation touches only the small wrapped DEKs, never the bulk ciphertext —
    which is the operational reason the envelope pattern exists. Phase 4 uses this to
    migrate rung ① → ③.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401

    backend = get_backend()
    old_backend_id = secret.kek_id
    try:
        dek = get_backend().unwrap(bytes(secret.wrapped_dek))
    except KEKError as exc:
        raise VaultDecryptError(f"cannot rewrap secret {secret.pk}") from exc
    secret.wrapped_dek = backend.wrap(dek)
    secret.kek_id = backend.kek_id
    secret.save(update_fields=["wrapped_dek", "kek_id"])
    _audit("vault-secret-rewrapped", secret, actor=actor, from_kek=old_backend_id,
           to_kek=backend.kek_id)
    return secret


def _audit(action, secret, *, actor=None, severity="info", **detail):
    """Local import keeps vault/ free of an import-time dependency on core/."""
    from core.audit import audit

    return audit(
        action,
        secret,
        actor=actor,
        source="system",
        severity=severity,
        kind=secret.kind,
        owner_type=secret.owner_type,
        owner_id=secret.owner_id,
        fingerprint=secret.fingerprint,
        **detail,
    )

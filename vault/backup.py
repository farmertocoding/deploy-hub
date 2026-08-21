"""Bulk backup sealing. Distinct from the KEK: the backup key is a vault Secret.

Production live form is `pg_dump | age` (age binary). T1 seals with AES-256-GCM
and a clear prefix so tests can see the dump is not plaintext.
"""
import os

PREFIX = b"age-stub:"
NONCE_BYTES = 12
BACKUP_KEY_BYTES = 32
AAD = b"backup-dump"


def seal(plaintext: bytes, key: bytes) -> bytes:
    """AES-256-GCM under the backup key, prefixed so ciphertext is visibly not SQL."""
    if not isinstance(plaintext, bytes):
        raise TypeError("plaintext must be bytes — encode explicitly at the call site")
    if len(key) != BACKUP_KEY_BYTES:
        raise ValueError("backup key must be 32 bytes")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(NONCE_BYTES)
    body = AESGCM(key).encrypt(nonce, plaintext, AAD)
    return PREFIX + nonce + body

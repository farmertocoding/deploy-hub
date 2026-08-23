"""KEK backends (§6.9 key hierarchy).

The KEK wraps per-secret DEKs; it never encrypts bulk data. Rung ① is the local
keyfile (test/dev; does not defeat a stolen Hub disk). Rung ② (YubiKey) may slip.
Rung ③ is KmsKEK: the AWS client lives in providers/kms.py and this class takes
that port without importing boto3 (D-059). Ciphertexts and schema are identical
across rungs (D-006).

Every backend carries a `kek_id`, stored on each Secret row, because rotation needs to
know which KEK wrapped which DEK. Rewrapping without that column would mean trying
every key and treating failure as "wrong key" — indistinguishable from tampering.
"""
import os
import pathlib
import stat

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEK_NONCE_BYTES = 12


class KEKError(RuntimeError):
    """Configuration or unwrap failure. Never swallowed — see vault.service."""


class LocalKeyfileKEK:
    """Rung ①: 32-byte key in a file outside the DB and outside backups.

    Defeats a stolen DB dump and a stolen backup set. Does NOT defeat a full image of
    the Hub disk — that is what rungs ② and ③ are for, and the honest statement of
    this limit belongs here rather than in a design doc nobody greps.
    """

    def __init__(self, path, *, kek_id="local-1", require_mode=True):
        self.path = pathlib.Path(path)
        self.kek_id = kek_id
        self._require_mode = require_mode
        self._key = None

    def check(self):
        """Startup validation. Raises KEKError; callers fail loud (§Phase-0 style)."""
        if not self.path.exists():
            raise KEKError(
                f"vault keyfile missing: {self.path}. Generate one with "
                f"`python manage.py vault_init_keyfile`."
            )
        if self._require_mode:
            mode = stat.S_IMODE(self.path.stat().st_mode)
            if mode != 0o400:
                raise KEKError(
                    f"vault keyfile {self.path} has mode {mode:o}, expected 400"
                )
        raw = self.path.read_bytes()
        if len(raw) != 32:
            raise KEKError(
                f"vault keyfile {self.path} is {len(raw)} bytes, expected exactly 32"
            )
        return True

    def _load(self):
        if self._key is None:
            self.check()
            self._key = self.path.read_bytes()
        return self._key

    def wrap(self, dek: bytes) -> bytes:
        nonce = os.urandom(KEK_NONCE_BYTES)
        return nonce + AESGCM(self._load()).encrypt(nonce, dek, b"kek-wrap")

    def unwrap(self, wrapped: bytes) -> bytes:
        nonce, body = wrapped[:KEK_NONCE_BYTES], wrapped[KEK_NONCE_BYTES:]
        try:
            return AESGCM(self._load()).decrypt(nonce, body, b"kek-wrap")
        except Exception as exc:  # InvalidTag and friends
            raise KEKError("DEK unwrap failed — wrong KEK or tampered row") from exc


class FakeKEK:
    """Tests and local dev only.

    Guarded by an explicit opt-in setting rather than DEBUG: the Django test runner
    forces DEBUG=False, so a DEBUG guard would be simultaneously too strict (tests
    can't use it) and too loose (a prod box with DEBUG accidentally on would accept
    it). prod.py refuses to boot with this enabled.
    """

    def __init__(self, key=None, *, kek_id="fake-1"):
        from django.conf import settings

        if not getattr(settings, "VAULT_ALLOW_FAKE_KEK", False):
            raise KEKError(
                "FakeKEK requires VAULT_ALLOW_FAKE_KEK=True (dev/test settings only)"
            )
        self.kek_id = kek_id
        self._key = key or bytes(range(32))

    def check(self):
        return True

    def wrap(self, dek: bytes) -> bytes:
        nonce = os.urandom(KEK_NONCE_BYTES)
        return nonce + AESGCM(self._key).encrypt(nonce, dek, b"kek-wrap")

    def unwrap(self, wrapped: bytes) -> bytes:
        nonce, body = wrapped[:KEK_NONCE_BYTES], wrapped[KEK_NONCE_BYTES:]
        try:
            return AESGCM(self._key).decrypt(nonce, body, b"kek-wrap")
        except Exception as exc:
            raise KEKError("DEK unwrap failed") from exc


class KmsKEK:
    """Rung ③: wrap DEKs through a KMS port. Never imports boto3 (D-059)."""

    def __init__(self, port, *, kek_id=None):
        self._port = port
        key_id = str(getattr(port, "key_id", "") or "").strip()
        if kek_id is None:
            if not key_id:
                raise KEKError(
                    "VAULT_KEK_BACKEND=kms refuses unless VAULT_KMS_KEY_ID is set"
                )
            kek_id = f"kms:{key_id}"
        self.kek_id = kek_id

    def check(self):
        check = getattr(self._port, "check", None)
        if check is not None:
            check()
        return True

    def wrap(self, dek: bytes) -> bytes:
        try:
            return self._port.encrypt(dek)
        except KEKError:
            raise
        except Exception as exc:
            raise KEKError("DEK wrap failed") from exc

    def unwrap(self, wrapped: bytes) -> bytes:
        try:
            return self._port.decrypt(wrapped)
        except KEKError:
            raise
        except Exception as exc:
            raise KEKError("DEK unwrap failed — wrong KEK or tampered row") from exc


def get_backend():
    """Resolve the configured backend. Import-time-free so settings can change in tests."""
    from django.conf import settings

    configured = getattr(settings, "VAULT_KEK_BACKEND", "local")
    if configured == "fake":
        return FakeKEK()
    if configured == "local":
        path = getattr(settings, "VAULT_KEYFILE", None)
        if not path:
            raise KEKError("VAULT_KEYFILE is not set")
        return LocalKeyfileKEK(
            path, require_mode=getattr(settings, "VAULT_KEYFILE_REQUIRE_MODE", True)
        )
    if configured == "kms":
        key_id = str(getattr(settings, "VAULT_KMS_KEY_ID", "") or "").strip()
        if not key_id:
            raise KEKError(
                "VAULT_KEK_BACKEND=kms refuses unless VAULT_KMS_KEY_ID is set"
            )
        from providers.kms import KmsClient

        return KmsKEK(KmsClient(key_id))
    raise KEKError(f"unknown VAULT_KEK_BACKEND: {configured!r}")


def backend_for_stored_kek_id(kek_id):
    """Backend that wrapped this kek_id. ①→③ rewrap keeps the keyfile on disk."""
    from django.conf import settings

    current = get_backend()
    if kek_id == current.kek_id:
        return current
    if isinstance(kek_id, str) and kek_id.startswith("kms:"):
        from providers.kms import KmsClient

        return KmsKEK(KmsClient(kek_id[len("kms:") :]), kek_id=kek_id)
    if isinstance(kek_id, str) and kek_id.startswith("local"):
        path = getattr(settings, "VAULT_KEYFILE", None)
        if not path:
            raise KEKError("VAULT_KEYFILE is not set")
        return LocalKeyfileKEK(
            path,
            kek_id=kek_id,
            require_mode=getattr(settings, "VAULT_KEYFILE_REQUIRE_MODE", True),
        )
    if isinstance(kek_id, str) and kek_id.startswith("fake"):
        return FakeKEK(kek_id=kek_id)
    raise KEKError(f"no KEK backend for kek_id {kek_id!r}")

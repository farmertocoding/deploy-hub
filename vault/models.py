"""vault: the one place secret material is stored (§6.9).

Design constraints that are load-bearing, each with a test in tests/test_vault.py:

* Fresh DEK per write — DEKs are never rotated, only KEKs are (§6.9, Google KMS
  guidance). Two writes of identical plaintext must differ in ciphertext.
* AAD binds kind+owner, so an attacker with DB write access cannot move a ciphertext
  onto another row and have it decrypt.
* No plaintext accessor on the model. Reading goes through vault.service.get(), which
  audits. A property here would be used, and the audit trail would quietly rot.
* owner is (type, id) strings rather than FKs: vault/ must not import core/ or
  deploys/ models, or the app boundary in §D4 stops meaning anything.
"""
from django.conf import settings
from django.db import models


class Secret(models.Model):
    class Kind(models.TextChoices):
        ENV_BUNDLE = "env_bundle"
        SSH_PRIVATE_KEY = "ssh_private_key"
        TLS_PRIVATE_KEY = "tls_private_key"
        CLOUD_CREDENTIAL = "cloud_credential"
        # nosec B105 — a Kind label naming what a row holds, not a credential.
        API_TOKEN = "api_token"  # nosec B105
        DATABASE_URL = "database_url"
        # nosec B105 — Kind label for the per-site backup key, distinct from the KEK.
        BACKUP_KEY = "backup_key"  # nosec B105

    kind = models.CharField(max_length=32, choices=Kind.choices)
    owner_type = models.CharField(max_length=32)  # 'site' | 'target' | 'project' | ...
    owner_id = models.CharField(max_length=64)

    ciphertext = models.BinaryField()
    wrapped_dek = models.BinaryField()
    nonce = models.BinaryField()
    algo = models.CharField(max_length=32, default="AES-256-GCM")
    kek_id = models.CharField(max_length=64)

    # sha256(plaintext)[:16] — lets the UI say "same key as target X" and lets a
    # rotation confirm the new value differs, without ever decrypting.
    fingerprint = models.CharField(max_length=16, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["owner_type", "owner_id"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind}:{self.owner_type}:{self.owner_id}#{self.fingerprint}"

    def __repr__(self):
        # Explicit: a stray repr() in a traceback or log line must not carry bytes.
        return f"<Secret {self.pk} {self.kind} redacted>"

    @staticmethod
    def build_aad(kind, owner_type, owner_id) -> bytes:
        """Associated data — binds a ciphertext to a row's identity, spelled ONCE.

        R18 folded note. This expression was written three times: here, inline in
        `vault.service.put`, and again in tests/test_vault.py. Drift fails CLOSED — the
        decrypt raises `InvalidTag` and `get` audits it — so this was never a hole; it is
        the one-fact rule, and a fact whose three copies can only be compared by eye is
        one edit from an outage that reads like corruption. `put` now encrypts with the
        same function `Secret.aad` decrypts with, and a test asserts the two agree.

        THE `|` DELIMITER IS NOT ESCAPED, and that is safe TODAY rather than in general:
        `kind` is a `Secret.Kind` choice, `owner_type` is one of a fixed set of strings
        this codebase writes, and `owner_id` is a primary key rendered by `str()`. None of
        them is repo-controlled or user-supplied, so none can carry a `|` and shift the
        boundary between two fields (`a|b` + `c` colliding with `a` + `b|c`). If any of
        the three ever becomes free text, this needs a canonical encoding — length
        prefixes, or a delimiter the field cannot contain — BEFORE that lands, because the
        collision it would open is silent: two different identities producing one AAD,
        which is exactly the cut-and-paste the AAD exists to prevent.
        """
        return f"{kind}|{owner_type}|{owner_id}".encode()

    @property
    def aad(self) -> bytes:
        """This row's associated data. See `build_aad` for the spelling and its limits."""
        return self.build_aad(self.kind, self.owner_type, self.owner_id)

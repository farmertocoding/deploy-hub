"""Vault tests (§6.9 / SEC-69-ENVELOPE-ENCRYPTION).

Each test here corresponds to a property the envelope design claims. The AAD test in
particular is the one that matters: "ciphertexts cannot be swapped between rows" is a
claim about an attacker with DB write access, and the only honest way to hold it is to
perform the swap and watch it fail.
"""
import os
import pathlib
import stat

import pytest
from django.test import override_settings

from vault import service
from vault.kek import KEKError, LocalKeyfileKEK
from vault.models import Secret

pytestmark = pytest.mark.django_db

SECRET_MARKER = b"VAULT-TEST-PLAINTEXT-MARKER-do-not-log"


def _put(**kw):
    defaults = dict(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type="site",
        owner_id="1",
        plaintext=SECRET_MARKER,
    )
    defaults.update(kw)
    return service.put(**defaults)


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_roundtrip():
    secret = _put()
    assert service.get(secret) == SECRET_MARKER


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_fresh_dek_per_write():
    """Identical plaintext, two writes: ciphertext, nonce and wrapped DEK all differ.

    If a DEK were reused, equal ciphertexts would leak equality of secrets across rows.
    """
    a, b = _put(), _put()
    assert bytes(a.ciphertext) != bytes(b.ciphertext)
    assert bytes(a.nonce) != bytes(b.nonce)
    assert bytes(a.wrapped_dek) != bytes(b.wrapped_dek)
    # ... and both still decrypt to the same thing.
    assert service.get(a) == service.get(b) == SECRET_MARKER
    # Fingerprints match — that's how the UI compares without decrypting.
    assert a.fingerprint == b.fingerprint


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_issue_r4_11_dek_is_a_full_256_bit_key():
    """R4-11 WI-6: the requirement says AES-**256**-GCM and nothing pinned the key
    size — setting `vault.service.DEK_BYTES = 16` (AES-128) kept all 22 vault tests
    green, because AES-128-GCM round-trips, authenticates and rejects swaps exactly
    like AES-256-GCM does.

    Measured on the real key material, not just the named constant: the DEK is
    unwrapped back out of the stored row with the configured KEK backend, so a
    downgrade anywhere between `os.urandom(...)` and the cipher is caught.
    """
    from vault.kek import get_backend

    assert service.DEK_BYTES == 32, "the DEK constant must stay AES-256"

    secret = _put()
    dek = get_backend().unwrap(bytes(secret.wrapped_dek))
    assert len(dek) == 32, f"DEK is {len(dek) * 8}-bit, requirement says AES-256"
    # It really is the key this row's ciphertext was encrypted under.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    aad = f"{secret.kind}|{secret.owner_type}|{secret.owner_id}".encode()
    assert AESGCM(dek).decrypt(bytes(secret.nonce), bytes(secret.ciphertext),
                               aad) == SECRET_MARKER


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_plaintext_never_stored():
    secret = _put()
    row = Secret.objects.get(pk=secret.pk)
    for field in (row.ciphertext, row.wrapped_dek, row.nonce):
        assert SECRET_MARKER not in bytes(field)


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_aad_prevents_cut_and_paste_between_rows():
    """The attack: DB write access, copy a secret's crypto columns onto another row.

    Owner differs → AAD differs → GCM authentication fails. Without AAD this would
    silently succeed and hand site 2 the env bundle of site 1.
    """
    victim = _put(owner_id="1")
    attacker_row = _put(owner_id="2", plaintext=b"attacker-placeholder")

    Secret.objects.filter(pk=attacker_row.pk).update(
        ciphertext=bytes(victim.ciphertext),
        wrapped_dek=bytes(victim.wrapped_dek),
        nonce=bytes(victim.nonce),
    )
    moved = Secret.objects.get(pk=attacker_row.pk)
    with pytest.raises(service.VaultDecryptError):
        service.get(moved)


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_aad_prevents_kind_change():
    """Same owner, different kind — e.g. relabelling an env bundle as an SSH key to
    route it somewhere it doesn't belong."""
    secret = _put(kind=Secret.Kind.ENV_BUNDLE)
    Secret.objects.filter(pk=secret.pk).update(kind=Secret.Kind.SSH_PRIVATE_KEY)
    with pytest.raises(service.VaultDecryptError):
        service.get(Secret.objects.get(pk=secret.pk))


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_tampered_ciphertext_raises_loudly():
    """Never returns None, never returns garbage — the named defect in the rejected
    django-fernet-encrypted-fields."""
    secret = _put()
    corrupted = bytearray(bytes(secret.ciphertext))
    corrupted[0] ^= 0xFF
    Secret.objects.filter(pk=secret.pk).update(ciphertext=bytes(corrupted))
    with pytest.raises(service.VaultDecryptError):
        service.get(Secret.objects.get(pk=secret.pk))


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_decrypt_failure_is_audited_as_security():
    from core.models import AuditEvent

    secret = _put()
    Secret.objects.filter(pk=secret.pk).update(kind=Secret.Kind.API_TOKEN)
    with pytest.raises(service.VaultDecryptError):
        service.get(Secret.objects.get(pk=secret.pk))
    event = AuditEvent.objects.filter(action="vault-secret-decrypt-failed").first()
    assert event is not None
    assert event.severity == AuditEvent.Severity.SECURITY


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_use_is_audited_and_stamped():
    from core.models import AuditEvent

    secret = _put()
    service.get(secret, reason="deploy")
    secret.refresh_from_db()
    assert secret.last_used_at is not None
    assert AuditEvent.objects.filter(action="vault-secret-used").exists()


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_audit_detail_never_contains_plaintext():
    from core.models import AuditEvent

    secret = _put()
    service.get(secret)
    for event in AuditEvent.objects.all():
        assert SECRET_MARKER.decode() not in str(event.detail)


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_model_exposes_no_plaintext_accessor():
    """Reads go through service.get() so they are audited. A convenience property on
    the model would be used, and the audit trail would rot within a phase."""
    banned = {"plaintext", "value", "decrypt", "secret_value"}
    assert banned.isdisjoint(dir(Secret))


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_repr_is_redacted():
    secret = _put()
    assert "redacted" in repr(secret)
    assert SECRET_MARKER.decode() not in repr(secret)


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_put_rejects_str_plaintext():
    with pytest.raises(TypeError):
        _put(plaintext="a string, not bytes")


# --- KEK backend (rung ①) ---

@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_local_keyfile_requires_mode_400(tmp_path):
    keyfile = tmp_path / "vault.key"
    keyfile.write_bytes(os.urandom(32))
    keyfile.chmod(0o644)
    with pytest.raises(KEKError, match="mode"):
        LocalKeyfileKEK(keyfile).check()
    keyfile.chmod(0o400)
    assert LocalKeyfileKEK(keyfile).check() is True


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_local_keyfile_rejects_wrong_length(tmp_path):
    keyfile = tmp_path / "vault.key"
    keyfile.write_bytes(os.urandom(16))
    keyfile.chmod(0o400)
    with pytest.raises(KEKError, match="32"):
        LocalKeyfileKEK(keyfile).check()


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_missing_keyfile_names_the_fix(tmp_path):
    with pytest.raises(KEKError, match="vault_init_keyfile"):
        LocalKeyfileKEK(tmp_path / "absent.key").check()


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_real_keyfile_backend_roundtrips(tmp_path):
    keyfile = tmp_path / "vault.key"
    keyfile.write_bytes(os.urandom(32))
    keyfile.chmod(0o400)
    with override_settings(VAULT_KEK_BACKEND="local", VAULT_KEYFILE=str(keyfile)):
        secret = _put()
        assert secret.kek_id == "local-1"
        assert service.get(secret) == SECRET_MARKER


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_wrong_kek_cannot_unwrap(tmp_path):
    """A stolen DB dump without the keyfile is inert — the guarantee the whole
    envelope design exists to provide."""
    first, second = tmp_path / "a.key", tmp_path / "b.key"
    for path in (first, second):
        path.write_bytes(os.urandom(32))
        path.chmod(0o400)

    with override_settings(VAULT_KEK_BACKEND="local", VAULT_KEYFILE=str(first)):
        secret = _put()
    with override_settings(VAULT_KEK_BACKEND="local", VAULT_KEYFILE=str(second)):
        with pytest.raises(service.VaultDecryptError):
            service.get(Secret.objects.get(pk=secret.pk))


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_rewrap_changes_wrapping_not_plaintext(tmp_path):
    """KEK rotation touches the small wrapped DEKs only — the operational reason the
    envelope pattern is worth its complexity."""
    first, second = tmp_path / "a.key", tmp_path / "b.key"
    for path in (first, second):
        path.write_bytes(os.urandom(32))
        path.chmod(0o400)

    with override_settings(VAULT_KEK_BACKEND="local", VAULT_KEYFILE=str(first),
                           VAULT_KEK_ID="local-1"):
        secret = _put()
        original_ciphertext = bytes(secret.ciphertext)
        original_wrapped = bytes(secret.wrapped_dek)
        service.rewrap(secret)

    secret.refresh_from_db()
    assert bytes(secret.ciphertext) == original_ciphertext   # bulk data untouched
    assert bytes(secret.wrapped_dek) != original_wrapped     # wrapping refreshed
    with override_settings(VAULT_KEK_BACKEND="local", VAULT_KEYFILE=str(first)):
        assert service.get(secret) == SECRET_MARKER


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_keyfile_init_command_refuses_to_overwrite(tmp_path):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    keyfile = tmp_path / "vault.key"
    with override_settings(VAULT_KEYFILE=str(keyfile)):
        call_command("vault_init_keyfile")
        assert stat.S_IMODE(keyfile.stat().st_mode) == 0o400
        assert len(keyfile.read_bytes()) == 32
        with pytest.raises(CommandError, match="refusing to overwrite"):
            call_command("vault_init_keyfile")


# --- structural rules ---

@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_aead_primitives_used_only_under_vault():
    """One crypto code path (§6.9). If a second app starts importing AESGCM directly,
    there are two implementations of the same guarantee and only one is tested."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    apps = ["core", "catalog", "scanner", "provision", "deploys", "reconcile",
            "providers", "monitor", "scaling", "realtime", "hub"]
    offenders = []
    for app in apps:
        for py in (repo / app).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            if "AESGCM" in text or "cryptography.hazmat" in text:
                offenders.append(str(py.relative_to(repo)))
    assert offenders == [], f"crypto primitives outside vault/: {offenders}"


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_fake_kek_refused_without_explicit_optin():
    """Regression (build finding, 2026-08-09): the first version guarded FakeKEK on
    DEBUG, which the Django test runner forces to False — simultaneously too strict
    (tests couldn't use it) and too loose (a prod box with DEBUG left on would accept
    a key that is literally in the source tree). The guard is now an explicit setting.
    """
    from vault.kek import FakeKEK

    with override_settings(VAULT_ALLOW_FAKE_KEK=False):
        with pytest.raises(KEKError, match="VAULT_ALLOW_FAKE_KEK"):
            FakeKEK()


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_prod_settings_refuse_fake_kek(monkeypatch):
    """prod.py is the backstop: even if a deployment sets the env var, boot aborts."""
    import importlib

    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "fake")
    with pytest.raises(ImproperlyConfigured, match="not permitted in prod"):
        importlib.reload(importlib.import_module("hub.settings.prod"))

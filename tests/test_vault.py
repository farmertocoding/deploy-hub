"""Vault tests (§6.9 / SEC-69-ENVELOPE-ENCRYPTION).

Each test here corresponds to a property the envelope design claims. The AAD test in
particular is the one that matters: "ciphertexts cannot be swapped between rows" is a
claim about an attacker with DB write access, and the only honest way to hold it is to
perform the swap and watch it fail.
"""
import os
import pathlib
import re
import stat
import types

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
    """Identical plaintext, two writes: the two rows are encrypted under *different
    DEKs* — compared as keys, after unwrapping, not as wrapped bytes.

    R4-11 F-2 correction (2026-08-11). This test used to assert
    `a.wrapped_dek != b.wrapped_dek` and justify it as "if a DEK were reused, equal
    ciphertexts would leak equality of secrets across rows". Both halves were wrong,
    and the docstring was the more dangerous half because it told the next reader the
    clause was covered:

    * `kek.wrap()` prepends a fresh `os.urandom` nonce, so two *identical* DEKs wrap to
      different bytes every time — that assertion could not fail.
    * `service.put()` draws a fresh GCM nonce, so equal plaintexts under a shared DEK
      still produce different ciphertexts. Nonce freshness, not DEK freshness, is what
      stops ciphertext equality from leaking plaintext equality.

    Measured: pinning `dek = b"\\x42" * DEK_BYTES` in `vault/service.py` left all 23
    vault tests green, this one included. What fresh-DEK-per-write actually buys is
    blast radius (one recovered DEK decrypts exactly one row) and DEKs that never need
    rotation because no key is used often enough to approach GCM's nonce budget —
    `deploy-system-plan.md` §6.9. That is a claim about the keys, so the keys are what
    this test compares. Where the key *comes from* is pinned separately by
    `test_issue_r4_11_f2_dek_is_drawn_from_the_csprng` — "different every write" is
    necessary, not sufficient.
    """
    from vault.kek import get_backend

    a, b = _put(), _put()
    backend = get_backend()
    dek_a = backend.unwrap(bytes(a.wrapped_dek))
    dek_b = backend.unwrap(bytes(b.wrapped_dek))
    assert dek_a != dek_b, "both rows are encrypted under the same DEK"
    assert len(dek_a) == len(dek_b) == service.DEK_BYTES

    # Nonce freshness is the property that keeps equal plaintexts from producing equal
    # ciphertexts, and unlike the wrapped-DEK comparison it can genuinely fail (a fixed
    # or counter-reset nonce breaks it), so it stays asserted — on its own terms.
    assert bytes(a.nonce) != bytes(b.nonce)
    assert bytes(a.ciphertext) != bytes(b.ciphertext)

    # ... and both still decrypt to the same thing.
    assert service.get(a) == service.get(b) == SECRET_MARKER
    # Fingerprints match — that's how the UI compares without decrypting.
    assert a.fingerprint == b.fingerprint


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_issue_r4_11_f2_dek_is_drawn_from_the_csprng(monkeypatch):
    """R4-11 F-2: the DEK must come from `os.urandom`, and be the key the row is
    encrypted under.

    Comparing two unwrapped DEKs proves they differ; it cannot prove they are
    *unpredictable*. `dek = random.randbytes(DEK_BYTES)` is fresh per write, differs
    every time, and is a Mersenne Twister draw an attacker who sees a few outputs can
    continue — it kept all 23 vault tests green before this test existed. So the draw
    itself is recorded: `put()` must take exactly two values from the CSPRNG, the DEK
    then the GCM nonce, and the DEK it stored must be the one it drew.

    Note the patch target. `import os` binds the one shared module object, so
    `setattr(service.os, "urandom", ...)` would swap the CSPRNG out from under
    `vault.kek` and Django too for the duration of the test. Replacing *this module's
    reference* to `os` keeps the blast radius at `vault.service`, which is the only
    thing under test here — and `vault/service.py` uses `os` for nothing else.
    """
    from vault.kek import get_backend

    real_urandom = os.urandom
    draws = []

    def recording_urandom(n):
        value = real_urandom(n)
        draws.append((n, value))
        return value

    monkeypatch.setattr(service, "os", types.SimpleNamespace(urandom=recording_urandom))
    secret = _put()

    assert [n for n, _value in draws] == [service.DEK_BYTES, service.NONCE_BYTES], (
        f"put() must draw the DEK ({service.DEK_BYTES} bytes) then the GCM nonce "
        f"({service.NONCE_BYTES} bytes) from os.urandom and nothing else; "
        f"observed draws of {[n for n, _value in draws]} bytes"
    )
    drawn_dek, drawn_nonce = draws[0][1], draws[1][1]
    # The drawn bytes are the material actually used — not a decoy draw beside a DEK
    # that came from somewhere else.
    assert get_backend().unwrap(bytes(secret.wrapped_dek)) == drawn_dek
    assert bytes(secret.nonce) == drawn_nonce


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
            "providers", "monitor", "scaling", "realtime", "hub", "wizard",
            "intake"]
    assert "wizard" in apps, "wizard/ must stay crypto-free; AESGCM belongs under vault/"
    assert "intake" in apps, (
        "intake/ may verify Ed25519; AESGCM/Fernet/KEK belong under vault/"
    )
    intake_ed25519_ok = re.compile(
        r"cryptography\.hazmat\.primitives\.(asymmetric\.ed25519|serialization)\b"
    )
    intake_aead_needles = ("AESGCM", "Fernet", "FakeKEK", "LocalKeyfileKEK")
    offenders = []
    for app in apps:
        for py in (repo / app).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            rel = str(py.relative_to(repo))
            if app == "intake":
                if any(needle in text for needle in intake_aead_needles):
                    offenders.append(rel)
                    continue
                for line in text.splitlines():
                    if "cryptography.hazmat" in line and not intake_ed25519_ok.search(line):
                        offenders.append(rel)
                        break
            elif "AESGCM" in text or "cryptography.hazmat" in text:
                offenders.append(rel)
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
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_AUDIT_S3_BUCKET", "hub-audit-test")
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "fake")
    with pytest.raises(ImproperlyConfigured, match="not permitted in prod"):
        importlib.reload(importlib.import_module("hub.settings.prod"))


# ── R18 folded note: the AAD, spelled once ───────────────────────────────────

def test_issue_r18_the_encrypt_and_decrypt_paths_build_one_aad(db):
    """`put` encrypts under the same associated data `Secret.aad` decrypts with.

    The expression was written three times — in `put`, in the model property, and in this
    file — with nothing comparing them. Drift fails CLOSED (an `InvalidTag` that `get`
    audits as a security event), so this was never a hole; it is the one-fact rule, and
    the failure it would produce reads like ciphertext corruption rather than like a typo
    in a format string, which is the expensive way to find out.

    Asserted against the ROW rather than against a literal: a test carrying its own copy
    of the format string is the third spelling this closes.
    """
    secret = service.put(kind=Secret.Kind.API_TOKEN, owner_type="site",
                               owner_id=7, plaintext=b"round-18-marker")

    assert secret.aad == Secret.build_aad(Secret.Kind.API_TOKEN, "site", "7")
    # …and the ciphertext really is bound to it, which is what makes the equality matter.
    assert service.get(secret) == b"round-18-marker"


def test_issue_r18_an_integer_owner_id_binds_to_the_string_the_row_stores(db):
    """`put` takes `owner_id=7`, the row stores `"7"`, and the secret still decrypts.

    R19-QUAL corrects what this used to claim: there is NO behavioural divergence between
    an int and its string here, because the AAD is built through an f-string and
    `f"{7}"` == `f"{'7'}"`. The `str()` in `put` coerces at the call so the two sites
    visibly build from one value; it is not preventing an int/str mismatch, because the
    f-string never produced one. What this asserts is the honest property — an int
    `owner_id` round-trips — not an averted bug that could not occur."""
    secret = service.put(kind=Secret.Kind.API_TOKEN, owner_type="site",
                         owner_id=7, plaintext=b"int-owner")

    assert secret.owner_id == "7"
    assert service.get(secret) == b"int-owner"
    # The claim, made falsifiable: the string and the int build the identical AAD, so no
    # divergence exists to guard against.
    assert Secret.build_aad(Secret.Kind.API_TOKEN, "site", 7) == \
        Secret.build_aad(Secret.Kind.API_TOKEN, "site", "7")


def test_issue_r19_qual_put_binds_to_build_aad_not_an_inlined_copy(db, monkeypatch):
    """R19-QUAL sentinel (R10-A5 shape). The round-18 pins compare `put`'s output to
    `build_aad` for EQUALITY, which an inlined `f"{kind}|..."` in `put` satisfies just as
    well — re-inlining the format string survives them. This patches `build_aad` and
    proves `put` encrypted under WHATEVER it returns, which only a call can do.

    Decrypts by hand with the sentinel AAD: if `put` used its own copy of the expression,
    the ciphertext would be bound to the real AAD and this `decrypt` would raise
    `InvalidTag`.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from vault.kek import get_backend

    sentinel = b"SENTINEL-AAD-not-the-real-format"
    # `monkeypatch.setattr` restores the STATICMETHOD DESCRIPTOR, not the underlying
    # function — a hand-rolled try/finally that saved `Secret.build_aad` would save the
    # unwrapped function and leave every later `self.build_aad(...)` passing `self` as a
    # fourth argument, which is a state leak into every other vault test.
    monkeypatch.setattr(Secret, "build_aad",
                        staticmethod(lambda kind, owner_type, owner_id: sentinel))
    secret = service.put(kind=Secret.Kind.API_TOKEN, owner_type="site",
                         owner_id="9", plaintext=b"sentinel-marker")
    monkeypatch.undo()
    # Captured AFTER undo, or it is the sentinel too — the real AAD is what the restored
    # function produces.
    real_aad = Secret.build_aad(Secret.Kind.API_TOKEN, "site", "9")
    assert real_aad != sentinel

    dek = get_backend().unwrap(bytes(secret.wrapped_dek))
    # Bound to the sentinel: decrypting under it succeeds…
    assert AESGCM(dek).decrypt(bytes(secret.nonce), bytes(secret.ciphertext),
                               sentinel) == b"sentinel-marker"
    # …and NOT under the real AAD the row would otherwise produce, which is the half that
    # fails if `put` ever stops calling `build_aad`.
    import pytest
    from cryptography.exceptions import InvalidTag

    with pytest.raises(InvalidTag):
        AESGCM(dek).decrypt(bytes(secret.nonce), bytes(secret.ciphertext), real_aad)


def test_issue_r18_the_aad_delimiter_is_documented_where_it_is_built():
    """The `|` is unescaped, and safe today because none of the three fields can contain
    one. That is a property of the CURRENT field types, so it is written down beside the
    expression rather than left for the next reader to re-derive — and this asserts the
    note exists, because a note nobody can find is a note nobody reads."""
    doc = Secret.build_aad.__doc__

    assert "canonical encoding" in doc
    assert "repo-controlled" in doc or "user-supplied" in doc

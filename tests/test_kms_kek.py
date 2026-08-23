"""KmsKEK T1 adapter + DEK cache (D-059 / SEC-A3-KMS-KEK-ADAPTER).

boto3, botocore, and moto must not appear as imports in this file. The AWS
client and the moto 5.x context live in providers/kms.py so the tested client
is the shipped client (the D-034 split).
"""
import os
import pathlib
import re
import stat

import pytest
from django.conf import settings
from django.test import override_settings

from vault import service
from vault.kek import KEKError, LocalKeyfileKEK, get_backend
from vault.models import Secret

pytestmark = [pytest.mark.django_db, pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")]

PLAINTEXT = b"VAULT-TEST-PLAINTEXT-MARKER-do-not-log"
REPO = pathlib.Path(__file__).resolve().parent.parent
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)


def _put(**kw):
    defaults = dict(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type="site",
        owner_id="kms-t1",
        plaintext=PLAINTEXT,
    )
    defaults.update(kw)
    return service.put(**defaults)


@pytest.fixture(autouse=True)
def _reset_dek_cache():
    reset = getattr(service, "reset_dek_cache", None)
    if reset is not None:
        reset()
    yield
    if reset is not None:
        reset()


@pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")
def test_kms_kek_wrap_unwrap_with_moto():
    """A DEK wrapped under moto decrypts to the same bytes. No live AWS.

    What would make this fail: KmsKEK importing boto3 itself, or wrap/unwrap
    going through a second client the tests never drive.
    """
    from providers.kms import KmsClient, create_test_key, mock_aws_kms
    from vault.kek import KmsKEK

    dek = os.urandom(32)
    with mock_aws_kms():
        kek = KmsKEK(KmsClient(create_test_key()))
        wrapped = kek.wrap(dek)
        assert wrapped != dek
        assert kek.unwrap(wrapped) == dek
        assert kek.kek_id.startswith("kms:")


@pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")
def test_kms_backend_refuses_unless_configured():
    """VAULT_KEK_BACKEND=kms is fail-closed until a key id is configured.

    What would make this fail: treating kms as constructible with the default
    empty VAULT_KMS_KEY_ID, which is the fail-open D-059 names.
    """
    with override_settings(VAULT_KEK_BACKEND="kms"):
        with pytest.raises(KEKError, match="VAULT_KMS_KEY_ID"):
            get_backend()


@pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")
def test_kms_backend_refuses_when_key_id_empty():
    """Explicit empty and whitespace are the same refusal, not a boto3 client.

    What would make this fail: `if not key_id` missing a strip, so `" "`
    constructs a client and boto3 talks to AWS.
    """
    for empty in ("", "  ", "\n"):
        with override_settings(VAULT_KEK_BACKEND="kms", VAULT_KMS_KEY_ID=empty):
            with pytest.raises(KEKError, match="VAULT_KMS_KEY_ID"):
                get_backend()


@pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")
def test_keyfile_backend_still_default_in_tests():
    """Keyfile/fake remains the test/dev rung; kms is not the default.

    Rung ① does not defeat a stolen Hub disk: the keyfile lives on that disk
    next to the DB. That limit stays on LocalKeyfileKEK, not in a design doc.

    What would make this fail: prod/base defaulting VAULT_KEK_BACKEND to kms,
    or tests booting a KmsKEK because VAULT_KMS_KEY_ID defaulted to a real id.
    """
    assert settings.VAULT_KEK_BACKEND != "kms"
    assert getattr(settings, "VAULT_KMS_KEY_ID", "") == ""
    assert type(get_backend()).__name__ != "KmsKEK"
    doc = LocalKeyfileKEK.__doc__ or ""
    assert "Does NOT defeat a full image of" in doc
    assert "Hub disk" in doc

    base = (REPO / "hub" / "settings" / "base.py").read_text(encoding="utf-8")
    assert 'os.environ.get("HUB_VAULT_KEK_BACKEND", "local")' in base
    assert 'os.environ.get("HUB_VAULT_KMS_KEY_ID", "")' in base
    prod = (REPO / "hub" / "settings" / "prod.py").read_text(encoding="utf-8")
    assert "kms" not in prod.lower()


@pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")
def test_rewrap_from_local_to_kms_under_moto(tmp_path):
    """①→③: rewrap changes wrapping and kek_id, never the bulk ciphertext.

    What would make this fail: rewrap unwrapping with the *new* KmsKEK, so a
    local-wrapped DEK cannot migrate; or rewriting ciphertext under the KMS
    key instead of wrapping the existing DEK.
    """
    from providers.kms import create_test_key, mock_aws_kms

    keyfile = tmp_path / "vault.key"
    keyfile.write_bytes(os.urandom(32))
    keyfile.chmod(stat.S_IRUSR)  # 0o400

    with override_settings(
        VAULT_KEK_BACKEND="local",
        VAULT_KEYFILE=str(keyfile),
        VAULT_KEYFILE_REQUIRE_MODE=True,
    ):
        secret = _put()
        assert secret.kek_id == "local-1"
        original_ciphertext = bytes(secret.ciphertext)
        original_wrapped = bytes(secret.wrapped_dek)

    with mock_aws_kms():
        key_id = create_test_key()
        with override_settings(
            VAULT_KEK_BACKEND="kms",
            VAULT_KMS_KEY_ID=key_id,
            VAULT_KEYFILE=str(keyfile),
            VAULT_KEYFILE_REQUIRE_MODE=True,
        ):
            service.rewrap(secret)
            secret.refresh_from_db()
            assert secret.kek_id == f"kms:{key_id}"
            assert bytes(secret.ciphertext) == original_ciphertext
            assert bytes(secret.wrapped_dek) != original_wrapped
            assert service.get(secret) == PLAINTEXT


@pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")
def test_dek_cache_survives_kms_blip(monkeypatch):
    """A KMS blip must not fail a get whose DEK is already in process memory.

    Cache key is (secret.pk, kek_id). Unwrap on miss only. Never log the DEK.

    What would make this fail: get() calling unwrap on every read, so a KMS
    blip takes down serving sites that already unwrapped the row.
    """
    from providers.fakes import FakeKms
    from vault.kek import KmsKEK

    port = FakeKms(key_id="alias/hub-test")
    kek = KmsKEK(port)
    monkeypatch.setattr(service, "get_backend", lambda: kek)

    secret = _put()
    service.reset_dek_cache()
    assert service.get(secret) == PLAINTEXT
    assert port.decrypt_calls == 1
    port.down = True
    assert service.get(secret) == PLAINTEXT
    assert port.decrypt_calls == 1


@pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")
def test_vault_and_kms_tests_do_not_import_boto3():
    """vault/ and this module speak the port; boto3/moto stay in providers/kms.py.

    What would make this fail: a convenience `import boto3` in vault.kek or in
    this file, so the tested client is no longer the shipped client.
    """
    offenders = []
    for py in (REPO / "vault").rglob("*.py"):
        if _IMPORT_BOTO.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(REPO)))
    if _IMPORT_BOTO.search(pathlib.Path(__file__).read_text(encoding="utf-8")):
        offenders.append("tests/test_kms_kek.py")
    assert offenders == [], f"boto3/botocore/moto import outside providers/kms.py: {offenders}"

"""AWS KMS client (D-059). The only module that may import boto3 for KMS.

vault.kek.KmsKEK takes this port and never imports boto3. Tests enter
`mock_aws_kms()` (moto 5.x, not LocalStack) instead of importing moto themselves.
Live AWS is a Joseph interrupt — dummy creds inside the T1 helper so a missed
context cannot pick up a real profile.
"""
import os
from contextlib import contextmanager

import boto3


class KmsError(RuntimeError):
    """KMS call failed. Never carries plaintext or DEKs."""


class KmsClient:
    """Encrypt/decrypt port. Constructed by vault.kek.get_backend, not by tests."""

    def __init__(self, key_id, *, client=None, region_name="us-east-1"):
        key_id = str(key_id or "").strip()
        if not key_id:
            raise KmsError("KMS key id is empty")
        self.key_id = key_id
        self._client = client or boto3.client("kms", region_name=region_name)

    def check(self):
        try:
            self._client.describe_key(KeyId=self.key_id)
        except Exception as exc:
            raise KmsError("KMS key is not usable") from exc
        return True

    def encrypt(self, plaintext: bytes) -> bytes:
        try:
            resp = self._client.encrypt(KeyId=self.key_id, Plaintext=plaintext)
        except Exception as exc:
            raise KmsError("KMS encrypt failed") from exc
        return bytes(resp["CiphertextBlob"])

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            resp = self._client.decrypt(CiphertextBlob=ciphertext, KeyId=self.key_id)
        except Exception as exc:
            raise KmsError("KMS decrypt failed") from exc
        return bytes(resp["Plaintext"])


@contextmanager
def mock_aws_kms():
    """T1 moto 5.x context. Dummy creds so boto3 never reaches live AWS."""
    from moto import mock_aws

    dummy = "testing"  # T1 dummy so boto3 cannot pick up a live profile
    pinned = {
        "AWS_ACCESS_KEY_ID": dummy,
        "AWS_SECRET_ACCESS_KEY": dummy,
        "AWS_SESSION_TOKEN": dummy,
        "AWS_SECURITY_TOKEN": dummy,
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
    }
    saved = {name: os.environ.get(name) for name in pinned}
    os.environ.update(pinned)
    try:
        with mock_aws():
            yield
    finally:
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def create_test_key():
    """Allocate a CMK inside mock_aws_kms(). Dummy static creds: never live AWS."""
    dummy = "testing"
    client = boto3.client(
        "kms",
        region_name="us-east-1",
        aws_access_key_id=dummy,
        aws_secret_access_key=dummy,
    )
    return client.create_key(Description="deploy-hub-t1")["KeyMetadata"]["KeyId"]

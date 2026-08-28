"""Append-only audit object store. PutObject only; no delete, no overwrite."""
from django.conf import settings

from core.audit_ship import AuditShipError


class S3AuditStore:
    """Production PutObject adapter. Callers never pass a live bucket in tests."""

    def __init__(
        self,
        *,
        bucket,
        region="us-east-1",
        access_key_id="",
        secret_access_key="",
        object_lock=True,
        versioning=True,
    ):
        self.bucket = bucket
        self.region = region
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.object_lock = bool(object_lock)
        self.versioning = bool(versioning)

    @classmethod
    def from_settings(cls):
        return cls(
            bucket=(getattr(settings, "AUDIT_S3_BUCKET", "") or "").strip(),
            region=(getattr(settings, "AUDIT_S3_REGION", "") or "us-east-1"),
            access_key_id=(getattr(settings, "AUDIT_S3_ACCESS_KEY_ID", "") or ""),
            secret_access_key=(getattr(settings, "AUDIT_S3_SECRET_ACCESS_KEY", "") or ""),
            object_lock=bool(getattr(settings, "AUDIT_S3_OBJECT_LOCK", True)),
            versioning=bool(getattr(settings, "AUDIT_S3_VERSIONING", True)),
        )

    def put(self, key, body):
        if not self.object_lock or not self.versioning:
            raise AuditShipError("object lock required")
        if not self.bucket:
            raise AuditShipError("absent bucket")
        if not self.access_key_id or not self.secret_access_key:
            raise AuditShipError("audit store credentials missing")
        from providers.aws_creds import boto3_client

        client = boto3_client(
            "s3",
            access_key_id=self.access_key_id,
            secret_access_key=self.secret_access_key,
            region_name=self.region,
        )
        client.put_object(Bucket=self.bucket, Key=key, Body=body)

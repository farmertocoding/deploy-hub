"""Signed task envelopes. Workers reauthorize claimed workspace before side effects."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from django.conf import settings
from django.core.cache import cache

from core.audit import audit
from core.models import HudOperation, workspace_of


class EnvelopeError(ValueError):
    """Replay, tamper, or missing authorization."""


def _secret():
    return str(getattr(settings, "HUB_TASK_ENVELOPE_SECRET", "") or settings.SECRET_KEY).encode()


def wrap(*, task, workspace_id, resource_type="", resource_id="", producer="hub", ttl=300):
    issued = int(time.time())
    resource_id = str(resource_id or "")
    body = {
        "task": task,
        "workspace_id": workspace_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "producer": producer,
        "issued_at": issued,
        "expires_at": issued + ttl,
        "nonce": secrets.token_hex(16),
    }
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    body["sig"] = hmac.new(_secret(), payload, hashlib.sha256).hexdigest()
    return body


def verify(envelope):
    if not isinstance(envelope, dict):
        raise EnvelopeError("envelope missing")
    body = dict(envelope)
    sig = body.pop("sig", "")
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    expected = hmac.new(_secret(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise EnvelopeError("tampered envelope")
    now = int(time.time())
    if now > int(body.get("expires_at") or 0) or now < int(body.get("issued_at") or 0) - 30:
        raise EnvelopeError("expired envelope")
    return body


def reauthorize(envelope, *, resource=None, task=None, resource_id=None):
    try:
        body = verify(envelope)
    except EnvelopeError as exc:
        audit("task_envelope_rejected", source="celery", severity="security", reason=str(exc))
        raise
    nonce = body.get("nonce")
    ttl = max(int(body.get("expires_at") or 0) - int(time.time()), 1)
    if not cache.add(f"task-envelope-nonce:{nonce}", 1, timeout=ttl):
        audit("task_envelope_rejected", source="celery", severity="security", reason="replay")
        raise EnvelopeError("replayed envelope")
    if task is not None and body.get("task") != task:
        audit(
            "task_envelope_rejected", source="celery",
            severity="security", reason="task mismatch",
        )
        raise EnvelopeError("task mismatch")
    if resource_id is not None and str(body.get("resource_id") or "") != str(resource_id):
        audit(
            "task_envelope_rejected", source="celery",
            severity="security", reason="resource mismatch",
        )
        raise EnvelopeError("resource mismatch")
    if resource is not None:
        claimed = body.get("workspace_id")
        actual = getattr(resource, "workspace_id", None)
        if actual is None:
            ws = workspace_of(resource)
            actual = getattr(ws, "pk", None)
        if actual != claimed:
            audit(
                "task_envelope_rejected",
                source="celery",
                severity="security",
                reason="workspace mismatch",
                workspace=workspace_of(resource),
            )
            raise EnvelopeError("workspace mismatch")
    return body


def reauthorize_operation(operation_id, envelope):
    operation = HudOperation.objects.select_related("workspace").get(pk=operation_id)
    return reauthorize(envelope, resource=operation), operation

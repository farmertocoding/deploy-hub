"""T1 AWS terminate: instance.terminate + target.delete terminates on success.

instance.terminate is T1 (touch + type-the-name). It is the AWS call and
must not leave status=ready. target.delete on aws_ec2 terminates then
deletes only if terminate succeeded (absent == success). Failure files
kind aws-terminate-failed fingerprint aws-terminate:{target.pk} P1 and
keeps the row. SSH kind is row-delete only. tests/ do not import boto3/moto.
"""
from __future__ import annotations

import inspect
import itertools
import json
import os
import pathlib
import re
import time

import pytest
from django.contrib.auth.models import User

from providers.fakes import FakeCloudProvider

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
HOST = "100.64.0.10"
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)
_ZONES = itertools.count(1)


class RecordingCloud(FakeCloudProvider):
    """Test double: FakeCloudProvider plus call log and terminate failure."""

    _MUTATING = frozenset(
        {"create_instance", "terminate_instance", "ensure_ingress_rules"}
    )

    def __init__(self, *, fail_terminate=False):
        super().__init__()
        self.calls = []
        self.fail_terminate = fail_terminate

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def create_instance(self, spec):
        self.calls.append(("create_instance", spec))
        return super().create_instance(spec)

    def terminate_instance(self, instance_id):
        self.calls.append(("terminate_instance", instance_id))
        if self.fail_terminate:
            raise RuntimeError("terminate failed")
        return super().terminate_instance(instance_id)

    def list_tagged_instances(self, tags):
        self.calls.append(("list_tagged_instances", tags))
        return super().list_tagged_instances(tags)


def _zone(slug=None):
    from core.models import NetworkZone

    n = next(_ZONES)
    slug = slug or f"aws-term-{n}"
    return NetworkZone.objects.create(name=slug, slug=slug)


def _aws_target(*, host=HOST, provider_ref="i-term1", status=None, zone=None):
    from core.models import Target

    return Target.objects.create(
        zone=zone or _zone(),
        kind=Target.Kind.AWS_EC2,
        host=host,
        provider_ref=provider_ref,
        ssh_user="deploy",
        ssh_key_ref="vault-term",
        host_key_fingerprint="SHA256:term",
        lifecycle=Target.Lifecycle.EPHEMERAL,
        status=status or Target.Status.READY,
    )


def _ssh_target(*, host="box-1.example.com"):
    from core.models import Target

    return Target.objects.create(
        zone=_zone(),
        kind=Target.Kind.SSH,
        host=host,
        ssh_user="deploy",
        ssh_key_ref="vault-ssh",
        host_key_fingerprint="SHA256:ssh",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def _make_cred(user, name="passkey"):
    from django_otp_webauthn.models import WebAuthnCredential

    return WebAuthnCredential.objects.create(
        user=user,
        name=name,
        confirmed=True,
        credential_id=os.urandom(16),
        public_key=os.urandom(32),
        aaguid="00000000-0000-0000-0000-000000000000",
        transports=["usb"],
    )


def _login(client, user, password="a-long-dev-password"):
    client.force_login(user)
    session = client.session
    session["_hub_last_activity"] = time.time()
    session.save()


def _patch_webauthn(monkeypatch):
    from django_otp_webauthn.models import WebAuthnCredential

    class FakeHelper:
        def __init__(self, request):
            self.request = request

        def authenticate_begin(self, user=None, require_user_verification=True):
            return (
                {"challenge": "YXV0aGNoYWxs", "rpId": "localhost"},
                {"challenge": "YXV0aGNoYWxs"},
            )

        def authenticate_complete(self, user, state, data):
            qs = WebAuthnCredential.objects.filter(confirmed=True)
            if user is not None:
                qs = qs.filter(user=user)
            return qs.first()

    monkeypatch.setattr(
        WebAuthnCredential,
        "get_webauthn_helper",
        classmethod(lambda cls, request: FakeHelper(request)),
    )


def _touch(client, monkeypatch):
    _patch_webauthn(monkeypatch)
    assert client.post("/api/auth/webauthn/authentication/begin/").status_code == 200
    touch = client.post(
        "/api/auth/webauthn/touch/",
        data=json.dumps({"id": "cred-1", "response": {}}),
        content_type="application/json",
    )
    assert touch.status_code == 200, touch.content


def _t1_user(client):
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    _login(client, user)
    return user


def _inject_provider(monkeypatch, provider):
    monkeypatch.setattr(
        "provision.aws_enroll._cloud_provider",
        lambda **kwargs: provider,
    )


def _terminate_url(target):
    return f"/api/v1/targets/{target.pk}/terminate/"


def _delete_url(target):
    return f"/api/v1/targets/{target.pk}/delete/"


# ── T1 HTTP ──────────────────────────────────────────────────────────────────


@pytest.mark.req("AWS-INSTANCE-T1")
def test_instance_terminate_is_t1():
    """instance.terminate is T1 Terminate target: RequireRecentTouch HTTP.

    What would make this fail: a T2/T3 row, hanging the view off /api/auth/,
    or leaving T1_HTTP unregistered so the Task 2 pin 404s the wrong slug.
    """
    from django.urls import resolve

    from core.actions import ACTION_TIERS
    from core.permissions import RequireRecentTouch
    from core.views import InstanceTerminateView
    from tests.test_webauthn_t1 import T1_HTTP

    row = next(r for r in ACTION_TIERS if r["id"] == "instance.terminate")
    assert row["tier"] == "T1"
    assert row["label"] == "Terminate target"
    assert "instance" not in row["label"].lower()

    template = T1_HTTP["instance.terminate"]
    assert template == "/api/v1/targets/{pk}/terminate/"
    match = resolve(template.format(pk=1))
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is InstanceTerminateView
    assert RequireRecentTouch in view_cls.permission_classes
    source = inspect.getsource(InstanceTerminateView)
    assert "InstanceTerminateSerializer" in source
    assert "request.data.get" not in source
    assert "confirm_name" in source

    core_urls = (REPO / "core" / "urls.py").read_text(encoding="utf-8")
    assert "terminate" not in core_urls


@pytest.mark.req("AWS-INSTANCE-T1")
def test_instance_terminate_refuses_without_recent_touch(client, monkeypatch):
    """Two passkeys are not enough: no recent WebAuthn touch → 403, still READY.

    What would make this fail: terminate running on a stolen session that never
    touched a security key.
    """
    from core.models import Target

    _t1_user(client)
    provider = RecordingCloud()
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"])
    _inject_provider(monkeypatch, provider)

    response = client.post(
        _terminate_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 403, response.content
    assert "touch" in response.json()["detail"].lower()
    target.refresh_from_db()
    assert Target.objects.filter(pk=target.pk).exists()
    assert target.status == Target.Status.READY
    assert "hardware_touch_at" not in client.session
    assert not any(c[0] == "terminate_instance" for c in provider.calls)


@pytest.mark.req("AWS-INSTANCE-T1")
def test_instance_terminate_requires_type_the_name(client, monkeypatch):
    """Hardware touch without typing the target host still refuses.

    What would make this fail: confirm_name ignored so any string terminates.
    """
    from core.models import Target

    _t1_user(client)
    _touch(client, monkeypatch)
    provider = RecordingCloud()
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"])
    _inject_provider(monkeypatch, provider)

    wrong = client.post(
        _terminate_url(target),
        data=json.dumps({"confirm_name": "wrong-host"}),
        content_type="application/json",
    )
    assert wrong.status_code == 400, wrong.content
    target.refresh_from_db()
    assert Target.objects.filter(pk=target.pk).exists()
    assert target.status == Target.Status.READY
    assert not any(c[0] == "terminate_instance" for c in provider.calls)

    ok = client.post(
        _terminate_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert ok.status_code == 204, ok.content
    target.refresh_from_db()
    assert Target.objects.filter(pk=target.pk).exists()
    assert target.status != Target.Status.READY
    assert any(c[0] == "terminate_instance" for c in provider.calls)


@pytest.mark.req("AWS-INSTANCE-T1")
def test_totp_does_not_satisfy_instance_terminate(client):
    """A TOTP login of a two-passkey operator still cannot satisfy T1.

    What would make this fail: TOTP writing hardware_touch_at, or terminate
    treating an OTP session as a recent touch.
    """
    from django_otp.oath import TOTP
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import Target

    user = User.objects.create_user("joseph", password="a-long-dev-password")
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    code = format(totp.token(), "06d")

    login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph",
            "password": "a-long-dev-password",
            "otp_code": code,
        }),
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    assert "hardware_touch_at" not in client.session

    target = _aws_target()
    response = client.post(
        _terminate_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 403
    assert "hardware_touch_at" not in client.session
    target.refresh_from_db()
    assert Target.objects.filter(pk=target.pk).exists()
    assert target.status == Target.Status.READY


@pytest.mark.req("AWS-INSTANCE-T1")
def test_terminate_run_twice_zero_mutating_calls():
    """Second pass records zero mutating provider calls (D-018).

    What would make this fail: TerminateInstances again after the Target is
    already decommissioned.
    """
    from provision.aws_enroll import terminate_aws_target

    provider = RecordingCloud()
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"])
    first = terminate_aws_target(target, provider=provider)
    assert provider.mutating_calls(), "first terminate must call terminate_instance"
    assert any(c[0] == "terminate_instance" for c in provider.mutating_calls())
    provider.calls.clear()
    second = terminate_aws_target(target, provider=provider)
    assert provider.mutating_calls() == []
    assert first.pk == second.pk


@pytest.mark.req("AWS-INSTANCE-T1")
def test_target_delete_on_aws_ec2_terminates_then_deletes(client, monkeypatch):
    """aws_ec2 delete calls terminate_instance then drops the Django row.

    What would make this fail: deleting the row without terminating, or
    keeping the row after a successful terminate.
    """
    from core.models import Target

    _t1_user(client)
    _touch(client, monkeypatch)
    provider = RecordingCloud()
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"])
    pk = target.pk
    _inject_provider(monkeypatch, provider)

    response = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 204, response.content
    assert any(
        c[0] == "terminate_instance" and c[1] == inst["id"]
        for c in provider.calls
    )
    assert inst["id"] not in provider.instances
    assert not Target.objects.filter(pk=pk).exists()


@pytest.mark.req("AWS-INSTANCE-T1")
def test_target_delete_on_ssh_does_not_call_terminate(client, monkeypatch):
    """SSH kind is unchanged: row delete only, no CloudProvider terminate.

    What would make this fail: routing ssh targets through terminate_instance.
    """
    from core.models import Target

    _t1_user(client)
    _touch(client, monkeypatch)
    provider = RecordingCloud()
    target = _ssh_target()
    pk = target.pk
    _inject_provider(monkeypatch, provider)

    response = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 204, response.content
    assert not any(c[0] == "terminate_instance" for c in provider.calls)
    assert not Target.objects.filter(pk=pk).exists()


@pytest.mark.req("AWS-INSTANCE-T1")
def test_terminate_absent_is_success():
    """Already-absent instance is success (reaper / retry depend on it).

    What would make this fail: treating a missing instance as terminate
    failure and keeping the operator blocked, or leaving status=ready.
    """
    from core.models import Target
    from provision.aws_enroll import terminate_aws_target

    provider = RecordingCloud()
    target = _aws_target(provider_ref="i-already-gone")
    terminate_aws_target(target, provider=provider)
    target.refresh_from_db()
    assert Target.objects.filter(pk=target.pk).exists()
    assert target.status != Target.Status.READY
    assert target.status == Target.Status.DECOMMISSIONED
    assert any(
        c[0] == "terminate_instance" and c[1] == "i-already-gone"
        for c in provider.calls
    )


@pytest.mark.req("AWS-INSTANCE-T1")
def test_terminate_failure_does_not_delete_row(client, monkeypatch):
    """Terminate failure files C12 and keeps the Target so the operator can retry.

    What would make this fail: deleting the row on TerminateInstances error,
    losing the instance id needed to retry.
    """
    from core.models import Target

    _t1_user(client)
    _touch(client, monkeypatch)
    provider = RecordingCloud(fail_terminate=True)
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"])
    pk = target.pk
    _inject_provider(monkeypatch, provider)

    response = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 400, response.content
    assert Target.objects.filter(pk=pk).exists()
    assert inst["id"] in provider.instances
    target.refresh_from_db()
    assert target.provider_ref == inst["id"]


@pytest.mark.req("AWS-INSTANCE-T1")
def test_instance_terminate_does_not_leave_ready_target():
    """instance.terminate must not leave status=ready (success or failure).

    What would make this fail: keeping READY after a successful AWS terminate
    (the Hub still thinks the host is live) or after a failed terminate.
    """
    from core.models import Target
    from provision.aws_enroll import TerminateError, terminate_aws_target

    provider = RecordingCloud()
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"], status=Target.Status.READY)
    terminate_aws_target(target, provider=provider)
    target.refresh_from_db()
    assert target.status != Target.Status.READY
    assert target.status == Target.Status.DECOMMISSIONED
    assert Target.objects.filter(pk=target.pk).exists()

    failing = RecordingCloud(fail_terminate=True)
    boom = failing.create_instance({"tags": {"purpose": "test"}})
    stuck = _aws_target(provider_ref=boom["id"], status=Target.Status.READY)
    with pytest.raises(TerminateError):
        terminate_aws_target(stuck, provider=failing)
    stuck.refresh_from_db()
    assert stuck.status != Target.Status.READY
    assert Target.objects.filter(pk=stuck.pk).exists()


@pytest.mark.req("AWS-INSTANCE-T1")
def test_terminate_finding_fingerprint_is_aws_terminate_target_pk():
    """Terminate failure files kind aws-terminate-failed fingerprint aws-terminate:{pk}.

    What would make this fail: using the kind as the fingerprint (C12).
    """
    from core.models import Finding
    from provision.aws_enroll import TerminateError, terminate_aws_target

    provider = RecordingCloud(fail_terminate=True)
    inst = provider.create_instance({"tags": {"purpose": "test"}})
    target = _aws_target(provider_ref=inst["id"])
    with pytest.raises(TerminateError):
        terminate_aws_target(target, provider=provider)
    row = Finding.objects.get(fingerprint=f"aws-terminate:{target.pk}")
    assert row.severity == "p1"
    assert row.fingerprint != f"aws-terminate-failed:{target.pk}"
    assert "aws-terminate-failed" not in row.fingerprint
    assert Target.objects.filter(pk=target.pk).exists()

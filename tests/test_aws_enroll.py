"""T1 AWS enroll: Hub-minted public-only SSH, pin before Transport (C5/C12).

instance.create is T1 (touch + type-the-name). TOTP does not satisfy.
Playbook mints Ed25519 in-Hub, vaults the private key, injects the public
key only, pins host_key_fingerprint before any Transport, then provision_host.
tests/ do not import boto3/moto.
"""
from __future__ import annotations

import inspect
import json
import os
import pathlib
import re
import time

import pytest
from django.contrib.auth.models import User
from django.test import override_settings

from core.transport import FakeTransport
from providers.fakes import FakeCloudProvider

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
CREATE_URL = "/api/v1/instance/create/"
HOST = "100.64.0.10"
NAME = "burst-ec2-1"
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)
PRIVATE_MARKERS = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
)
FRESH = {
    "ss": {"stdout": ""},
    "docker": {"stdout": ""},
    "crontab": {"stdout": ""},
    "env": {"exit_code": 1, "stdout": ""},
}


def _zone(slug="aws-use1"):
    from core.models import NetworkZone

    return NetworkZone.objects.create(
        name=slug, slug=slug, purpose=NetworkZone.Purpose.TEST,
    )


class RecordingCloud(FakeCloudProvider):
    """Test double: FakeCloudProvider plus call log and failure knobs."""

    _MUTATING = frozenset(
        {"create_instance", "terminate_instance", "ensure_ingress_rules"}
    )

    def __init__(
        self,
        *,
        cost=0.05,
        cost_error=False,
        empty_pin=False,
        host_key_timeout=False,
        fail_create=False,
    ):
        super().__init__()
        self.calls = []
        self.cost = cost
        self.cost_error = cost_error
        self.empty_pin = empty_pin
        self.host_key_timeout = host_key_timeout
        self.fail_create = fail_create

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def estimate_hourly_cost(self, spec):
        self.calls.append(("estimate_hourly_cost", spec))
        if self.cost_error:
            raise RuntimeError("unconfigured hourly cost")
        if self.cost is None:
            raise RuntimeError("unconfigured hourly cost")
        return self.cost

    def create_instance(self, spec):
        self.calls.append(("create_instance", spec))
        if self.fail_create:
            raise RuntimeError("create failed")
        if self.host_key_timeout:
            from monitor.alerts import raise_alert

            name = (spec.get("tags") or {}).get("Name") or spec.get("name") or NAME
            raise_alert(
                "aws-host-key-timeout",
                f"aws:{name}",
                fingerprint=f"aws-host-key-timeout:{name}",
                source_engine="providers.ec2",
                title="EC2 host keys did not arrive in time",
                body=(
                    f"GetConsoleOutput produced no pin-able host key for {name}; "
                    "Transport refused (never TOFU)."
                ),
                fix_action=(
                    "Inspect the instance console and retry create; "
                    "do not accept an unpinned host key"
                ),
            )
            raise RuntimeError("host key timeout; refusing TOFU")
        inst = super().create_instance(spec)
        if self.empty_pin:
            inst["host_key_fingerprint"] = ""
            self.instances[inst["id"]]["host_key_fingerprint"] = ""
        return inst

    def terminate_instance(self, instance_id):
        self.calls.append(("terminate_instance", instance_id))
        return super().terminate_instance(instance_id)

    def ensure_ingress_rules(self, instance_id, rules):
        self.calls.append(("ensure_ingress_rules", instance_id, rules))
        return super().ensure_ingress_rules(instance_id, rules)


def _enroll(*, provider=None, transport=None, host=HOST, name=NAME, zone=None,
            **kwargs):
    from provision.aws_enroll import enroll_aws_target

    zone = zone or _zone()
    provider = provider or RecordingCloud()
    events = []
    transport = transport or FakeTransport(responses=FRESH)

    def make_transport(target):
        events.append(
            {
                "ssh_key_ref": target.ssh_key_ref,
                "host_key_fingerprint": target.host_key_fingerprint,
                "kind": target.kind,
                "provider_ref": target.provider_ref,
                "host": target.host,
            }
        )
        return transport

    result = enroll_aws_target(
        host=host,
        name=name,
        zone=zone,
        provider=provider,
        make_transport=make_transport,
        **kwargs,
    )
    return result, provider, transport, events


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


def _create_body(*, host=HOST, confirm_name=None, zone=None, **extra):
    zone = zone or _zone()
    body = {
        "host": host,
        "confirm_name": HOST if confirm_name is None else confirm_name,
        "zone": zone.slug,
    }
    body.update(extra)
    return body, zone


# ── T1 HTTP ──────────────────────────────────────────────────────────────────


@pytest.mark.req("AWS-INSTANCE-T1")
def test_instance_create_is_t1():
    """instance.create is T1 Create target: RequireRecentTouch HTTP, type-the-name.

    What would make this fail: a T2/T3 row, hanging the view off /api/auth/,
    or leaving T1_HTTP unregistered so the Task 2 pin 404s the wrong slug.
    """
    from django.urls import resolve

    from core.actions import ACTION_TIERS
    from core.permissions import RequireRecentTouch
    from core.views import InstanceCreateView
    from tests.test_webauthn_t1 import T1_HTTP

    row = next(r for r in ACTION_TIERS if r["id"] == "instance.create")
    assert row["tier"] == "T1"
    assert row["label"] == "Create target"
    assert "instance" not in row["label"].lower()

    template = T1_HTTP["instance.create"]
    assert template == CREATE_URL
    match = resolve(template)
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is InstanceCreateView
    assert RequireRecentTouch in view_cls.permission_classes
    source = inspect.getsource(InstanceCreateView)
    assert "InstanceCreateSerializer" in source
    assert "request.data.get" not in source
    assert "confirm_name" in source

    core_urls = (REPO / "core" / "urls.py").read_text(encoding="utf-8")
    assert "instance/create" not in core_urls


@pytest.mark.req("AWS-INSTANCE-T1")
def test_instance_create_refuses_without_recent_touch(client, monkeypatch):
    """Two passkeys are not enough: no recent WebAuthn touch → 403, no Target.

    What would make this fail: create running on a stolen session that never
    touched a security key.
    """
    from core.models import Target

    _t1_user(client)
    body, _zone_row = _create_body()
    response = client.post(
        CREATE_URL,
        data=json.dumps(body),
        content_type="application/json",
    )
    assert response.status_code == 403, response.content
    assert "touch" in response.json()["detail"].lower()
    assert not Target.objects.filter(host=HOST).exists()
    assert "hardware_touch_at" not in client.session


@pytest.mark.req("AWS-INSTANCE-T1")
def test_instance_create_requires_type_the_name(client, monkeypatch):
    """Hardware touch without typing the intended host still refuses.

    What would make this fail: confirm_name ignored so any string creates,
    or the success path skipping the playbook.
    """
    from core.models import Target
    from provision.aws_enroll import enroll_aws_target as real_enroll

    _t1_user(client)
    _touch(client, monkeypatch)
    provider = RecordingCloud()
    transport = FakeTransport(responses=FRESH)

    def patched(**kwargs):
        kwargs.setdefault("provider", provider)
        kwargs.setdefault(
            "make_transport",
            lambda target: transport,
        )
        return real_enroll(**kwargs)

    monkeypatch.setattr("provision.aws_enroll.enroll_aws_target", patched)

    body, _zone_row = _create_body(confirm_name="wrong-host")
    wrong = client.post(
        CREATE_URL,
        data=json.dumps(body),
        content_type="application/json",
    )
    assert wrong.status_code == 400, wrong.content
    assert not Target.objects.filter(host=HOST, kind="aws_ec2").exists()

    ok_body, _ = _create_body(confirm_name=HOST, zone=_zone_row)
    ok = client.post(
        CREATE_URL,
        data=json.dumps(ok_body),
        content_type="application/json",
    )
    assert ok.status_code in (200, 201), ok.content
    assert Target.objects.filter(host=HOST, kind="aws_ec2").exists()


@pytest.mark.req("AWS-INSTANCE-T1")
def test_totp_does_not_satisfy_instance_create(client):
    """A TOTP login of a two-passkey operator still cannot satisfy T1.

    What would make this fail: TOTP writing hardware_touch_at, or create
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

    body, _ = _create_body()
    response = client.post(
        CREATE_URL,
        data=json.dumps(body),
        content_type="application/json",
    )
    assert response.status_code == 403
    assert "hardware_touch_at" not in client.session
    assert not Target.objects.filter(host=HOST).exists()


# ── pin / public-only / C12 ──────────────────────────────────────────────────


@pytest.mark.req("AWS-ENROLL-PIN")
def test_pin_happens_before_any_transport():
    """host_key_fingerprint is set on the Target before make_transport runs.

    What would make this fail: constructing SshTransport (or any Transport)
    and probing before the pin, which is TOFU.
    """
    result, provider, transport, events = _enroll()
    assert events, "provision_host must run over a Transport after the pin"
    assert events[0]["host_key_fingerprint"]
    assert events[0]["host_key_fingerprint"].startswith("SHA256:")
    creates = [c for c in provider.calls if c[0] == "create_instance"]
    assert creates, "create_instance must run so there is a pin to write"
    src = (REPO / "provision" / "aws_enroll.py").read_text(encoding="utf-8")
    assert "AutoAdd" not in src
    assert "WarningPolicy" not in src
    del result, transport


@pytest.mark.req("AWS-ENROLL-PIN")
def test_empty_pin_still_refuses_transport():
    """Empty / missing fingerprint refuses before any Transport (SEC-68).

    What would make this fail: falling through to AutoAdd / the first key
    the host presents, or constructing Transport with a blank pin.
    """
    from provision.aws_enroll import EnrollError

    provider = RecordingCloud(empty_pin=True)
    transport = FakeTransport(responses=FRESH)
    events = []

    def make_transport(target):
        events.append(target)
        return transport

    from provision.aws_enroll import enroll_aws_target

    with pytest.raises(EnrollError, match="pin|fingerprint|refuse"):
        enroll_aws_target(
            host=HOST, name=NAME, zone=_zone(),
            provider=provider, make_transport=make_transport,
        )
    assert events == [], "empty pin must not construct Transport"
    assert transport.calls == []

    from core.models import Target
    from provision.aws_enroll import terminate_aws_target

    target = Target.objects.get(host=HOST, kind=Target.Kind.AWS_EC2)
    assert target.provider_ref
    assert target.provider_ref in provider.instances
    terminate_aws_target(target, provider=provider)
    assert target.provider_ref not in provider.instances


@pytest.mark.req("AWS-ENROLL-PIN")
def test_host_key_timeout_does_not_tofu():
    """Timeout waiting for keys files aws-host-key-timeout:{name} P1, no TOFU.

    What would make this fail: using the kind as the fingerprint, or
    proceeding to Transport with an empty pin.
    """
    from core.models import Finding
    from provision.aws_enroll import EnrollError, enroll_aws_target

    provider = RecordingCloud(host_key_timeout=True)
    transport = FakeTransport(responses=FRESH)
    events = []

    def make_transport(target):
        events.append(target)
        return transport

    with pytest.raises(EnrollError, match="timeout|TOFU|pin"):
        enroll_aws_target(
            host=HOST, name=NAME, zone=_zone(),
            provider=provider, make_transport=make_transport,
        )
    row = Finding.objects.get(fingerprint=f"aws-host-key-timeout:{NAME}")
    assert row.severity == "p1"
    assert "TOFU" in row.body
    assert row.fingerprint != "aws-host-key-timeout"
    assert events == []
    assert transport.calls == []


@pytest.mark.req("AWS-ENROLL-PIN")
def test_enroll_sets_ssh_key_ref_before_transport():
    """Hub-minted Ed25519 is vaulted and ssh_key_ref is set before Transport.

    What would make this fail: logging in with a key AWS minted, or
    constructing Transport before the vault row exists.
    """
    from vault.models import Secret

    result, provider, transport, events = _enroll()
    assert events, "Transport must run after the key is vaulted"
    assert events[0]["ssh_key_ref"]
    secret = Secret.objects.get(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_id=events[0]["ssh_key_ref"],
    )
    assert secret.pk
    creates = [c for c in provider.calls if c[0] == "create_instance"]
    assert creates
    del result, transport


@pytest.mark.req("AWS-ENROLL-PIN")
def test_userdata_or_keypair_is_public_key_only():
    """create_instance spec carries the Hub pubkey; never the private key.

    What would make this fail: CreateKeyPair, UserData with the PEM, or
    stuffing Hub CLOUD_CREDENTIAL / SSM values into the spec.
    """
    result, provider, _transport, _events = _enroll()
    creates = [c for c in provider.calls if c[0] == "create_instance"]
    assert creates
    spec = creates[0][1]
    blob = json.dumps(spec)
    for marker in PRIVATE_MARKERS:
        assert marker not in blob
    pub = spec.get("ssh_public_key") or spec.get("public_key") or ""
    assert pub.startswith("ssh-ed25519")
    assert spec.get("KeyName") in (None, "")
    assert "AWS_ACCESS_KEY_ID" not in blob
    assert "AWS_SECRET_ACCESS_KEY" not in blob
    assert "/deploy-hub/" not in blob
    src = (REPO / "provision" / "aws_enroll.py").read_text(encoding="utf-8")
    assert "CreateKeyPair" not in src
    assert "create_key_pair" not in src
    del result


@pytest.mark.req("AWS-ENROLL-PIN")
def test_kind_aws_ec2_and_provider_ref_and_host_written():
    """Enroll stores kind=aws_ec2, provider_ref, and host as the Transport address.

    What would make this fail: leaving kind=ssh, stuffing i-… into host, or
    using the world-open public IP as the SSH address.
    """
    from core.models import Target

    result, provider, _transport, events = _enroll()
    target = Target.objects.get(host=HOST)
    assert target.kind == Target.Kind.AWS_EC2
    assert target.provider_ref
    assert target.provider_ref.startswith("i-")
    assert target.host == HOST
    assert target.host != target.provider_ref
    assert target.host_key_fingerprint
    assert target.ssh_key_ref
    assert events[0]["kind"] == Target.Kind.AWS_EC2
    assert events[0]["provider_ref"] == target.provider_ref
    del result, provider


@pytest.mark.req("AWS-ENROLL-PIN")
def test_create_finding_fingerprint_is_aws_create_name():
    """Create failure files kind aws-create-failed fingerprint aws-create:{name}.

    What would make this fail: using the kind as the fingerprint (C12), or
    proceeding to Transport after RunInstances failed.
    """
    from core.models import Finding
    from provision.aws_enroll import EnrollError, enroll_aws_target

    provider = RecordingCloud(fail_create=True)
    transport = FakeTransport(responses=FRESH)
    events = []

    def make_transport(target):
        events.append(target)
        return transport

    with pytest.raises(EnrollError):
        enroll_aws_target(
            host=HOST, name=NAME, zone=_zone(),
            provider=provider, make_transport=make_transport,
        )
    row = Finding.objects.get(fingerprint=f"aws-create:{NAME}")
    assert row.severity == "p2"
    assert row.fingerprint != f"aws-create-failed:{NAME}"
    assert "aws-create-failed" not in row.fingerprint
    assert events == []
    assert transport.calls == []


@pytest.mark.req("UX-P5-AWS-OPERATOR")
def test_cost_visible_on_overlay_before_confirm():
    """T1Overlay.cost is required on instance.create and shown in words before Confirm.

    What would make this fail: omitting cost on create, showing $0 as free,
    color-only, or passing cost on Delete target / ssh.rotate.
    """
    from core.actions import ACTION_TIERS

    row = next(r for r in ACTION_TIERS if r["id"] == "instance.create")
    assert row["label"] == "Create target"

    tiers = (REPO / "frontend" / "src" / "Tiers.jsx").read_text(encoding="utf-8")
    targets = (REPO / "frontend" / "src" / "screens" / "Targets.jsx").read_text(
        encoding="utf-8"
    )
    assert "function T1Overlay" in tiers
    assert re.search(r"function T1Overlay\(\s*\{[^}]*cost", tiers, re.S)
    start = tiers.find("export function T1Overlay")
    end = tiers.find("export function ActionButton")
    overlay = tiers[start:end]
    assert "costText" in overlay or "costLine" in overlay
    assert "five cents per hour" in tiers
    assert overlay.find("costText") < overlay.find("Confirm —"), (
        "cost must be visible before Confirm"
    )
    assert "$" in tiers or "0.05" in tiers

    assert "instance.create" in targets
    assert re.search(r"cost=\{", targets)
    assert "target.delete" in targets


@pytest.mark.req("UX-P5-AWS-OPERATOR")
def test_unconfigured_estimate_refuses_create():
    """Unconfigured / error estimate refuses create — never $0 as free.

    What would make this fail: treating a missing table as $0.00/h free, or
    calling create_instance before the estimate is known.
    """
    from core.models import Target
    from provision.aws_enroll import EnrollError, enroll_aws_target

    provider = RecordingCloud(cost_error=True)
    transport = FakeTransport(responses=FRESH)
    events = []

    def make_transport(target):
        events.append(target)
        return transport

    with pytest.raises(EnrollError, match="estimate|unconfigured|cost"):
        enroll_aws_target(
            host=HOST, name=NAME, zone=_zone(),
            provider=provider, make_transport=make_transport,
        )
    assert not any(c[0] == "create_instance" for c in provider.calls)
    assert events == []
    assert not Target.objects.filter(host=HOST, kind="aws_ec2").exists()

    zero = RecordingCloud(cost=0)
    with pytest.raises(EnrollError, match="estimate|free|cost|\\$0"):
        enroll_aws_target(
            host=HOST, name=NAME, zone=_zone("aws-zero"),
            provider=zero, make_transport=make_transport,
        )
    assert not any(c[0] == "create_instance" for c in zero.calls)


def test_budget_cap_hit_files_existing_kind():
    """Cap exceeded files existing budget-cap-hit fingerprint budget-cap-hit:aws.

    What would make this fail: inventing a new kind, or creating the instance
    anyway. Empty AWS_HOURLY_BUDGET_USD still shows the estimate and does not file.
    """
    from core.models import Finding, Target
    from provision.aws_enroll import EnrollError, enroll_aws_target

    provider = RecordingCloud(cost=0.05)
    transport = FakeTransport(responses=FRESH)

    def make_transport(target):
        return transport

    with override_settings(AWS_HOURLY_BUDGET_USD="0.01"):
        with pytest.raises(EnrollError, match="budget|cap"):
            enroll_aws_target(
                host=HOST, name=NAME, zone=_zone(),
                provider=provider, make_transport=make_transport,
            )
    row = Finding.objects.get(fingerprint="budget-cap-hit:aws")
    assert row.severity == "p1"
    assert not any(c[0] == "create_instance" for c in provider.calls)
    assert not Target.objects.filter(host=HOST, kind="aws_ec2").exists()

    Finding.objects.all().delete()
    ok_provider = RecordingCloud(cost=0.05)
    with override_settings(AWS_HOURLY_BUDGET_USD=""):
        enroll_aws_target(
            host=HOST, name=NAME, zone=_zone("aws-budget-ok"),
            provider=ok_provider, make_transport=make_transport,
        )
    assert not Finding.objects.filter(fingerprint="budget-cap-hit:aws").exists()
    assert any(c[0] == "create_instance" for c in ok_provider.calls)


@pytest.mark.req("AWS-ENROLL-PIN")
def test_enroll_run_twice_zero_mutating_calls():
    """Second pass records zero mutating provider / Transport calls (D-018).

    What would make this fail: minting another key, RunInstances again, or
    rewriting the host after the Target is already enrolled.
    """
    provider = RecordingCloud()
    transport = FakeTransport(responses=FRESH)
    zone = _zone()

    from provision.aws_enroll import enroll_aws_target

    first = enroll_aws_target(
        host=HOST, name=NAME, zone=zone,
        provider=provider, make_transport=lambda target: transport,
    )
    assert provider.mutating_calls(), "first enroll must create_instance"
    first_mut = list(provider.mutating_calls())
    transport.calls.clear()
    provider.calls.clear()
    second = enroll_aws_target(
        host=HOST, name=NAME, zone=zone,
        provider=provider, make_transport=lambda target: transport,
    )
    assert provider.mutating_calls() == []
    assert transport.mutating_calls() == []
    assert first.pk == second.pk
    del first_mut


def test_aws_enroll_tests_do_not_import_boto3():
    """This module never imports boto3/botocore/moto (D-034 split)."""
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(text) is None
    playbook = REPO / "provision" / "aws_enroll.py"
    if playbook.exists():
        assert _IMPORT_BOTO.search(playbook.read_text(encoding="utf-8")) is None

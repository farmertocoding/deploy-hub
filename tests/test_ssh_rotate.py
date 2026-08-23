"""T1: quarterly SSH rotation — dual-key overlap, probe-before-revoke (D-064 / C8).

SEC-B7-SSH-QUARTERLY-ROTATE. Private key never leaves the vault. Never
ssh-keygen on the target. Never clobber authorized_keys with a single-key
install during overlap. Overlap itself is not a Finding.
"""
from __future__ import annotations

import ast
import json
import pathlib
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from paramiko import ECDSAKey

from core.models import NetworkZone, Target
from core.transport import CommandResult, FakeTransport
from vault import service as vault_service
from vault.models import Secret

pytestmark = [pytest.mark.django_db, pytest.mark.req("SEC-B7-SSH-QUARTERLY-ROTATE")]

REPO = pathlib.Path(__file__).resolve().parent.parent
AUTH_PATH = "/home/deploy/.ssh/authorized_keys"
OPERATOR_LINE = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIoperatorpreserve0001 operator@laptop\n"
)
PRIVATE_MARKERS = ("BEGIN OPENSSH PRIVATE KEY", "BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY")


def _ed25519_pair():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    pub = key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    return pem, pub


def _blob(line):
    parts = (line or "").split()
    return parts[1] if len(parts) >= 2 else (line or "").strip()


def _public_line(pem):
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_ssh_private_key,
    )

    key = load_ssh_private_key(pem, password=None)
    return key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()


def _as_text(payload):
    if payload is None:
        return ""
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload).decode()
    return str(payload)


def _surfaces():
    from core.models import AuditEvent, CheckRun, Finding

    blobs = []
    for row in Finding.objects.all():
        blobs.extend([row.title, row.body, row.fix_action, row.entity, row.fingerprint])
    for event in AuditEvent.objects.all():
        blobs.append(event.detail)
    for run in CheckRun.objects.filter(kind="ssh_rotate"):
        blobs.append(run.results)
    return json.dumps(blobs, default=str)


def _target(*, host="10.0.0.8", owner_id="vault-ssh-old"):
    zone = NetworkZone.objects.create(
        name="lan-ssh-rot", slug=f"lan-ssh-{uuid.uuid4().hex[:10]}",
    )
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=host,
        ssh_user="deploy",
        ssh_key_ref=owner_id,
        host_key_fingerprint="SHA256:test-pin",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def _plant_old_key(target, *, age=timedelta(days=91)):
    pem, pub = _ed25519_pair()
    secret = vault_service.put(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id=target.ssh_key_ref,
        plaintext=pem,
    )
    Secret.objects.filter(pk=secret.pk).update(created_at=timezone.now() - age)
    secret.refresh_from_db()
    line = f"{pub} hub-ssh:{target.ssh_key_ref}\n"
    return secret, pem, pub, line


class RotateTransport(FakeTransport):
    """Fake that serves authorized_keys from files and logins from vault pubkeys."""

    def __init__(self, *, auth_path=AUTH_PATH, initial=""):
        super().__init__()
        self.auth_path = auth_path
        raw = initial.encode() if isinstance(initial, str) else initial
        self.files[auth_path] = raw
        self.put_modes[auth_path] = 0o600
        self.active_ref = None
        self.put_snapshots = []
        self.old_ref = None
        self.fail_new_login = False

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv[:1] == ["cat"]:
            path = argv[-1] if len(argv) > 1 else self.auth_path
            return CommandResult(argv, stdout=_as_text(self.files.get(path, b"")))
        if argv == ["true"]:
            return CommandResult(argv, **self._login_result())
        return CommandResult(argv)

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        super().put(local_path_or_bytes, remote_path, mode=mode)
        self.put_snapshots.append((remote_path, local_path_or_bytes, mode))

    def _auth_text(self):
        return _as_text(self.files.get(self.auth_path, b""))

    def _login_result(self):
        ref = self.active_ref
        if self.fail_new_login and ref and ref != self.old_ref:
            return {"exit_code": 255, "stdout": "", "stderr": "Permission denied"}
        blob = _blob_for_ref(ref)
        text = self._auth_text()
        if blob and blob in text:
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        return {"exit_code": 255, "stdout": "", "stderr": "Permission denied"}


def _blob_for_ref(ref):
    if not ref:
        return ""
    secret = (
        Secret.objects.filter(kind=Secret.Kind.SSH_PRIVATE_KEY, owner_id=ref)
        .order_by("-created_at")
        .first()
    )
    if secret is None:
        return ""
    pem = vault_service.get(secret, reason="ssh-rotate-test")
    return _blob(_public_line(pem))


def _factory(transport):
    def make(target):
        transport.active_ref = target.ssh_key_ref
        return transport

    return make


def _world(*, fail_new_login=False, sticky_old=False):
    target = _target()
    old, pem, pub, line = _plant_old_key(target)
    initial = line + OPERATOR_LINE
    transport = RotateTransport(initial=initial)
    if sticky_old:
        transport = StickyOldTransport(old_blob=_blob(pub), initial=initial)
    transport.old_ref = target.ssh_key_ref
    transport.active_ref = target.ssh_key_ref
    transport.fail_new_login = fail_new_login
    return target, transport, old, pem, pub


class StickyOldTransport(RotateTransport):
    """Drop-put cannot remove the old blob — revoke-intended, old still lives."""

    def __init__(self, *, old_blob, **kwargs):
        super().__init__(**kwargs)
        self.old_blob = old_blob

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        text = _as_text(local_path_or_bytes)
        if self.old_blob not in text:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"ssh-ed25519 {self.old_blob} hub-ssh:stale-old\n"
            local_path_or_bytes = text.encode()
        super().put(local_path_or_bytes, remote_path, mode=mode)


def _rotation_findings():
    from core.models import Finding

    return Finding.objects.filter(
        fingerprint__startswith="ssh-rotation-",
    )


def test_ssh_rotate_generate_append_probe_revoke():
    """Generate in-Hub → append both keys → probe new → drop old → retarget →
    probe old fails / new works → revoke old Secret.

    What would make this fail: ssh-keygen on the target, a single-key put
    during overlap, skipping Transport.probe, or leaving the old Secret.
    """
    from provision.ssh_rotate import rotate_ssh

    target, transport, old, old_pem, old_pub = _world()
    old_blob = _blob(old_pub)
    old_pk = old.pk
    old_ref = target.ssh_key_ref

    result = rotate_ssh(target, transport, make_transport=_factory(transport))
    assert result["status"] == "rotated"

    target.refresh_from_db()
    assert target.ssh_key_ref != old_ref
    assert not Secret.objects.filter(pk=old_pk).exists()
    new = Secret.objects.get(
        kind=Secret.Kind.SSH_PRIVATE_KEY, owner_id=target.ssh_key_ref,
    )
    new_pem = vault_service.get(new, reason="ssh-rotate-assert")
    new_blob = _blob(_public_line(new_pem))
    assert new_blob.startswith("AAAAC3NzaC1lZDI1NTE5")
    assert _public_line(new_pem).startswith("ssh-ed25519 ")

    assert transport.put_snapshots, "append/drop must go through put(), never a heredoc"
    first_text = _as_text(transport.put_snapshots[0][1])
    last_text = _as_text(transport.put_snapshots[-1][1])
    assert old_blob in first_text and new_blob in first_text, (
        "overlap put must carry both pubkeys — a single-key install locks the operator out"
    )
    assert OPERATOR_LINE.strip() in first_text
    assert old_blob not in last_text
    assert new_blob in last_text
    assert OPERATOR_LINE.strip() in last_text
    assert transport.put_snapshots[0][2] == 0o600

    probes = [argv for kind, argv in transport.calls if kind == "probe"]
    assert any(argv[:1] == ["cat"] for argv in probes)
    assert any(argv == ["true"] for argv in probes)
    assert all(kind != "run" for kind, _ in transport.calls)
    for _kind, payload in transport.calls:
        if isinstance(payload, list):
            blob = " ".join(payload)
        else:
            blob = str(payload)
        assert "ssh-keygen" not in blob

    src = (REPO / "provision" / "ssh_rotate.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and node.value == "ssh-keygen":
            raise AssertionError("playbook must not name the ssh-keygen binary")

    from django.conf import settings

    entry = settings.CELERY_BEAT_SCHEDULE["ssh-rotate-quarterly"]
    assert float(entry["schedule"]) == 90 * 86400
    assert entry["task"] == "provision.tasks.rotate_ssh_keys"


def test_ssh_rotate_run_twice_zero_mutating_calls():
    """Second pass inspects via probe and records zero run/put (D-018).

    What would make this fail: generating another key on every call, or
    rewriting authorized_keys when the current key is still inside 90 d.
    """
    from provision.ssh_rotate import rotate_ssh

    target, transport, old, _, _ = _world()
    rotate_ssh(target, transport, make_transport=_factory(transport))
    first = list(transport.mutating_calls())
    assert first, "first rotation must put the overlap and the drop"
    transport.calls.clear()
    rotate_ssh(target, transport, make_transport=_factory(transport))
    assert transport.mutating_calls() == []
    assert all(kind == "probe" for kind, _ in transport.calls)


def test_incomplete_rotation_is_p1():
    """New-key login probe failure files P1 ssh-rotation-incomplete; old key stays.

    What would make this fail: dropping the old pubkey anyway, or filing
    overlap itself as the Finding.
    """
    from core.models import Finding
    from monitor.alert_rules import classify
    from provision.ssh_rotate import rotate_ssh

    assert classify("ssh-rotation-incomplete") == "p1"
    target, transport, old, _, old_pub = _world(fail_new_login=True)
    old_ref = target.ssh_key_ref
    result = rotate_ssh(target, transport, make_transport=_factory(transport))
    assert result["status"] == "incomplete"
    target.refresh_from_db()
    assert target.ssh_key_ref == old_ref
    assert Secret.objects.filter(pk=old.pk).exists()
    row = Finding.objects.get(fingerprint=f"ssh-rotation-incomplete:{target.pk}")
    assert row.severity == Finding.Severity.P1
    assert "ssh-rotation-stale-key" not in {
        f.fingerprint.split(":")[0] for f in Finding.objects.all()
    }
    text = transport._auth_text()
    assert _blob(old_pub) in text


def test_stale_old_key_after_revoke_intended_is_p2():
    """After the drop is intended, an old pubkey that still authenticates is P2.

    What would make this fail: treating leftover old-key login as success, or
    classifying ssh-rotation-stale-key as P1.
    """
    from core.models import Finding
    from monitor.alert_rules import classify
    from provision.ssh_rotate import rotate_ssh

    assert classify("ssh-rotation-stale-key") == "p2"
    target, transport, old, _, old_pub = _world(sticky_old=True)
    rotate_ssh(target, transport, make_transport=_factory(transport))
    row = Finding.objects.get(fingerprint=f"ssh-rotation-stale-key:{target.pk}")
    assert row.severity == Finding.Severity.P2
    assert _blob(old_pub) in transport._auth_text()


def test_overlap_is_not_a_finding():
    """Two hub pubkeys in authorized_keys during overlap must not file.

    What would make this fail: raise_alert on the append step, or treating
    dual-key as ssh-rotation-incomplete.
    """
    from core.models import Finding
    from provision.ssh_rotate import rotate_ssh

    target, transport, old, _, old_pub = _world()
    old_blob = _blob(old_pub)
    seen_overlap = {"n": 0}

    orig_put = transport.put

    def watching_put(data, remote, *, mode=0o644):
        orig_put(data, remote, mode=mode)
        text = _as_text(data)
        if old_blob in text and text.count("ssh-ed25519") >= 2:
            seen_overlap["n"] += 1
            assert not _rotation_findings().exists(), (
                "overlap itself is not a Finding (D-064)"
            )

    transport.put = watching_put
    rotate_ssh(target, transport, make_transport=_factory(transport))
    assert seen_overlap["n"] >= 1
    assert not _rotation_findings().exists()
    assert not Finding.objects.filter(
        fingerprint__startswith="ssh-rotation-incomplete:",
    ).exists()


def test_private_key_never_leaves_vault():
    """PEM never rides put(), argv, CheckRun, Finding, or AuditEvent.detail.

    What would make this fail: writing the private key to authorized_keys,
    passing it as a Transport argv, or logging it on rotate.
    """
    from provision.ssh_rotate import rotate_ssh

    target, transport, old, old_pem, _ = _world()
    rotate_ssh(target, transport, make_transport=_factory(transport))
    target.refresh_from_db()
    new = Secret.objects.get(
        kind=Secret.Kind.SSH_PRIVATE_KEY, owner_id=target.ssh_key_ref,
    )
    new_pem = vault_service.get(new, reason="ssh-rotate-assert")

    for _, payload, _ in transport.put_snapshots:
        text = _as_text(payload)
        for marker in PRIVATE_MARKERS:
            assert marker not in text
        assert old_pem.decode() not in text
        assert new_pem.decode() not in text
    for _kind, payload in transport.calls:
        blob = " ".join(payload) if isinstance(payload, list) else str(payload)
        for marker in PRIVATE_MARKERS:
            assert marker not in blob
    surface = _surfaces()
    for marker in PRIVATE_MARKERS:
        assert marker not in surface
    assert old_pem.decode() not in surface
    assert new_pem.decode() not in surface


def test_ssh_rotate_is_t1():
    """ssh.rotate is T1: ACTION_TIERS row, RequireRecentTouch HTTP, type-the-name.

    What would make this fail: a T2/T3 row, an unguarded view, or leaving
    T1_HTTP unregistered so the Task 2 pin 404s the wrong slug.
    """
    import inspect

    from django.urls import resolve

    from core.actions import ACTION_TIERS
    from core.permissions import RequireRecentTouch
    from core.views import SshRotateView

    row = next(r for r in ACTION_TIERS if r["id"] == "ssh.rotate")
    assert row["tier"] == "T1"

    from tests.test_webauthn_t1 import T1_HTTP

    template = T1_HTTP["ssh.rotate"]
    match = resolve(template.format(pk=1))
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is SshRotateView
    assert RequireRecentTouch in view_cls.permission_classes
    source = inspect.getsource(SshRotateView)
    assert "SshRotateSerializer" in source
    assert "request.data.get" not in source
    assert "confirm_name" in source


def test_host_key_mismatch_files_finding(monkeypatch):
    """SshTransport._refuse files P1 ssh-host-key-mismatch, not AuditEvent-only.

    What would make this fail: audit-only refuse, or raise_alert of an
    unregistered kind.
    """
    from core.models import Finding
    from core.ssh import HostKeyMismatch, SshTransport
    from monitor.alert_rules import classify
    from tests.test_ssh_transport import _client_key_and_pem, _install_presenting_connect

    assert classify("ssh-host-key-mismatch") == "p1"
    _, pem = _client_key_and_pem()
    pinned = ECDSAKey.generate()
    presented = ECDSAKey.generate()
    assert pinned.fingerprint != presented.fingerprint
    target = _target(owner_id="vault-ssh-hk")
    vault_service.put(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id=target.ssh_key_ref,
        plaintext=pem,
    )
    target.host_key_fingerprint = pinned.fingerprint
    target.save(update_fields=["host_key_fingerprint"])
    _install_presenting_connect(monkeypatch, presented)

    with pytest.raises(HostKeyMismatch):
        SshTransport(target).run(["true"])

    row = Finding.objects.get(fingerprint=f"ssh-host-key-mismatch:{target.pk}")
    assert row.severity == Finding.Severity.P1
    assert row.title
    assert row.body
    assert row.fix_action

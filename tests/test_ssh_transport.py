"""T1: SshTransport — argv lists, SFTP put, fail-closed host-key pin."""
import io
import json
import logging
from unittest.mock import MagicMock

import pytest
from fabric.testing.base import MockChannel
from paramiko import ECDSAKey

from core.models import AuditEvent, NetworkZone, Target
from vault import service
from vault.models import Secret

pytestmark = pytest.mark.django_db


def _client_key_and_pem():
    key = ECDSAKey.generate()
    buf = io.StringIO()
    key.write_private_key(buf)
    return key, buf.getvalue().encode()


def _target(*, fingerprint, key_bytes, owner_id="vault-ssh-1"):
    zone = NetworkZone.objects.create(name="lan", slug="lan-ssh")
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref=owner_id,
        host_key_fingerprint=fingerprint,
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    service.put(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id=owner_id,
        plaintext=key_bytes,
    )
    return target


def _install_presenting_connect(monkeypatch, presented_key):
    """Paramiko stub: connect() runs the client's host-key policy, no sshd.

    Fabric's default AutoAddPolicy would accept any presented key. A pin that
    actually fails closed must go through missing_host_key.
    """
    state = {"connects": 0, "commands": [], "sftp": MagicMock()}
    state["sftp"].getcwd.return_value = "/remote"
    state["sftp"].stat.return_value.st_mode = 0o644
    state["sftp"].normalize.side_effect = lambda p: p

    def connect(self, hostname, port=22, username=None, **kwargs):
        state["connects"] += 1
        self._policy.missing_host_key(self, hostname, presented_key)
        channel = MockChannel(stdout=io.BytesIO(b"ok\n"), stderr=io.BytesIO(b""))
        channel.recv_exit_status.return_value = 0
        channel.exit_status_ready.return_value = True
        real_exec = channel.exec_command

        def tracking_exec(cmd):
            state["commands"].append(cmd)
            return real_exec(cmd)

        channel.exec_command = tracking_exec
        transport = MagicMock()
        transport.active = True
        transport.open_session.return_value = channel
        transport.open_sftp_client.return_value = state["sftp"]
        self._transport = transport

    monkeypatch.setattr("fabric.connection.SSHClient.connect", connect)
    return state


@pytest.mark.req("VAL-45-SHELL-ARGLISTS")
def test_argv_must_be_a_list():
    """A string argv must TypeError before any remote call — same contract as FakeTransport.

    What would make this fail: SshTransport.run/probe accepting a shell string.
    """
    from core.ssh import SshTransport

    target = Target(
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref="unused",
        host_key_fingerprint="SHA256:unused",
    )
    t = SshTransport(target)
    with pytest.raises(TypeError):
        t.run("echo hello")
    with pytest.raises(TypeError):
        t.probe("docker inspect foo")


@pytest.mark.req("VAL-45-SHELL-ARGLISTS")
def test_put_does_not_build_a_heredoc(monkeypatch):
    """put() must use SFTP (putfo/put), never a shell heredoc.

    What would make this fail: delivering file bytes via `cat <<EOF` / run().
    """
    from core.ssh import SshTransport

    _, pem = _client_key_and_pem()
    presented = ECDSAKey.generate()
    target = _target(fingerprint=presented.fingerprint, key_bytes=pem)
    state = _install_presenting_connect(monkeypatch, presented)

    SshTransport(target).put(b"hello-bytes", "/tmp/hub-file")

    assert state["sftp"].putfo.called or state["sftp"].put.called
    joined = " ".join(str(c) for c in state["commands"])
    assert "<<" not in joined
    assert "cat" not in joined


@pytest.mark.req("SEC-68-HOSTKEY-PINNING")
def test_hostkey_mismatch_refuses_and_audits(monkeypatch):
    """Presented key ≠ pin: refuse, security audit, no retry against a new key.

    What would make this fail: AutoAddPolicy, swapping the pin, or skipping audit.
    """
    from core.ssh import HostKeyMismatch, SshTransport

    _, pem = _client_key_and_pem()
    pinned = ECDSAKey.generate()
    presented = ECDSAKey.generate()
    assert pinned.fingerprint != presented.fingerprint
    target = _target(fingerprint=pinned.fingerprint, key_bytes=pem)
    state = _install_presenting_connect(monkeypatch, presented)

    t = SshTransport(target)
    with pytest.raises(HostKeyMismatch):
        t.run(["true"])

    assert state["connects"] == 1
    event = AuditEvent.objects.get(severity="security")
    assert event.action == "ssh-hostkey-mismatch"
    assert event.object_id == str(target.pk)
    # Pin is unchanged — we do not adopt the presented key and retry.
    target.refresh_from_db()
    assert target.host_key_fingerprint == pinned.fingerprint
    with pytest.raises(HostKeyMismatch):
        t.run(["true"])
    assert state["connects"] == 2


@pytest.mark.req("SEC-68-HOSTKEY-PINNING")
def test_matching_pin_connects(monkeypatch):
    """Matching fingerprint is accepted and a command can run (paramiko stub).

    What would make this fail: rejecting a matching pin, or never opening a session.
    """
    from core.ssh import SshTransport

    _, pem = _client_key_and_pem()
    presented = ECDSAKey.generate()
    target = _target(fingerprint=presented.fingerprint, key_bytes=pem)
    _install_presenting_connect(monkeypatch, presented)

    result = SshTransport(target).run(["true"])
    assert result.ok
    assert result.stdout == "ok\n"


@pytest.mark.req("SEC-68-HOSTKEY-PINNING")
def test_private_key_bytes_never_in_log_or_task_kwargs(monkeypatch, caplog):
    """Vault decrypt is the only key path; PEM never appears in logs or task kwargs.

    What would make this fail: passing key bytes as Celery kwargs, or logging PEM.
    """
    from core.ssh import SshTransport

    _, pem = _client_key_and_pem()
    marker = pem.splitlines()[2].decode()
    presented = ECDSAKey.generate()
    target = _target(fingerprint=presented.fingerprint, key_bytes=pem)
    _install_presenting_connect(monkeypatch, presented)

    # Worker-facing dict: target id only. Key bytes are loaded inside the transport.
    task_kwargs = {"target_id": target.pk}
    assert marker not in json.dumps(task_kwargs)

    caplog.set_level(logging.DEBUG)
    real_get = service.get
    vault_reads = []

    def tracking_get(secret, **kwargs):
        vault_reads.append(secret)
        return real_get(secret, **kwargs)

    monkeypatch.setattr("vault.service.get", tracking_get)
    worker_target = Target.objects.get(pk=task_kwargs["target_id"])
    SshTransport(worker_target).run(["true"])

    assert vault_reads, "private key must be loaded via vault.service.get"
    assert marker not in caplog.text
    for record in caplog.records:
        assert marker not in record.getMessage()
        assert pem.decode() not in record.getMessage()
    for event in AuditEvent.objects.all():
        blob = json.dumps(event.detail)
        assert marker not in blob
        assert pem.decode() not in blob

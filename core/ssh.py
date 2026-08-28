"""SshTransport: Fabric-backed Transport with a fail-closed host-key pin (§6.8)."""
import io
import shlex

import paramiko
from fabric import Config, Connection
from paramiko.ssh_exception import BadHostKeyException

from core.audit import audit
from core.transport import CommandResult, Transport
from vault import service as vault_service
from vault.models import Secret


class HostKeyMismatch(Exception):
    """Pinned host key did not match; the connection is refused and not retried."""


def _require_argv(argv):
    if not isinstance(argv, (list, tuple)):
        raise TypeError("argv must be a list — never a shell string (§4.5)")
    return list(argv)


def _pkey_from_bytes(material: bytes):
    text = material.decode()
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text))
        except (paramiko.SSHException, ValueError):
            continue
    raise ValueError("unsupported ssh private key")


class PinnedHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Accept the presented key only when its fingerprint matches the Target pin."""

    def __init__(self, target):
        self.target = target

    def missing_host_key(self, client, hostname, key):
        presented = key.fingerprint
        expected = self.target.host_key_fingerprint
        if not expected or presented != expected:
            _refuse(self.target, hostname, presented, expected)
        client.get_host_keys().add(hostname, key.get_name(), key)


def _refuse(target, hostname, presented, expected):
    audit(
        "ssh-hostkey-mismatch",
        target,
        severity="security",
        host=hostname,
        expected=expected,
        presented=presented,
    )
    from monitor.alerts import raise_alert

    raise_alert(
        "ssh-host-key-mismatch",
        f"target:{getattr(target, 'pk', '')}",
        fingerprint=f"ssh-host-key-mismatch:{getattr(target, 'pk', '')}",
        workspace=getattr(target, "workspace", None) or getattr(
            getattr(target, "zone", None), "workspace", None,
        ),
        source_engine="core.ssh",
        title="SSH host-key mismatch",
        body=(
            f"Pinned host key for {hostname} did not match "
            f"(expected {expected}, presented {presented}). "
            "Possible MITM/hijack — never auto-retried."
        ),
        fix_action=(
            "Do not retry. Verify the host on the console and update the pin "
            "only after out-of-band confirmation."
        ),
    )
    raise HostKeyMismatch(
        f"host key mismatch for {hostname}: expected {expected}, presented {presented}"
    )


class SshTransport(Transport):
    """One Fabric connection to one Target. Private key material comes from the vault."""

    def __init__(self, target):
        self.target = target
        self._cxn = None

    def run(self, argv, *, timeout=60):
        return self._exec(argv, timeout=timeout)

    def probe(self, argv, *, timeout=60):
        return self._exec(argv, timeout=timeout)

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        conn = self._connection()
        try:
            if isinstance(local_path_or_bytes, (bytes, bytearray)):
                transferred = conn.put(io.BytesIO(local_path_or_bytes), remote_path)
            else:
                transferred = conn.put(local_path_or_bytes, remote_path)
            conn.sftp().chmod(transferred.remote, mode)
        except BadHostKeyException as exc:
            self._refuse_bad_host_key(exc)

    def get(self, remote_path):
        buf = io.BytesIO()
        try:
            self._connection().get(remote_path, buf)
        except BadHostKeyException as exc:
            self._refuse_bad_host_key(exc)
        return buf.getvalue()

    def _exec(self, argv, *, timeout):
        argv = _require_argv(argv)
        try:
            result = self._connection().run(
                shlex.join(argv),
                timeout=timeout,
                hide=True,
                warn=True,
                in_stream=False,
            )
        except HostKeyMismatch:
            raise
        except BadHostKeyException as exc:
            self._refuse_bad_host_key(exc)
        return CommandResult(
            argv,
            exit_code=result.exited if result.exited is not None else 0,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _connection(self):
        if self._cxn is None:
            pkey = self._load_pkey()
            config = Config(overrides={"run": {"in_stream": False, "hide": True}})
            cxn = Connection(
                host=self.target.host,
                user=self.target.ssh_user,
                connect_kwargs={
                    "pkey": pkey,
                    "look_for_keys": False,
                    "allow_agent": False,
                },
                config=config,
            )
            # Fabric defaults to AutoAddPolicy; replace it with the pin.
            cxn.client.set_missing_host_key_policy(PinnedHostKeyPolicy(self.target))
            self._cxn = cxn
        return self._cxn

    def _load_pkey(self):
        secret = (
            Secret.objects.filter(
                kind=Secret.Kind.SSH_PRIVATE_KEY,
                owner_id=self.target.ssh_key_ref,
            )
            .order_by("-created_at")
            .first()
        )
        if secret is None:
            raise RuntimeError("no ssh private key in vault for this target")
        material = vault_service.get(secret, reason="ssh-transport")
        return _pkey_from_bytes(material)

    def _refuse_bad_host_key(self, exc):
        presented = exc.key.fingerprint if exc.key is not None else ""
        expected = getattr(exc.expected_key, "fingerprint", "") or (
            self.target.host_key_fingerprint
        )
        _refuse(self.target, exc.hostname, presented, expected)

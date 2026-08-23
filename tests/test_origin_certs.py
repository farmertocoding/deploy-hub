"""T1: Origin-cert key lifecycle (D-035) — vault-first, atomic 0400/0700, rollback."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from core.transport import CommandResult
from tests.test_ensure_route import RouteTransport

pytestmark = pytest.mark.django_db

SLUG = "blog"
TLS_DIR = f"/srv/sites/{SLUG}/tls"
CERT_PATH = f"{TLS_DIR}/cert.pem"
KEY_PATH = f"{TLS_DIR}/key.pem"


class TlsTransport(RouteTransport):
    """Route transport plus a real-enough remote filesystem for mv/chmod/rm."""

    def __init__(self):
        super().__init__()
        self.dirs = {}
        self.owners = {}
        self.fail_reload = False
        self.reload_count = 0

    def probe(self, argv, *, timeout=60):
        argv = list(argv)
        cmd = argv[1:] if argv and argv[0] == "sudo" else argv
        if cmd[:2] == ["test", "-f"] and len(cmd) >= 3:
            self.calls.append(("probe", argv))
            path = cmd[2]
            if path in self.files:
                return CommandResult(argv, exit_code=0)
            return CommandResult(argv, exit_code=1, stderr="No such file")
        return super().probe(argv, timeout=timeout)

    def run(self, argv, *, timeout=60):
        argv = list(argv)
        cmd = argv[1:] if argv and argv[0] == "sudo" else argv
        if cmd[:3] == ["systemctl", "reload", "caddy"]:
            self.calls.append(("run", argv))
            self.reload_count += 1
            if self.fail_reload:
                return CommandResult(argv, exit_code=1, stderr="caddy reload failed")
            return CommandResult(argv)
        if cmd[:2] == ["mkdir", "-p"] and len(cmd) >= 3:
            self.calls.append(("run", argv))
            self.dirs[cmd[2]] = 0o755
            return CommandResult(argv)
        if cmd[:1] == ["chmod"] and len(cmd) >= 3:
            self.calls.append(("run", argv))
            mode = int(str(cmd[1]), 8)
            path = cmd[2]
            if path in self.dirs:
                self.dirs[path] = mode
            self.put_modes[path] = mode
            return CommandResult(argv)
        if cmd[:1] == ["chown"] and len(cmd) >= 3:
            self.calls.append(("run", argv))
            self.owners[cmd[2]] = cmd[1]
            return CommandResult(argv)
        if cmd[:1] == ["mv"] and len(cmd) >= 3:
            self.calls.append(("run", argv))
            src, dst = cmd[1], cmd[2]
            if src in self.files:
                self.files[dst] = self.files.pop(src)
            if src in self.put_modes:
                self.put_modes[dst] = self.put_modes.pop(src)
            return CommandResult(argv)
        if cmd and cmd[0] == "rm":
            self.calls.append(("run", argv))
            for path in cmd[1:]:
                if path.startswith("-"):
                    continue
                self.files.pop(path, None)
            return CommandResult(argv)
        return super().run(argv, timeout=timeout)


class MismatchIssuer:
    """Returns a cert whose public key is not the Hub key — match must refuse."""

    def issue(self, zone, hostnames, *, validity_days, csr=None):
        return {
            "certificate": _unrelated_cert_pem(),
            "expires_at": timezone.now() + timedelta(days=validity_days),
        }


def _unrelated_cert_pem():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mismatch.example")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(timezone.now() - timedelta(minutes=1))
        .not_valid_after(timezone.now() + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _site(slug=SLUG, *, proxied=True, exposure="public"):
    from dns_fixtures import default_dns_zone

    from core.models import NetworkZone, Project, Site, Target

    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    net = NetworkZone.objects.create(name="lan", slug=f"lan-{slug}")
    target = Target.objects.create(
        zone=net,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="root",
        ssh_key_ref=f"vault-{slug}",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    kwargs = {
        "project": project,
        "name": slug,
        "domain": f"{slug}.example.test",
        "primary_target": target,
        "proxied": proxied,
        "exposure": exposure,
    }
    if exposure != Site.Exposure.MESH_ONLY:
        kwargs["dns_zone"] = default_dns_zone(f"{slug}.example.test")
    return Site.objects.create(**kwargs)


def _desired(site, transport, **extra):
    from providers.fakes import FakeOriginCertIssuer

    desired = {
        "transport": transport,
        "site": site,
        "site_slug": site.name,
        "domain": site.domain,
        "dns_zone": site.dns_zone,
        "cert_issuer": extra.pop("cert_issuer", FakeOriginCertIssuer()),
        "manifest_body": {"exposure": site.exposure},
        "proxied": site.proxied,
    }
    desired.update(extra)
    return desired


def _runs(transport):
    return [argv for kind, argv in transport.calls if kind == "run"]


def _has_run(transport, *needles):
    for argv in _runs(transport):
        if all(needle in argv for needle in needles):
            return argv
    return None


def test_key_is_vaulted_before_the_first_push():
    """The private key is a vault row before any put of key material.

    What would make this fail: putting PEM to the target and vaulting after,
    or writing the key into an artifact / task kwarg instead of the vault.
    """
    from deploys.certs import ensure_site_certificate
    from vault import service as vault_service
    from vault.models import Secret

    order = []
    real_put = vault_service.put

    def vault_spy(**kwargs):
        order.append(("vault", kwargs["kind"]))
        return real_put(**kwargs)

    site = _site()
    transport = TlsTransport()
    desired = _desired(site, transport)
    orig = transport.put

    def put_spy(content, remote_path, *, mode=0o644):
        blob = content if isinstance(content, (bytes, bytearray)) else b""
        if b"PRIVATE KEY" in blob:
            order.append(("put-key", remote_path))
        return orig(content, remote_path, mode=mode)

    transport.put = put_spy
    vault_service.put = vault_spy
    try:
        ensure_site_certificate(desired)
    finally:
        vault_service.put = real_put

    assert ("vault", "tls_private_key") in order
    assert any(item[0] == "put-key" for item in order)
    vault_idx = next(i for i, item in enumerate(order) if item[0] == "vault")
    put_idx = next(i for i, item in enumerate(order) if item[0] == "put-key")
    assert vault_idx < put_idx
    assert Secret.objects.filter(kind=Secret.Kind.TLS_PRIVATE_KEY).exists()


def test_key_written_atomically_0400_in_a_0700_root_dir():
    """put temp → chmod 0400 → mv, into /srv/sites/{slug}/tls/ 0700 root:root.

    What would make this fail: writing the final name in place, 0644, a
    world-readable directory, or a shell-string chmod/mv.
    """
    from deploys.certs import ensure_site_certificate

    site = _site()
    transport = TlsTransport()
    ensure_site_certificate(_desired(site, transport))

    assert _has_run(transport, "mkdir", TLS_DIR)
    chmod_dir = _has_run(transport, "chmod", TLS_DIR)
    assert chmod_dir is not None
    assert "0700" in chmod_dir or "700" in chmod_dir
    assert _has_run(transport, "chown", "root:root", TLS_DIR)

    put_paths = [remote for kind, remote in transport.calls if kind == "put"]
    assert put_paths, "expected put of cert/key material"
    assert any(path.startswith(TLS_DIR + "/") and path.endswith(".tmp") for path in put_paths)
    key_blob = transport.files.get(KEY_PATH, b"")
    if isinstance(key_blob, str):
        key_blob = key_blob.encode()
    assert b"PRIVATE KEY" in key_blob

    chmod_key = _has_run(transport, "chmod", "0400") or _has_run(transport, "chmod", "400")
    assert chmod_key is not None
    assert any(part.endswith(".tmp") for part in chmod_key)

    assert _has_run(transport, "mv")
    for argv in _runs(transport):
        assert isinstance(argv, list)
        assert not isinstance(argv, str)
        assert "<<" not in argv


def test_key_cert_mismatch_refuses_before_reload():
    """A cert that does not match the vaulted key never reaches Caddy.

    What would make this fail: reloading first and noticing the mismatch
    after the process is already serving the wrong pair.
    """
    from deploys.certs import CertKeyMismatch, ensure_site_certificate

    site = _site()
    transport = TlsTransport()
    with pytest.raises(CertKeyMismatch):
        ensure_site_certificate(_desired(site, transport, cert_issuer=MismatchIssuer()))
    assert transport.reload_count == 0
    assert not any(
        argv and "caddy" in argv
        for argv in _runs(transport)
    )


def test_failed_reload_restores_the_previous_pair():
    """A failed Caddy reload puts the previous cert+key back on disk.

    What would make this fail: leaving the new pair in place after reload
    fails, so the next start serves a key Caddy never accepted.
    """
    from deploys.certs import ensure_site_certificate

    site = _site()
    transport = TlsTransport()
    desired = _desired(site, transport)
    ensure_site_certificate(desired)
    old_cert = transport.files[CERT_PATH]
    old_key = transport.files[KEY_PATH]

    from core.models import TlsCertificate

    row = TlsCertificate.objects.get(site=site)
    row.not_after = timezone.now() + timedelta(days=2)
    row.save(update_fields=["not_after"])

    transport.fail_reload = True
    transport.calls.clear()
    with pytest.raises(RuntimeError, match="reload"):
        ensure_site_certificate(desired)
    assert transport.files[CERT_PATH] == old_cert
    assert transport.files[KEY_PATH] == old_key


def test_superseded_pair_removed_only_after_the_new_one_serves():
    """Old files stay until the new pair has reloaded successfully, then go.

    What would make this fail: deleting the previous pair before reload, or
    leaving .prev files behind after a successful cutover.
    """
    from core.models import TlsCertificate
    from deploys.certs import ensure_site_certificate

    site = _site()
    transport = TlsTransport()
    desired = _desired(site, transport)
    ensure_site_certificate(desired)
    old_cert = transport.files[CERT_PATH]

    row = TlsCertificate.objects.get(site=site)
    row.not_after = timezone.now() + timedelta(days=2)
    row.save(update_fields=["not_after"])

    transport.calls.clear()
    ensure_site_certificate(desired)
    assert transport.files[CERT_PATH] != old_cert
    assert f"{CERT_PATH}.prev" not in transport.files
    assert f"{KEY_PATH}.prev" not in transport.files
    rm_calls = [argv for argv in _runs(transport) if argv and (
        argv[0] == "rm" or (len(argv) > 1 and argv[0] == "sudo" and argv[1] == "rm")
    )]
    assert rm_calls, "expected rm of the superseded pair after a successful reload"


def test_rotation_creates_a_new_vault_version_and_keeps_the_old_readable():
    """Reissue writes a new vault version; the previous row still decrypts.

    What would make this fail: overwriting the only vault row, so a rollback
    has no key to roll back to.
    """
    from core.models import TlsCertificate
    from deploys.certs import ensure_site_certificate
    from vault import service as vault_service
    from vault.models import Secret

    site = _site()
    transport = TlsTransport()
    desired = _desired(site, transport)
    ensure_site_certificate(desired)
    first = list(Secret.objects.filter(kind=Secret.Kind.TLS_PRIVATE_KEY).order_by("pk"))
    assert first
    old_plain = vault_service.get(first[0], reason="rotation-test")

    row = TlsCertificate.objects.get(site=site)
    row.not_after = timezone.now() + timedelta(days=2)
    row.save(update_fields=["not_after"])

    ensure_site_certificate(desired)
    rows = list(Secret.objects.filter(kind=Secret.Kind.TLS_PRIVATE_KEY).order_by("pk"))
    assert len(rows) >= 2
    assert vault_service.get(rows[0], reason="rotation-test-old") == old_plain
    assert vault_service.get(rows[-1], reason="rotation-test-new") != old_plain


def test_reissue_is_skipped_inside_the_renewal_window():
    """A second ensure of a still-fresh cert records zero mutating calls.

    What would make this fail: re-issuing on every reconcile tick, burning
    Origin-CA quota and rotating keys that do not need rotating.
    """
    from deploys.certs import ensure_site_certificate

    site = _site()
    transport = TlsTransport()
    desired = _desired(site, transport)
    ensure_site_certificate(desired)
    assert transport.mutating_calls(), "first call must mutate so the second can skip"

    transport.calls.clear()
    ensure_site_certificate(desired)
    assert transport.mutating_calls() == []


def test_unproxied_public_site_refusal_files_a_finding_with_a_fix_action():
    """Unproxied public sites refuse with a named error and a P2 Finding.

    What would make this fail: a bare traceback, or a Finding whose fix_action
    does not name phase 4 (Task 12/13 render this as the Sites-screen state).
    """
    from core.models import Finding
    from deploys.certs import UnproxiedCertUnsupported, ensure_site_certificate

    site = _site(slug="bare", proxied=False)
    transport = TlsTransport()
    with pytest.raises(UnproxiedCertUnsupported):
        ensure_site_certificate(_desired(site, transport))

    row = Finding.objects.get()
    assert row.severity == Finding.Severity.P2
    assert "phase 4" in row.fix_action.lower()
    assert "3b" not in row.fix_action.lower()
    assert row.title
    assert row.body
    assert row.entity


class PermissionFaithfulTlsTransport(TlsTransport):
    """probe as deploy cannot see into a 0700 root:root tls dir."""

    def _deploy_can_traverse(self, path):
        from pathlib import Path

        parent = str(Path(path).parent)
        mode = self.dirs.get(parent, 0o755)
        owner = self.owners.get(parent, "root:root")
        if owner.startswith("deploy"):
            return True
        group = owner.split(":")[-1] if ":" in owner else ""
        if group == "deploy" and (mode & 0o010):
            return True
        if mode & 0o001:
            return True
        return False

    def probe(self, argv, *, timeout=60):
        argv = list(argv)
        sudo = bool(argv and argv[0] == "sudo")
        cmd = argv[1:] if sudo else argv
        if cmd[:2] == ["test", "-f"] and len(cmd) >= 3:
            self.calls.append(("probe", argv))
            path = cmd[2]
            if not sudo and not self._deploy_can_traverse(path):
                return CommandResult(argv, exit_code=1, stderr="Permission denied")
            if path in self.files:
                return CommandResult(argv, exit_code=0)
            return CommandResult(argv, exit_code=1, stderr="No such file")
        return super().probe(argv, timeout=timeout)


def test_permission_faithful_probe_still_restores_and_rms():
    """deploy cannot see 0700 root:root; sudo probes still restore and rm.

    What would make this fail: `test -f` without sudo after the dir is locked,
    so had_previous stays false — no .prev, no restore, no post-serve rm.
    """
    from core.models import TlsCertificate
    from deploys.certs import ensure_site_certificate

    site = _site(slug="perm")
    tls = f"/srv/sites/{site.name}/tls"
    cert_path = f"{tls}/cert.pem"
    key_path = f"{tls}/key.pem"
    transport = PermissionFaithfulTlsTransport()
    desired = _desired(site, transport)
    ensure_site_certificate(desired)
    old_cert = transport.files[cert_path]
    old_key = transport.files[key_path]

    row = TlsCertificate.objects.get(site=site)
    row.not_after = timezone.now() + timedelta(days=2)
    row.save(update_fields=["not_after"])

    transport.fail_reload = True
    transport.calls.clear()
    with pytest.raises(RuntimeError, match="reload"):
        ensure_site_certificate(desired)
    assert transport.files[cert_path] == old_cert
    assert transport.files[key_path] == old_key
    assert any(
        argv[:3] == ["sudo", "test", "-f"]
        for kind, argv in transport.calls if kind == "probe"
    )

    row.not_after = timezone.now() + timedelta(days=2)
    row.save(update_fields=["not_after"])
    transport.fail_reload = False
    transport.calls.clear()
    ensure_site_certificate(desired)
    assert transport.files[cert_path] != old_cert
    assert f"{cert_path}.prev" not in transport.files
    assert f"{key_path}.prev" not in transport.files
    rm_calls = [argv for argv in _runs(transport) if argv and (
        argv[0] == "rm" or (len(argv) > 1 and argv[0] == "sudo" and argv[1] == "rm")
    )]
    assert rm_calls, "expected rm of the superseded pair after a successful reload"


def test_failed_put_relocks_tls_dir_0700():
    """A failed SFTP put still leaves /srv/sites/{slug}/tls/ at 0700 root:root.

    What would make this fail: opening the dir as 0770 root:deploy and
    returning on put/checksum failure without a finally relock.
    """
    from deploys.certs import ensure_site_certificate

    site = _site(slug="relock")
    tls = f"/srv/sites/{site.name}/tls"
    transport = TlsTransport()
    orig = transport.put

    def boom(content, remote_path, *, mode=0o644):
        if str(remote_path).endswith(".tmp"):
            raise RuntimeError("sftp put failed")
        return orig(content, remote_path, mode=mode)

    transport.put = boom
    with pytest.raises(RuntimeError, match="put failed"):
        ensure_site_certificate(_desired(site, transport))
    assert transport.dirs.get(tls) == 0o700
    assert transport.owners.get(tls) == "root:root"


def test_caddy_route_puts_tls_files_for_a_public_site():
    """ensure_route_tls JSON PUTs name the pushed cert/key; smoke is HTTPS.

    What would make this fail: automatic_https.disable + reverse_proxy only,
    so Caddy never loads the pair the cert step just wrote.
    """
    import json

    from deploys.steps import ensure_route_tls, ensure_smoke

    site = _site(slug="routetls")
    transport = TlsTransport()
    desired = _desired(site, transport)
    desired["internal_port"] = 21000
    ensure_route_tls(desired)

    route = None
    tls_payload = None
    for _remote, raw in transport.files.items():
        blob = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        if not isinstance(blob, str) or not blob.lstrip().startswith("{"):
            continue
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@id") == f"site-{site.name}":
            route = data
        if isinstance(data, dict) and "load_files" in str(data):
            tls_payload = data
    assert route is not None
    assert route.get("tls_connection_policies") == [{
        "certificate_selection": {"any_tag": [f"site-{site.name}"]},
    }]
    dumped = json.dumps(route)
    assert "BEGIN CERTIFICATE" not in dumped
    assert "-----BEGIN" not in dumped
    assert tls_payload is not None
    files = (tls_payload.get("certificates") or {}).get("load_files") or []
    assert files
    assert files[0]["certificate"] == f"/srv/sites/{site.name}/tls/cert.pem"
    assert files[0]["key"] == f"/srv/sites/{site.name}/tls/key.pem"
    assert "BEGIN" not in json.dumps(tls_payload)

    transport.routes[f"site-{site.name}"] = json.dumps(
        {"live": True, "ready": True, "checks": {}}
    ).encode()

    class _ReadyOnce(TlsTransport):
        def probe(self, argv, *, timeout=60):
            argv = list(argv)
            if argv and argv[0] == "curl" and any(
                isinstance(p, str) and p.startswith("https://") for p in argv
            ):
                self.calls.append(("probe", argv))
                return CommandResult(
                    argv, stdout=json.dumps({"live": True, "ready": True}),
                )
            return super().probe(argv, timeout=timeout)

    smoke_t = _ReadyOnce()
    ensure_smoke(_desired(site, smoke_t))
    curls = [
        argv for kind, argv in smoke_t.calls
        if kind == "probe" and argv[:1] == ["curl"]
    ]
    assert curls
    assert any(
        any(isinstance(p, str) and p.startswith("https://") for p in argv)
        for argv in curls
    )
    assert any("-skf" in argv or "-k" in argv for argv in curls)


def test_refusal_leaves_zero_mutating_calls():
    """The unproxied refusal is probe-then-refuse: no put, no run.

    What would make this fail: mkdir/put of a half-written pair before the
    named refusal, leaving debris on the target.
    """
    from deploys.certs import UnproxiedCertUnsupported, ensure_site_certificate

    site = _site(slug="refuse", proxied=False)
    transport = TlsTransport()
    with pytest.raises(UnproxiedCertUnsupported):
        ensure_site_certificate(_desired(site, transport))
    assert transport.mutating_calls() == []

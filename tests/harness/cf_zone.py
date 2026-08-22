"""Session fixture for the credentialed Cloudflare test zone (D-034 / D-043).

Allowlists the configured purpose=test DnsZone via HUB_TEST_ZONE_SLUGS,
constructs the product adapter through dns_provider_for (never a second
client), and reaps every record this run tracked in finally.
"""
from __future__ import annotations

import os
import socket
import time
import uuid
from dataclasses import dataclass, field

import pytest
from django.conf import settings as dj_settings

TOKEN_ENV = "HUB_TEST_CF_TOKEN"  # nosec B105 — the env var NAME
ORIGIN_IPV4_ENV = "HUB_TEST_ORIGIN_IPV4"
ORIGIN_CA_ENV = "HUB_TEST_ORIGIN_CA_KEY"  # nosec B105 — the env var NAME
SKIP_REASON = (
    f"{TOKEN_ENV} not set: no test-zone credentials on this host "
    "(DNS-CF-T3-LIVE stays skipped-only; D-043 waiver)"
)


def token_ready():
    return bool(os.environ.get(TOKEN_ENV, "").strip())


@dataclass
class CfTestPlane:
    """Product adapter + the DnsZone row + names this run may create."""

    zone: object
    provider: object
    issuer: object = None
    names: list = field(default_factory=list)

    def track(self, name):
        if name not in self.names:
            self.names.append(name)
        return name


def reap_tracked_records(plane):
    """Delete every tracked name from the test zone; absent == success."""
    wanted = set(plane.names)
    if not wanted:
        return
    for rec in plane.provider.list_records(plane.zone):
        if rec["name"] in wanted:
            plane.provider.delete_record(plane.zone, rec["id"])


def origin_ipv4(vm=None):
    override = os.environ.get(ORIGIN_IPV4_ENV, "").strip()
    if override:
        return override
    if vm is not None:
        return vm.ipv4
    return ""


def _allowlist_zone(name):
    dj_settings.HUB_TEST_MODE = True
    slugs = list(getattr(dj_settings, "HUB_TEST_ZONE_SLUGS", None) or [])
    if name not in slugs:
        dj_settings.HUB_TEST_ZONE_SLUGS = [*slugs, name]


def build_cf_test_plane():
    """Vault the token, persist the one-zone DnsZone, construct via the registry."""
    from core.models import DnsAccount, DnsZone
    from providers.cloudflare import observe_token
    from providers.registry import dns_provider_for, origin_cert_issuer_for
    from vault import service as vault_service

    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(SKIP_REASON)
    observed = observe_token(token)
    if observed["status"] != "active":
        raise RuntimeError(
            f"test-zone token verify returned status {observed['status']!r}"
        )
    zones = observed["zones"]
    if len(zones) != 1:
        raise RuntimeError(
            f"test-zone token reached {len(zones)} zones; it must be scoped "
            "to exactly one purpose=test zone (D-046)"
        )
    info = zones[0]
    account = DnsAccount.objects.create(
        provider=DnsAccount.Provider.CLOUDFLARE, label=f"t17-{uuid.uuid4().hex[:8]}",
    )
    ref = f"t17-dns-{account.pk}"
    vault_service.put(
        kind="api_token", owner_type="dns_account", owner_id=ref,
        plaintext=token.encode(),
    )
    account.dns_token_ref = ref
    origin_ca = os.environ.get(ORIGIN_CA_ENV, "").strip()
    if origin_ca:
        oca_ref = f"t17-oca-{account.pk}"
        vault_service.put(
            kind="api_token", owner_type="dns_account", owner_id=oca_ref,
            plaintext=origin_ca.encode(),
        )
        account.origin_ca_key_ref = oca_ref
    account.save()
    zone = DnsZone.objects.create(
        account=account,
        name=info["name"],
        provider_zone_id=info["id"],
        purpose="test",
        proxied_default=True,
    )
    _allowlist_zone(zone.name)
    issuer = origin_cert_issuer_for(zone) if origin_ca else None
    return CfTestPlane(
        zone=zone, provider=dns_provider_for(zone), issuer=issuer,
    )


def _cf_test_zone_impl():
    """Yield the plane; finally reaps even when a test body fails."""
    plane = build_cf_test_plane()
    try:
        yield plane
    finally:
        reap_tracked_records(plane)


@pytest.fixture(scope="session")
def cf_test_zone(django_db_setup, django_db_blocker):
    """Session plane: product adapter + allowlisted purpose=test DnsZone."""
    if not token_ready():
        pytest.skip(SKIP_REASON)
    with django_db_blocker.unblock():
        yield from _cf_test_zone_impl()


def queued_public_site(vm, settings, *, slug, body, dns_zone):
    """A public Site bound to the allowlisted test DnsZone (not mesh_only)."""
    from core.models import Project, Site
    from deploys.models import Deployment, Manifest
    from tests.harness.t3_deploy import _vault_env_bundle, enroll_target

    target = enroll_target(vm, settings)
    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    domain = body.get("domain") or f"{slug}.{dns_zone.name}"
    site = Site.objects.create(
        project=project,
        name=slug,
        domain=domain,
        primary_target=target,
        dns_zone=dns_zone,
        exposure="public",
        proxied=True,
        deploy_strategy=Site.DeployStrategy.RECREATE,
        readiness_path=body.get("readiness_path") or "/healthz.ready",
        warmup_timeout_s=int(body.get("warmup_timeout_s") or 60),
    )
    body = dict(body)
    body["exposure"] = "public"
    body["domain"] = domain
    body.pop("caddy_listen", None)
    body = _vault_env_bundle(site, body)
    manifest = Manifest.objects.create(site=site, version=1, body=body)
    return site, target, Deployment.objects.create(manifest=manifest)


def public_site_body(slug, dns_zone, *, origin, ws=False):
    from tests.harness.t3_deploy import node_site_body, sample_site_body

    body = node_site_body(slug) if ws else sample_site_body(slug)
    body["exposure"] = "public"
    body["domain"] = f"{slug}.{dns_zone.name}"
    body["dns_values"] = [origin]
    body["dns_proxied"] = True
    body.pop("caddy_listen", None)
    return body


def install_security_headers(transport, server_id):
    """Attach HSTS on the product :443 server (Caddy sends none by default)."""
    import json

    probe = transport.probe(
        ["curl", "-sf", f"http://127.0.0.1:2019/config/apps/http/servers/{server_id}"]
    )
    if not probe.ok or not (probe.stdout or "").strip():
        raise AssertionError(f"no caddy server {server_id}: {probe.stderr}")
    server = json.loads(probe.stdout)
    routes = server.get("routes") or []
    if not routes:
        raise AssertionError(f"caddy server {server_id} has no routes")
    handle = list(routes[0].get("handle") or [])
    handle.insert(0, {
        "handler": "headers",
        "response": {"set": {"Strict-Transport-Security": ["max-age=300"]}},
    })
    routes[0]["handle"] = handle
    server["routes"] = routes
    remote = f"/tmp/t17-hdr-{server_id}.json"
    transport.put(json.dumps(server, sort_keys=True).encode(), remote)
    result = transport.run(
        [
            "curl", "-sf", "-X", "PUT",
            f"http://127.0.0.1:2019/config/apps/http/servers/{server_id}",
            "-H", "Content-Type: application/json",
            "--data-binary", f"@{remote}",
        ]
    )
    assert result.ok, f"caddy headers PUT failed: {result.stderr}"


def https_probe(transport, domain, path):
    """In-VM GET https:// with DNS pinned to loopback. -k: Origin CA is not public."""
    return transport.probe(
        [
            "curl", "-vsk", "-D", "-", "-o", "/dev/null",
            "--resolve", f"{domain}:443:127.0.0.1",
            f"https://{domain}{path}",
        ],
        timeout=60,
    )


def wss_one_frame(domain, path, *, deadline_s=120):
    """One wss:// upgrade and one frame, resolved through public DNS (CF edge)."""
    deadline = time.time() + deadline_s
    last_error = None
    while time.time() < deadline:
        try:
            return _wss_frame_once(domain, path)
        except (OSError, AssertionError) as error:
            last_error = error
            time.sleep(5)
    raise AssertionError(f"no wss frame from {domain}{path}: {last_error}")


def _wss_frame_once(domain, path, *, timeout=15):
    import base64
    import ssl

    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {domain}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    context = ssl.create_default_context()
    with socket.create_connection((domain, 443), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=domain) as sock:
            sock.sendall(request.encode())
            header = b""
            while b"\r\n\r\n" not in header:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                header += chunk
            assert b"\r\n\r\n" in header, "no handshake response"
            head, rest = header.split(b"\r\n\r\n", 1)
            status = head.split(b"\r\n", 1)[0]
            assert b"101" in status, status
            data = rest
            while len(data) < 2:
                more = sock.recv(4096)
                if not more:
                    break
                data += more
            assert len(data) >= 2, "no frame after handshake"
            length = data[1] & 0x7F
            assert length < 126, "fixture frame is expected to be short"
            while len(data) < 2 + length:
                more = sock.recv(4096)
                if not more:
                    break
                data += more
            return data[2 : 2 + length].decode("utf-8", "replace")

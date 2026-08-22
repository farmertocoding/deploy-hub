"""T3: HTTPS + LE staging + wss through CF+Caddy (HARNESS-T3-LE-STAGING).

Credential-gated (D-028 / D-031): every test here needs HUB_TEST_DNS_ZONE
(the Cloudflare TEST zone name) and HUB_TEST_CF_TOKEN (a token scoped to that
zone — never a prod token name). Absent credentials are skipped-only; check.py
refuses to green a tier:t3 req from a skip, and the D-031 waiver is the honest
record of that state — not a T1 sibling green.

Documented run preconditions (per the task brief):

- DNS records point at the Multipass IPv4, or at HUB_TEST_ORIGIN_IPV4 when
  set — that is the documented tunnel hook for a NAT'd host: run a tunnel
  (e.g. cloudflared) whose public IPv4 forwards :80/:443 to the VM and export
  it. LE staging HTTP-01 issuance and the proxied wss path both need the
  origin reachable from the internet.
- The test zone's SSL mode must be "Full" (not strict): the origin serves an
  LE STAGING cert, which the CF edge cannot verify against public roots.
- Security headers: Caddy does not send Strict-Transport-Security by default,
  so the test-plane :443 server sets it explicitly and the test asserts it.
- The :443 TLS server and the staging issuer are TEST-PLANE Caddy config,
  installed through Transport after a normal deploy. The product pipeline's
  route (and the Phase 3 Origin-cert work) stays untouched.
"""
from __future__ import annotations

import base64
import inspect
import json
import os
import socket
import ssl
import time
import uuid
from dataclasses import dataclass, field

import pytest

from tests.harness.multipass import multipass_available

pytest_plugins = ["tests.harness.t3_deploy"]

TOKEN_ENV = "HUB_TEST_CF_TOKEN"
ZONE_ENV = "HUB_TEST_DNS_ZONE"
ORIGIN_ENV = "HUB_TEST_ORIGIN_IPV4"
LE_STAGING_CA = "https://acme-staging-v02.api.letsencrypt.org/directory"
SKIP_REASON = (
    f"{ZONE_ENV} / {TOKEN_ENV} not set: no test-zone credentials on this host "
    "(HARNESS-T3-LE-STAGING stays skipped-only; D-031 waiver)"
)


def _zone_name():
    return os.environ.get(ZONE_ENV, "").strip()


def _credentialed():
    return bool(_zone_name() and os.environ.get(TOKEN_ENV, "").strip())


pytestmark = [
    pytest.mark.t3,
    # I1 (phase-3 Task 0): the t3 host gate must derive from
    # multipass_available() — the credential skipif below is this file's OWN
    # precondition (D-031), not the host gate, and alone it left these t3
    # marks collecting on a Multipass-less host.
    pytest.mark.skipif(not multipass_available(), reason="multipass is not available"),
    pytest.mark.skipif(not _credentialed(), reason=SKIP_REASON),
    pytest.mark.django_db,
]


@dataclass
class DnsPlane:
    """The provider plus every record name this test run may create."""

    provider: object
    zone: str
    names: list = field(default_factory=list)

    def track(self, name):
        if name not in self.names:
            self.names.append(name)
        return name


def reap_dns_names(provider, zone, names):
    """Delete every tracked name from the test zone; absent == success."""
    wanted = set(names)
    for rec in provider.list_records(zone):
        if rec["name"] in wanted:
            provider.delete_record(zone, rec["id"])


def _dns_plane_impl(settings):
    """Yield a DnsPlane; the finally reaps even when the test body fails."""
    from providers.test_dns import TestDnsProvider
    from tests.harness.t3_deploy import allow_test_zone

    settings.HUB_TEST_MODE = True
    # S1: the configured DNS zone must itself pass the allowlist — the
    # provider fails closed on a zone that is only named by the env var.
    allow_test_zone(settings, _zone_name())
    plane = DnsPlane(provider=TestDnsProvider(), zone=_zone_name())
    try:
        yield plane
    finally:
        reap_dns_names(plane.provider, plane.zone, plane.names)


@pytest.fixture
def dns_plane(settings):
    yield from _dns_plane_impl(settings)


def _origin_ipv4(vm):
    """The Multipass IPv4, or the documented tunnel's public IPv4."""
    return os.environ.get(ORIGIN_ENV, "").strip() or vm.ipv4


def _upsert_origin_records(plane, domain, vm, *, proxied):
    """A (and AAAA when the VM has a global IPv6) for domain → the origin.

    Under the tunnel override the AAAA is skipped: the VM's own IPv6 is not
    the tunnel's, and publishing it would race the tunnel for connections.
    """
    plane.track(domain)
    plane.provider.upsert_record(
        plane.zone, domain, "A", [_origin_ipv4(vm)], proxied=proxied
    )
    if os.environ.get(ORIGIN_ENV, "").strip():
        return
    ipv6 = _global_ipv6(vm)
    if ipv6:
        plane.provider.upsert_record(
            plane.zone, domain, "AAAA", [ipv6], proxied=proxied
        )


def _global_ipv6(vm):
    """The VM's global-scope IPv6, or "" when it has none (AAAA is then skipped)."""
    from tests.harness.multipass import exec_result

    result = exec_result(
        vm.mp(), ["ip", "-6", "-o", "addr", "show", "scope", "global"], timeout=30
    )
    for token in (result.stdout or "").split():
        if ":" in token and "/" in token:
            return token.split("/", 1)[0]
    return ""


def _install_le_staging_issuer(transport, domain):
    """Point Caddy's cert automation for `domain` at the LE STAGING CA.

    Config travels as a file + argv list through Transport, exactly like the
    pipeline's ensure_route_tls — never an interpolated shell string.
    """
    policy = {
        "automation": {
            "policies": [
                {
                    "subjects": [domain],
                    "issuers": [{"module": "acme", "ca": LE_STAGING_CA}],
                }
            ]
        }
    }
    remote = f"/tmp/t3-tls-{domain}.json"
    transport.put(json.dumps(policy, sort_keys=True).encode(), remote)
    result = transport.run(
        [
            "curl", "-sf", "-X", "PUT",
            "http://127.0.0.1:2019/config/apps/tls",
            "-H", "Content-Type: application/json",
            "--data-binary", f"@{remote}",
        ]
    )
    assert result.ok, f"caddy tls automation PUT failed: {result.stderr}"


def _install_https_server(transport, server_id, domain, upstream):
    """A test-plane :443 server: TLS + explicit HSTS + reverse_proxy.

    Separate from the pipeline-managed route (which disables automatic HTTPS
    on purpose — Origin-cert TLS is Phase 3). The HSTS header here is the
    documented security header the assertions below check.
    """
    server = {
        "@id": server_id,
        "listen": [":443"],
        "routes": [
            {
                "match": [{"host": [domain]}],
                "handle": [
                    {
                        "handler": "headers",
                        "response": {
                            "set": {"Strict-Transport-Security": ["max-age=300"]}
                        },
                    },
                    {
                        "handler": "reverse_proxy",
                        "upstreams": [{"dial": upstream}],
                    },
                ],
            }
        ],
    }
    remote = f"/tmp/t3-https-{server_id}.json"
    transport.put(json.dumps(server, sort_keys=True).encode(), remote)
    result = transport.run(
        [
            "curl", "-sf", "-X", "PUT",
            f"http://127.0.0.1:2019/config/apps/http/servers/{server_id}",
            "-H", "Content-Type: application/json",
            "--data-binary", f"@{remote}",
        ]
    )
    assert result.ok, f"caddy https server PUT failed: {result.stderr}"


def _https_probe(transport, domain, path):
    """In-VM GET https:// with DNS pinned to loopback.

    -k because LE STAGING is deliberately untrusted by system roots; the
    issuer assertion (STAGING in the verbose TLS log) is what proves staging.
    stdout carries the response headers, stderr the TLS handshake detail.
    """
    return transport.probe(
        [
            "curl", "-vsk", "-D", "-", "-o", "/dev/null",
            "--resolve", f"{domain}:443:127.0.0.1",
            f"https://{domain}{path}",
        ],
        timeout=60,
    )


def _wait_for_staging_https(transport, domain, path, *, deadline_s=240):
    """Poll until the staging cert is issued and the route answers 200."""
    deadline = time.time() + deadline_s
    last = None
    while time.time() < deadline:
        last = _https_probe(transport, domain, path)
        status_line = (last.stdout or "").split("\n", 1)[0]
        if last.ok and " 200" in status_line:
            return last
        time.sleep(5)
    raise AssertionError(
        f"https never answered 200 for {domain}: "
        f"stdout={getattr(last, 'stdout', '')!r} stderr={getattr(last, 'stderr', '')!r}"
    )


def _wss_frame_from_hub(domain, path, *, deadline_s=120):
    """One wss:// upgrade and one frame, resolved through public DNS.

    A proxied (orange-cloud) record makes this necessarily cross the
    Cloudflare edge before Caddy. The client is deliberately minimal:
    TLS with SNI, an RFC 6455 upgrade, then one short unmasked server frame.
    """
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


def _execute(deployment, target, dns):
    from deploys.pipeline import execute
    from tests.harness.t3_deploy import ssh_transport

    result = execute(deployment.pk, transport=ssh_transport(target), dns=dns)
    deployment.refresh_from_db()
    return result


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.skipif(not _credentialed(), reason=SKIP_REASON)
@pytest.mark.req("HARNESS-T3-LE-STAGING")
def test_https_and_security_headers_le_staging(t3_ready, settings, dns_plane):
    """DNS upsert → deploy → staging issuer → 200 + HSTS → v2 → rollback.

    What would make this fail: a prod-issuer fallback (no STAGING in the
    issuer), a route that drops the HSTS header, or rollback breaking HTTPS.
    """
    from deploys.models import Deployment
    from tests.harness.t3_deploy import (
        queued_site,
        sample_site_available,
        sample_site_body,
        ssh_transport,
    )

    assert sample_site_available(), (
        "sample-site/ must exist on this tree (Task 5); do not green "
        "HARNESS-T3-LE-STAGING from node-site alone"
    )
    slug = f"t3h{uuid.uuid4().hex[:6]}"
    domain = f"{slug}.{dns_plane.zone}"
    _upsert_origin_records(dns_plane, domain, t3_ready, proxied=False)

    body = sample_site_body(slug)
    _site, target, deployment = queued_site(t3_ready, settings, slug=slug, body=body)
    _execute(deployment, target, dns_plane.provider)
    assert deployment.status == Deployment.Status.SUCCEEDED

    transport = ssh_transport(target)
    _install_le_staging_issuer(transport, domain)
    _install_https_server(transport, f"t3https-{slug}", domain, "127.0.0.1:8000")

    response = _wait_for_staging_https(transport, domain, "/healthz.ready")
    headers = (response.stdout or "").lower()
    assert " 200" in headers.split("\n", 1)[0], response.stdout
    assert "strict-transport-security" in headers, response.stdout
    assert "STAGING" in (response.stderr or ""), (
        f"issuer is not LE staging: {response.stderr!r}"
    )

    second = Deployment.objects.create(manifest=deployment.manifest)
    _execute(second, target, dns_plane.provider)
    assert second.status == Deployment.Status.SUCCEEDED
    after_v2 = _https_probe(transport, domain, "/healthz.ready")
    assert " 200" in (after_v2.stdout or "").split("\n", 1)[0], after_v2.stdout

    rollback = Deployment.objects.create(
        manifest=deployment.manifest, rollback_of=deployment
    )
    _execute(rollback, target, dns_plane.provider)
    assert rollback.status == Deployment.Status.SUCCEEDED
    after_rollback = _https_probe(transport, domain, "/healthz.ready")
    assert " 200" in (after_rollback.stdout or "").split("\n", 1)[0], after_rollback.stdout


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.skipif(not _credentialed(), reason=SKIP_REASON)
@pytest.mark.req("HARNESS-T3-LE-STAGING")
def test_wss_one_frame_through_cf_caddy(t3_ready, settings, dns_plane):
    """One wss:// upgrade and one frame, Hub → CF edge → Caddy → node site.

    The node-site manifest declares ws and the record is proxied, so the
    frame necessarily crosses Cloudflare. What would make this fail: CF
    terminating the Upgrade, or Caddy dropping it.
    """
    from deploys.models import Deployment
    from tests.harness.t3_deploy import node_site_body, queued_site, ssh_transport

    slug = f"t3x{uuid.uuid4().hex[:6]}"
    domain = f"{slug}.{dns_plane.zone}"
    body = node_site_body(slug)
    assert body.get("ws") is True, "the node-site manifest must declare ws"
    _upsert_origin_records(dns_plane, domain, t3_ready, proxied=True)

    _site, target, deployment = queued_site(t3_ready, settings, slug=slug, body=body)
    _execute(deployment, target, dns_plane.provider)
    assert deployment.status == Deployment.Status.SUCCEEDED

    transport = ssh_transport(target)
    _install_le_staging_issuer(transport, domain)
    _install_https_server(transport, f"t3wss-{slug}", domain, "127.0.0.1:8080")
    _wait_for_staging_https(transport, domain, "/healthz.ready")

    frame = _wss_frame_from_hub(domain, "/ws/levels")
    assert "snapshot" in frame, frame


@pytest.mark.t3
@pytest.mark.skipif(not _credentialed(), reason=SKIP_REASON)
@pytest.mark.req("HARNESS-T3-LE-STAGING")
def test_dns_records_reaped_in_finally(dns_plane):
    """Every record the run tracked is reaped in the fixture's finally.

    What would make this fail: teardown skipping the reap on a failed body
    (no finally), or delete_record raising on an already-absent record.
    """
    name = dns_plane.track(f"t3reap{uuid.uuid4().hex[:6]}.{dns_plane.zone}")
    rid = dns_plane.provider.upsert_record(
        dns_plane.zone, name, "TXT", ["t12-reap-probe"]
    )
    assert rid
    present = [
        rec for rec in dns_plane.provider.list_records(dns_plane.zone)
        if rec["name"] == name
    ]
    assert present, "upsert did not land in the test zone"

    reap_dns_names(dns_plane.provider, dns_plane.zone, dns_plane.names)
    left = [
        rec for rec in dns_plane.provider.list_records(dns_plane.zone)
        if rec["name"] == name
    ]
    assert left == [], left
    # Absent == success: a second reap of the same names must not raise.
    reap_dns_names(dns_plane.provider, dns_plane.zone, dns_plane.names)

    source = inspect.getsource(_dns_plane_impl)
    assert "finally" in source
    assert "reap_dns_names" in source

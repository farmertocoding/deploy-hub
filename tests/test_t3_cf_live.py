"""T3: live product Cloudflare adapter + Origin cert (DNS-CF-T3-LIVE).

Credential-gated (D-034 / D-043): every test here needs HUB_TEST_CF_TOKEN
and a purpose=test DnsZone the token can reach. Absent credentials are
skipped-only; check.py refuses to green a tier:t3 req from a skip, and the
D-043 waiver is the honest record of that state — not a T1 sibling green.

The host gate derives from multipass_available() (I1). The credential skip
is this file's own precondition and is not the host gate.
"""
from __future__ import annotations

import inspect
import os
import socket
import time
import uuid

import pytest

from tests.harness.multipass import multipass_available

pytest_plugins = ["tests.harness.t3_deploy", "tests.harness.cf_zone"]

TOKEN_ENV = "HUB_TEST_CF_TOKEN"  # nosec B105 — the env var NAME
SKIP_REASON = (
    f"{TOKEN_ENV} not set: no test-zone credentials on this host "
    "(DNS-CF-T3-LIVE stays skipped-only; D-043 waiver)"
)


def token_ready():
    return bool(os.environ.get(TOKEN_ENV, "").strip())


pytestmark = [
    pytest.mark.t3,
    pytest.mark.skipif(not multipass_available(), reason="multipass is not available"),
    pytest.mark.skipif(not token_ready(), reason=SKIP_REASON),
    pytest.mark.django_db,
    pytest.mark.req("DNS-CF-T3-LIVE"),
]


def _wait_resolve(name, *, deadline_s=60):
    deadline = time.time() + deadline_s
    last = None
    while time.time() < deadline:
        try:
            return socket.getaddrinfo(name, 443)
        except OSError as error:
            last = error
            time.sleep(2)
    raise AssertionError(f"did not resolve {name}: {last}")


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.skipif(not token_ready(), reason=SKIP_REASON)
@pytest.mark.req("DNS-CF-T3-LIVE")
def test_product_adapter_upserts_and_deletes_in_the_test_zone(cf_test_zone):
    """upsert A proxied → list → resolve → delete. Product adapter only.

    What would make this fail: a second client (providers.test_dns) doing the
    writes, or a record that never becomes visible / never resolves.
    """
    from providers.cloudflare import CloudflareDnsProvider

    plane = cf_test_zone
    assert isinstance(plane.provider, CloudflareDnsProvider)
    name = plane.track(f"t17a{uuid.uuid4().hex[:6]}.{plane.zone.name}")
    rid = plane.provider.upsert_record(
        plane.zone, name, "A", ["192.0.2.17"], proxied=True,
    )
    assert rid
    present = [
        rec for rec in plane.provider.list_records(plane.zone)
        if rec["name"] == name
    ]
    assert present, "upsert did not land in the test zone"
    assert present[0]["proxied"] is True
    _wait_resolve(name)
    plane.provider.delete_record(plane.zone, present[0]["id"])
    left = [
        rec for rec in plane.provider.list_records(plane.zone)
        if rec["name"] == name
    ]
    assert left == [], left


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.skipif(not token_ready(), reason=SKIP_REASON)
@pytest.mark.req("DNS-CF-T3-LIVE")
def test_origin_cert_serves_https_with_security_headers(
    t3_ready, cf_test_zone, settings,
):
    """Origin cert issued and pushed → HTTPS 200 + HSTS; wss one frame if ws.

    What would make this fail: FakeOriginCertIssuer on the live path, a
    :443 route that never points at the pushed pair, or CF dropping Upgrade.
    """
    from deploys.models import Deployment
    from deploys.pipeline import execute
    from tests.harness.cf_zone import (
        https_probe,
        install_security_headers,
        origin_ipv4,
        public_site_body,
        queued_public_site,
        wss_one_frame,
    )
    from tests.harness.t3_deploy import ssh_transport

    plane = cf_test_zone
    if plane.issuer is None:
        pytest.skip("origin CA key not present; DNS upsert still proves the live adapter")
    slug = f"t17h{uuid.uuid4().hex[:6]}"
    origin = origin_ipv4(t3_ready)
    body = public_site_body(slug, plane.zone, origin=origin, ws=True)
    assert body.get("ws") is True
    domain = body["domain"]
    plane.track(domain)
    site, target, deployment = queued_public_site(
        t3_ready, settings, slug=slug, body=body, dns_zone=plane.zone,
    )
    assert site.exposure != "mesh_only"
    assert site.dns_zone_id == plane.zone.pk
    result = execute(
        deployment.pk,
        transport=ssh_transport(target),
        dns=plane.provider,
        cert_issuer=plane.issuer,
    )
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED, result

    transport = ssh_transport(target)
    install_security_headers(transport, f"site-{slug}")
    response = https_probe(transport, domain, "/healthz.ready")
    headers = (response.stdout or "").lower()
    assert " 200" in headers.split("\n", 1)[0], response.stdout
    assert "strict-transport-security" in headers, response.stdout

    frame = wss_one_frame(domain, "/ws/levels")
    assert "snapshot" in frame, frame


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.skipif(not token_ready(), reason=SKIP_REASON)
@pytest.mark.req("DNS-CF-T3-LIVE")
def test_records_reaped_in_finally(cf_test_zone):
    """Every record the run tracked is reaped in the fixture's finally.

    What would make this fail: teardown skipping the reap on a failed body
    (no finally), or delete_record raising on an already-absent record.
    """
    from tests.harness.cf_zone import _cf_test_zone_impl, reap_tracked_records

    plane = cf_test_zone
    name = plane.track(f"t17r{uuid.uuid4().hex[:6]}.{plane.zone.name}")
    rid = plane.provider.upsert_record(
        plane.zone, name, "TXT", ["t17-reap-probe"],
    )
    assert rid
    present = [
        rec for rec in plane.provider.list_records(plane.zone)
        if rec["name"] == name
    ]
    assert present, "upsert did not land in the test zone"

    reap_tracked_records(plane)
    left = [
        rec for rec in plane.provider.list_records(plane.zone)
        if rec["name"] == name
    ]
    assert left == [], left
    reap_tracked_records(plane)

    source = inspect.getsource(_cf_test_zone_impl)
    assert "finally" in source
    assert "reap_tracked_records" in source


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.skipif(not token_ready(), reason=SKIP_REASON)
@pytest.mark.req("DNS-CF-T3-LIVE")
def test_no_prod_zone_is_reachable_from_this_run(cf_test_zone, settings):
    """The bound client refuses a prod zone; construction stays triple-keyed.

    What would make this fail: the live run constructing a second client, or
    list/upsert accepting a purpose=prod DnsZone.
    """
    from core.models import DnsZone
    from core.test_mode import TestModeError
    from providers.cloudflare import CloudflareError
    from providers.registry import ScopeError, dns_provider_for
    from tests.harness import cf_zone as cf_zone_mod

    plane = cf_test_zone
    prod = DnsZone.objects.create(
        account=plane.zone.account,
        name=f"prod-closed-{uuid.uuid4().hex[:6]}.example",
        provider_zone_id="zid-prod-unreachable",
        purpose="prod",
    )
    with pytest.raises(CloudflareError):
        plane.provider.list_records(prod)

    settings.HUB_TEST_MODE = True
    with pytest.raises((TestModeError, ScopeError)):
        dns_provider_for(prod)

    source = inspect.getsource(cf_zone_mod)
    assert "dns_provider_for" in source
    assert "origin_cert_issuer_for" in source
    assert "CloudflareDnsProvider(" not in source
    assert "TestDnsProvider" not in source

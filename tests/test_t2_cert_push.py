"""T2: origin cert+key land 0400 in a 0700 dir; Caddy serves the pushed cert."""
from __future__ import annotations

import shutil
import subprocess
import time
import uuid

import pytest

pytest_plugins = ["tests.harness.target"]


def _docker_available():
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    return probe.returncode == 0


pytestmark = [
    pytest.mark.t2,
    pytest.mark.skipif(not _docker_available(), reason="docker is not available"),
    pytest.mark.req("TLS-B2-ORIGIN-CERT-PUSH"),
    pytest.mark.django_db,
]


def _target_and_site(hub_target, slug):
    from dns_fixtures import default_dns_zone

    from core.models import NetworkZone, Project, Site, Target
    from vault import service
    from vault.models import Secret

    owner_id = f"t2-tls-{uuid.uuid4().hex[:12]}"
    zone = NetworkZone.objects.create(name="t2", slug=f"t2-tls-{uuid.uuid4().hex[:8]}")
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=f"{hub_target.host}:{hub_target.port}",
        ssh_user=hub_target.user,
        ssh_key_ref=owner_id,
        host_key_fingerprint=hub_target.host_key_fingerprint,
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    service.put(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id=owner_id,
        plaintext=hub_target.client_key_pem,
    )
    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    site = Site.objects.create(
        project=project,
        name=slug,
        domain=f"{slug}.example.test",
        primary_target=target,
        dns_zone=default_dns_zone(f"{slug}.example.test"),
        proxied=True,
    )
    return target, site


def _desired(site, transport):
    from providers.fakes import FakeOriginCertIssuer

    return {
        "transport": transport,
        "site": site,
        "site_slug": site.name,
        "domain": site.domain,
        "dns_zone": site.dns_zone,
        "cert_issuer": FakeOriginCertIssuer(),
        "manifest_body": {"exposure": "public"},
        "proxied": True,
    }


@pytest.mark.req("TLS-B2-ORIGIN-CERT-PUSH")
def test_t2_cert_and_key_land_0400_in_a_0700_dir_on_hub_test_target(hub_target):
    """Live sshd: cert+key are 0400 root:root in a 0700 root:root tls dir.

    What would make this fail: SFTP writing 0644, a deploy-owned directory,
    or skipping the atomic mv so the final names never appear.
    """
    from core.ssh import SshTransport
    from deploys.certs import ensure_site_certificate
    from tests.harness.target import _exec

    slug = f"t2c{uuid.uuid4().hex[:6]}"
    target, site = _target_and_site(hub_target, slug)
    transport = SshTransport(target)
    ensure_site_certificate(_desired(site, transport))

    tls_dir = f"/srv/sites/{slug}/tls"
    stat_dir = _exec(
        hub_target.container,
        ["stat", "-c", "%a %U:%G", tls_dir],
        check=True,
    ).stdout.strip()
    assert stat_dir == "700 root:root"

    for name in ("cert.pem", "key.pem"):
        stat = _exec(
            hub_target.container,
            ["stat", "-c", "%a %U:%G", f"{tls_dir}/{name}"],
            check=True,
        ).stdout.strip()
        assert stat == "400 root:root", f"{name} was {stat}"


@pytest.mark.req("TLS-B2-ORIGIN-CERT-PUSH")
def test_t2_caddy_reload_serves_the_pushed_cert(hub_target):
    """Caddy reloads and presents the pushed certificate on HTTPS.

    What would make this fail: files on disk that Caddy never loads, or a
    reload that keeps serving the previous (or no) certificate.
    """
    import json

    from core.ssh import SshTransport
    from deploys.steps import ensure_route_tls
    from tests.harness.target import _wait_exec

    _wait_exec(
        hub_target.container,
        ["systemctl", "is-active", "caddy"],
        ready=lambda r: r.stdout.strip() == "active",
        deadline=time.time() + 60,
    )

    slug = f"t2s{uuid.uuid4().hex[:6]}"
    target, site = _target_and_site(hub_target, slug)
    transport = SshTransport(target)
    desired = _desired(site, transport)
    desired["caddy_route"] = json.dumps({
        "@id": f"site-{slug}",
        "listen": [":443"],
        "automatic_https": {"disable": True},
        "routes": [{
            "match": [{"host": [site.domain]}],
            "handle": [{
                "handler": "static_response",
                "status_code": 200,
                "body": "tls-ok",
            }],
        }],
    })
    ensure_route_tls(desired)

    domain = site.domain
    served = transport.probe([
        "curl", "-sfk", "--resolve", f"{domain}:443:127.0.0.1",
        f"https://{domain}/",
    ])
    assert served.ok, served.stderr
    assert "tls-ok" in (served.stdout or "")

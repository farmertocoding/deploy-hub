"""T1 Fake CustomHostname: TXT-before-serve on the dns_provider_for object.

Live CF-for-SaaS is not this task. Function-level PART-CUSTOM-HOSTNAME
markers only on the named tests.
"""
import ast
import pathlib

import pytest
from django.test import override_settings
from test_dns_zone_wall import TOKEN, _http, _routes, _zone

REPO = pathlib.Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.django_db


def _fake(*, custom_hostname=True):
    from providers.fakes import FakeDnsProvider

    return FakeDnsProvider(custom_hostname=custom_hostname)


@pytest.mark.req("PART-CUSTOM-HOSTNAME")
def test_unverified_hostname_is_not_served():
    """Create without TXT ownership must not produce a Caddy route.

    What would make this fail: serving on create so an unverified client
    domain becomes a phishing factory on the fleet IPs.
    """
    from providers.custom_hostname import caddy_route_for

    dns = _fake()
    hostname = "app.client.example"
    dns.create_custom_hostname(hostname)
    assert dns.custom_hostname_status(hostname) != "active"
    assert caddy_route_for(dns, hostname) is None
    assert dns.serve_custom_hostname(hostname) is None


@pytest.mark.req("PART-CUSTOM-HOSTNAME")
def test_txt_before_serve():
    """TXT ownership is the gate: nothing is served until the record exists.

    What would make this fail: flipping status to active on create, or
    serving from hostname presence rather than the ownership TXT.
    """
    from providers.custom_hostname import caddy_route_for

    dns = _fake()
    hostname = "shop.client.example"
    created = dns.create_custom_hostname(hostname)
    txt = dns.custom_hostname_txt(hostname)
    assert txt["type"] == "txt"
    assert txt["name"]
    assert txt["value"]
    assert created["ownership_verification"]["value"] == txt["value"]
    assert caddy_route_for(dns, hostname) is None

    dns.upsert_record("zone", txt["name"], "TXT", [txt["value"]])
    assert dns.custom_hostname_status(hostname) == "active"
    route = caddy_route_for(dns, hostname)
    assert route is not None
    hosts = route["match"][0]["host"]
    assert hostname in hosts
    served = dns.serve_custom_hostname(hostname)
    assert served == route


@pytest.mark.req("PART-CUSTOM-HOSTNAME")
def test_custom_hostname_is_capability_on_dns_provider_for_object(monkeypatch):
    """custom_hostname lives on the dns_provider_for object (or flagged Fake).

    What would make this fail: a parallel CustomHostname client, or adding
    the flag to Fake-without-the-flag / constructing CF outside the registry.
    """
    from providers.fakes import FakeDnsProvider
    from providers.registry import dns_provider_for, reset_scope_cache

    plain = FakeDnsProvider()
    assert "custom_hostname" not in plain.capabilities()
    flagged = FakeDnsProvider(custom_hostname=True)
    assert "custom_hostname" in flagged.capabilities()
    for name in ("create_custom_hostname", "custom_hostname_status",
                 "custom_hostname_txt"):
        assert callable(getattr(flagged, name))

    reset_scope_cache()
    zone = _zone(name="saas.example", zone_id="zid-saas", token=TOKEN)
    _http(monkeypatch, _routes(zone))
    with override_settings(HUB_TEST_MODE=False):
        provider = dns_provider_for(zone)
    assert "custom_hostname" in provider.capabilities()
    for name in ("create_custom_hostname", "custom_hostname_status",
                 "custom_hostname_txt"):
        assert callable(getattr(provider, name))


@pytest.mark.req("PART-CUSTOM-HOSTNAME")
def test_helpers_do_not_construct_a_cloudflare_client():
    """providers/custom_hostname.py is helpers only — no CF client, no vault.

    What would make this fail: helpers calling CloudflareDnsProvider(...)
    or api_request, skipping dns_provider_for's scope wall.
    """
    path = REPO / "providers" / "custom_hostname.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden_names = {
        "CloudflareDnsProvider", "CloudflareEdge", "CloudflareOriginCertIssuer",
        "api_request", "observe_token", "urlopen", "dns_provider_for",
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in forbidden_names:
                found.append(f"{name}:{node.lineno}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", None) or ""
            names = [alias.name for alias in node.names]
            joined = ".".join([mod, *names])
            if "cloudflare" in joined.lower() and "custom_hostname" not in joined:
                found.append(f"import:{joined}")
            if "vault" in joined.split("."):
                found.append(f"import:{joined}")
    assert found == [], found
    assert "api_request" not in src
    assert "CloudflareDnsProvider" not in src


@pytest.mark.req("PART-CUSTOM-HOSTNAME")
def test_route53_has_no_custom_hostname_capability():
    """Route 53 capabilities still omit custom_hostname (D-079).

    What would make this fail: advertising the SaaS flag on Route 53 so
    ensure-path code thinks TXT-before-serve exists there.
    """
    from providers.fakes import FakeDnsProvider
    from providers.route53 import (
        Route53DnsProvider,
        create_test_hosted_zone,
        mock_aws_route53,
    )

    assert "custom_hostname" not in FakeDnsProvider().capabilities()
    name = "r53-saas.example"
    with mock_aws_route53():
        zid = create_test_hosted_zone(name)
        from core.models import DnsAccount, DnsZone

        account = DnsAccount.objects.create(
            provider=DnsAccount.Provider.ROUTE53, label="r53-saas",
        )
        zone = DnsZone.objects.create(
            account=account, name=name, provider_zone_id=zid, purpose="prod",
        )
        provider = Route53DnsProvider(
            zone,
            access_key_id="t1-r53-access-key-id-not-a-credential",
            secret_access_key="t1-r53-secret-access-key-not-a-credential",
        )
        assert "custom_hostname" not in provider.capabilities()


@pytest.mark.req("PART-CUSTOM-HOSTNAME")
def test_no_acme_or_dns01_in_custom_hostname_module():
    """No new ACME / DNS-01 in the CustomHostname helpers.

    What would make this fail: sneaking Let's Encrypt or Hub-central
    DNS-01 into this module so CF-for-SaaS grows a second cert path.
    """
    src = (REPO / "providers" / "custom_hostname.py").read_text(encoding="utf-8").lower()
    for needle in ("acme", "dns-01", "dns01", "dns_01", "letsencrypt", "let's encrypt"):
        assert needle not in src, needle


def test_custom_hostname_refuses_non_partner_site_domain():
    """Partner-base ≠ a non-partner Site domain (C5/C7; Task 4 refuse).

    What would make this fail: issuing a custom hostname that collides with
    Joseph's prod Site.domain, sharing cookie + reputation with the fleet.
    """
    from core.models import Project, Site
    from providers.custom_hostname import CustomHostnameError

    project = Project.objects.create(name="prod", slug="prod-ch")
    Site.objects.create(
        project=project, name="prod-site", domain="joseph.example",
        exposure=Site.Exposure.MESH_ONLY,
    )
    dns = _fake()
    with pytest.raises(CustomHostnameError):
        dns.create_custom_hostname("joseph.example")

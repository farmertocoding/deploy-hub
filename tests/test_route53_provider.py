"""T1: Route 53 DnsProvider adapter (D-065 / AWS-R53-ADAPTER).

boto3, botocore, and moto must not appear as imports in this file. Dummy
creds, the moto 5.x context, and hosted-zone allocation live in
providers/route53.py so the tested client is the shipped client.
"""
import ast
import json
import pathlib
import re

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
REF = "hub-aws-r53"
AKI = "t1-r53-access-key-id-not-a-credential"
SAK = "t1-r53-secret-access-key-not-a-credential"
EDGE_TOKEN = "cf-edge-t1-r53-token-not-a-credential"  # nosec B105
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)


def _put_aws(*, owner_id=REF):
    from vault import service as vault_service
    from vault.models import Secret

    return vault_service.put(
        kind=Secret.Kind.CLOUD_CREDENTIAL,
        owner_type="aws",
        owner_id=owner_id,
        plaintext=json.dumps(
            {"access_key_id": AKI, "secret_access_key": SAK}
        ).encode(),
    )


def _account(*, dns_token_ref=REF, edge_token_ref="", label="r53-acct"):
    from core.models import DnsAccount

    return DnsAccount.objects.create(
        provider=DnsAccount.Provider.ROUTE53,
        label=label,
        dns_token_ref=dns_token_ref,
        edge_token_ref=edge_token_ref,
    )


def _zone(account, *, name, provider_zone_id, purpose="prod"):
    from core.models import DnsZone

    return DnsZone.objects.create(
        account=account,
        name=name,
        provider_zone_id=provider_zone_id,
        purpose=purpose,
    )


def _attr_loads(source, name):
    tree = ast.parse(source)
    return any(
        isinstance(node, ast.Attribute) and node.attr == name
        for node in ast.walk(tree)
    )


def _func_source(path, func_name):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment(src, node) or ast.unparse(node)
    return ""


@pytest.mark.req("AWS-R53-ADAPTER")
def test_route53_is_not_edge_protection():
    """Route 53 implements DnsProvider only; it is not EdgeProtection (C7).

    What would make this fail: subclassing EdgeProtection so L5 could call
    set_security_level / ban_ip on a Route 53 zone, or dropping DnsProvider.
    """
    from providers.base import DnsProvider, EdgeProtection
    from providers.route53 import Route53DnsProvider

    assert issubclass(Route53DnsProvider, DnsProvider)
    assert not issubclass(Route53DnsProvider, EdgeProtection)
    assert EdgeProtection not in Route53DnsProvider.__mro__
    assert not hasattr(Route53DnsProvider, "set_security_level")
    assert not hasattr(Route53DnsProvider, "ban_ip")
    assert not hasattr(Route53DnsProvider, "purge_cache")


@pytest.mark.req("AWS-R53-ADAPTER")
def test_upsert_proxied_true_raises():
    """proxied=True raises and must not silently write an unproxied A (C7).

    What would make this fail: ignoring the flag and UPSERT-ing an ordinary
    A, so a Cloudflare-proxied site pointed at Route 53 looks converged.
    """
    from providers.route53 import (
        Route53DnsProvider,
        Route53Error,
        create_test_hosted_zone,
        mock_aws_route53,
    )

    name = "r53-proxied.example"
    with mock_aws_route53():
        zid = create_test_hosted_zone(name)
        zone = _zone(_account(label="r53-proxied"), name=name, provider_zone_id=zid)
        provider = Route53DnsProvider(
            zone, access_key_id=AKI, secret_access_key=SAK,
        )
        with pytest.raises(Route53Error, match="proxied"):
            provider.upsert_record(
                zone, f"www.{name}", "A", ["203.0.113.10"], proxied=True,
            )
        a_rows = [
            rec for rec in provider.list_records(zone)
            if rec["rtype"] == "A" and rec["name"].rstrip(".").lower()
            == f"www.{name}"
        ]
        assert a_rows == [], a_rows


@pytest.mark.req("AWS-R53-ADAPTER")
def test_capabilities_omit_proxied():
    """capabilities() does not advertise proxied; FakeDnsProvider still does.

    What would make this fail: returning {proxied} so ensure_dns treats
    Route 53 like Cloudflare orange-cloud, or dropping proxied from the fake.
    """
    from providers.fakes import FakeDnsProvider
    from providers.route53 import (
        Route53DnsProvider,
        create_test_hosted_zone,
        mock_aws_route53,
    )

    assert "proxied" in FakeDnsProvider().capabilities()
    name = "r53-caps.example"
    with mock_aws_route53():
        zid = create_test_hosted_zone(name)
        zone = _zone(_account(label="r53-caps"), name=name, provider_zone_id=zid)
        provider = Route53DnsProvider(
            zone, access_key_id=AKI, secret_access_key=SAK,
        )
        assert "proxied" not in provider.capabilities()


@pytest.mark.req("AWS-R53-ADAPTER")
def test_dns_provider_for_route53_fail_closed():
    """Matching dns_token_ref + CLOUD_CREDENTIAL + hosted zone, or no client.

    What would make this fail: constructing from leftover CLOUD_CREDENTIAL
    when AWS_CREDENTIALS_REF is empty, copying that secret into an API_TOKEN
    row, or returning a client when GetHostedZone name ≠ DnsZone.name.
    """
    from core.models import Finding
    from providers.aws_creds import last_client_kwargs, reset_client_log
    from providers.registry import ScopeError, dns_provider_for
    from providers.route53 import (
        Route53DnsProvider,
        create_test_hosted_zone,
        mock_aws_route53,
    )
    from vault.models import Secret

    name = "r53-failclosed.example"
    _put_aws(owner_id="leftover-r53")
    account = _account(dns_token_ref=REF, label="r53-fc")
    zone = _zone(account, name=name, provider_zone_id="ZLEFTOVER")
    with override_settings(AWS_CREDENTIALS_REF=""):
        with pytest.raises(ScopeError, match="AWS_CREDENTIALS_REF|HUB_AWS_CREDENTIALS_REF"):
            dns_provider_for(zone)

    _put_aws()
    with override_settings(AWS_CREDENTIALS_REF=REF):
        with pytest.raises(ScopeError, match="cloud_credential|vault"):
            dns_provider_for(_zone(
                _account(label="r53-missing-secret"),
                name="r53-missing.example",
                provider_zone_id="ZMISSING",
            ))

        with mock_aws_route53():
            zid = create_test_hosted_zone(name)
            mismatch = _zone(
                _account(label="r53-mismatch"),
                name="r53-other.example",
                provider_zone_id=zid,
            )
            with pytest.raises(ScopeError):
                dns_provider_for(mismatch)
            finding = Finding.objects.get(fingerprint=f"r53-fail:{mismatch.pk}")
            blob = f"{finding.title}\n{finding.body}\n{finding.fix_action}"
            assert AKI not in blob
            assert SAK not in blob
            assert str(mismatch.pk) in finding.fingerprint

            reset_client_log()
            bound = _zone(_account(label="r53-ok"), name=name, provider_zone_id=zid)
            provider = dns_provider_for(bound)
            assert isinstance(provider, Route53DnsProvider)
            kwargs = last_client_kwargs()
            assert kwargs is not None
            assert kwargs["aws_access_key_id"] == AKI
            assert kwargs["aws_secret_access_key"] == SAK
            assert "aws_session_token" not in kwargs
            assert not Secret.objects.filter(kind=Secret.Kind.API_TOKEN).exists()
            assert Secret.objects.filter(
                kind=Secret.Kind.CLOUD_CREDENTIAL,
                owner_type="aws",
                owner_id=REF,
            ).exists()


@pytest.mark.req("AWS-R53-ADAPTER")
def test_dns_provider_for_unknown_provider_still_refuses():
    """A provider that is not cloudflare or route53 still fails closed.

    What would make this fail: the Route 53 branch replacing the unknown
    refusal so 'gandi' constructs a client, or a silent None.
    """
    from core.models import DnsAccount, DnsZone
    from providers.registry import ScopeError, dns_provider_for

    account = DnsAccount.objects.create(provider="gandi", label="gandi-unknown")
    zone = DnsZone.objects.create(
        account=account, name="gandi-unknown.example", provider_zone_id="zid-gandi",
    )
    with pytest.raises(ScopeError, match="no DNS provider adapter"):
        dns_provider_for(zone)


@pytest.mark.req("AWS-R53-ADAPTER")
def test_edge_ref_on_route53_account_raises():
    """edge_protection_for raises on Route 53 when an edge ref is present (C6).

    What would make this fail: returning a silent no-op EdgeProtection, or
    loading the AWS CLOUD_CREDENTIAL as an edge token. Absent ref stays None.
    """
    from providers.registry import ScopeError, edge_protection_for

    present = _zone(
        _account(dns_token_ref=REF, edge_token_ref="edge-should-not-load",
                 label="r53-edge-present"),
        name="r53-edge-present.example",
        provider_zone_id="ZEDGEPRESENT",
    )
    with pytest.raises(ScopeError, match="no edge protection adapter"):
        edge_protection_for(present)

    absent = _zone(
        _account(dns_token_ref=REF, edge_token_ref="", label="r53-edge-absent"),
        name="r53-edge-absent.example",
        provider_zone_id="ZEDGEABSENT",
    )
    assert edge_protection_for(absent) is None


@pytest.mark.req("AWS-R53-ADAPTER")
def test_route53_never_loads_edge_token_ref():
    """dns_provider_for(Route 53) never reads edge_token_ref (C6 / D-057).

    What would make this fail: construct loading edge_token_ref so a
    Firewall-edit token or the AWS credential rides the DNS adapter.
    """
    from providers.aws_creds import last_client_kwargs, reset_client_log
    from providers.registry import dns_provider_for
    from providers.route53 import (
        Route53DnsProvider,
        create_test_hosted_zone,
        mock_aws_route53,
    )
    from vault import service as vault_service
    from vault.models import Secret

    route53_src = (REPO / "providers" / "route53.py").read_text(encoding="utf-8")
    assert not _attr_loads(route53_src, "edge_token_ref")
    ctor_src = _func_source(REPO / "providers" / "registry.py", "dns_provider_for")
    helper_src = _func_source(
        REPO / "providers" / "registry.py", "_route53_dns_provider_for",
    )
    assert not _attr_loads(ctor_src, "edge_token_ref")
    if helper_src:
        assert not _attr_loads(helper_src, "edge_token_ref")

    vault_service.put(
        kind=Secret.Kind.API_TOKEN,
        owner_type="dns_account",
        owner_id="edge-r53-wall",
        plaintext=EDGE_TOKEN.encode(),
    )
    _put_aws()
    name = "r53-edge-wall.example"
    with mock_aws_route53():
        zid = create_test_hosted_zone(name)
        zone = _zone(
            _account(
                dns_token_ref=REF,
                edge_token_ref="edge-r53-wall",
                label="r53-edge-wall",
            ),
            name=name,
            provider_zone_id=zid,
        )
        reset_client_log()
        with override_settings(AWS_CREDENTIALS_REF=REF):
            provider = dns_provider_for(zone)
        assert isinstance(provider, Route53DnsProvider)
        kwargs = last_client_kwargs()
        blob = json.dumps(kwargs)
        assert AKI in blob
        assert EDGE_TOKEN not in blob
        assert EDGE_TOKEN not in repr(provider)
        assert EDGE_TOKEN not in str(provider)


@pytest.mark.req("AWS-R53-ADAPTER")
def test_dns_token_ref_must_equal_aws_credentials_ref():
    """DnsAccount.dns_token_ref must be the same owner-id as AWS_CREDENTIALS_REF.

    What would make this fail: loading CLOUD_CREDENTIAL by a different
    dns_token_ref, or copying it into an API_TOKEN row so the CF loader
    can pick it up.
    """
    from providers.registry import ScopeError, dns_provider_for
    from vault.models import Secret

    _put_aws()
    zone = _zone(
        _account(dns_token_ref="other-aws-ref", label="r53-ref-mismatch"),
        name="r53-ref-mismatch.example",
        provider_zone_id="ZREFMISMATCH",
    )
    with override_settings(AWS_CREDENTIALS_REF=REF):
        with pytest.raises(ScopeError, match="dns_token_ref|AWS_CREDENTIALS_REF"):
            dns_provider_for(zone)
    assert not Secret.objects.filter(kind=Secret.Kind.API_TOKEN).exists()
    assert Secret.objects.filter(
        kind=Secret.Kind.CLOUD_CREDENTIAL, owner_type="aws", owner_id=REF,
    ).exists()


@pytest.mark.req("AWS-R53-ADAPTER")
def test_changes_are_scoped_to_provider_zone_id():
    """Mutations go only to DnsZone.provider_zone_id; a different zone refuses.

    What would make this fail: ChangeResourceRecordSets on * or on a second
    hosted zone the Hub user can see, so one DnsZone row authorizes another.
    """
    from providers.route53 import (
        Route53DnsProvider,
        Route53Error,
        create_test_hosted_zone,
        mock_aws_route53,
    )

    name_a = "r53-scope-a.example"
    name_b = "r53-scope-b.example"
    with mock_aws_route53():
        zid_a = create_test_hosted_zone(name_a)
        zid_b = create_test_hosted_zone(name_b)
        zone_a = _zone(_account(label="r53-scope-a"), name=name_a, provider_zone_id=zid_a)
        zone_b = _zone(_account(label="r53-scope-b"), name=name_b, provider_zone_id=zid_b)
        provider_a = Route53DnsProvider(
            zone_a, access_key_id=AKI, secret_access_key=SAK,
        )
        provider_b = Route53DnsProvider(
            zone_b, access_key_id=AKI, secret_access_key=SAK,
        )
        rid = provider_a.upsert_record(
            zone_a, f"www.{name_a}", "A", ["203.0.113.10"],
        )
        assert rid
        with pytest.raises(Route53Error, match="bound to zone"):
            provider_a.upsert_record(
                zone_b, f"www.{name_b}", "A", ["198.51.100.10"],
            )
        names_a = {
            rec["name"].rstrip(".").lower()
            for rec in provider_a.list_records(zone_a)
            if rec["rtype"] == "A"
        }
        names_b = {
            rec["name"].rstrip(".").lower()
            for rec in provider_b.list_records(zone_b)
            if rec["rtype"] == "A"
        }
        assert f"www.{name_a}" in names_a
        assert f"www.{name_b}" not in names_b
        assert f"www.{name_a}" not in names_b


def test_route53_tests_do_not_import_boto3():
    """This module never imports boto3/moto; the moto helper lives in route53.py.

    What would make this fail: a convenience `import boto3` here, so the
    tested client is no longer the shipped adapter (the D-034 split).
    """
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(text) is None
    offenders = []
    for py in (REPO / "tests").rglob("*.py"):
        if _IMPORT_BOTO.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(REPO)))
    assert offenders == [], f"boto3/botocore/moto import in tests/: {offenders}"

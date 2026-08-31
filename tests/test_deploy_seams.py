"""Process-boundary deploy seams: never a silent Fake in prod (phase-exit C1/I5).

run_deploy / execute(pk) without injected dns=/cert_issuer= must construct
through dns_provider_for / origin_cert_issuer_for when the refs exist, and
fail closed (Finding + refuse) when they do not. --fake and explicit
injection stay for T1/T2.
"""
import pytest
from pipeline_fakes import PipelineTransport, queued_deployment

from core.models import Finding
from providers.fakes import FakeDnsProvider, FakeOriginCertIssuer

pytestmark = pytest.mark.django_db


def _track_fakes(monkeypatch):
    """Count FakeDnsProvider / FakeOriginCertIssuer constructions."""
    import providers.fakes as fakes

    counts = {"dns": 0, "issuer": 0}
    real_dns = fakes.FakeDnsProvider.__init__
    real_issuer = fakes.FakeOriginCertIssuer.__init__

    def dns_init(self, *args, **kwargs):
        counts["dns"] += 1
        return real_dns(self, *args, **kwargs)

    def issuer_init(self, *args, **kwargs):
        counts["issuer"] += 1
        return real_issuer(self, *args, **kwargs)

    monkeypatch.setattr(fakes.FakeDnsProvider, "__init__", dns_init)
    monkeypatch.setattr(fakes.FakeOriginCertIssuer, "__init__", issuer_init)
    return counts


def _plant_refs(site, *, dns=True, origin_ca=True):
    from vault import service as vault_service

    account = site.dns_zone.account
    if dns:
        ref = f"dnsacct-{account.pk}-dns"
        vault_service.put(
            kind="api_token", owner_type="dns_account", owner_id=ref,
            plaintext=b"t1-seam-dns-token-not-a-credential",
        )
        account.dns_token_ref = ref
    if origin_ca:
        ref = f"dnsacct-{account.pk}-oca"
        vault_service.put(
            kind="api_token", owner_type="dns_account", owner_id=ref,
            plaintext=b"t1-seam-oca-key-not-a-credential",
        )
        account.origin_ca_key_ref = ref
    account.save()
    return account


def test_execute_without_injected_seams_constructs_through_real_factories(monkeypatch):
    """Refs present: execute(pk) with no dns=/cert_issuer= goes through the
    registry factories, never _default_dns / _default_cert_issuer.

    What would make this fail: execute filling both seams from FakeDnsProvider
    / FakeOriginCertIssuer so production upserts in-memory and mints a local
    leaf.
    """
    from deploys.pipeline import execute
    from deploys.tasks import run_deploy

    constructed = []

    def dns_for(zone):
        constructed.append(("dns", zone.pk))
        return FakeDnsProvider()

    def issuer_for(zone):
        constructed.append(("issuer", zone.pk))
        return FakeOriginCertIssuer()

    monkeypatch.setattr("deploys.seams.dns_provider_for", dns_for)
    monkeypatch.setattr("deploys.seams.origin_cert_issuer_for", issuer_for)

    site, deployment = queued_deployment("seam-ok")
    _plant_refs(site)
    result = execute(deployment.pk, transport=PipelineTransport())
    deployment.refresh_from_db()
    assert deployment.status == "succeeded", result
    assert ("dns", site.dns_zone_id) in constructed
    assert ("issuer", site.dns_zone_id) in constructed

    constructed.clear()
    site2, deployment2 = queued_deployment("seam-ok-task")
    _plant_refs(site2)
    monkeypatch.setattr(
        "deploys.pipeline._default_transport",
        lambda site: PipelineTransport(),
    )
    from deploys.tasks import envelope_for_deploy

    run_deploy(deployment2.pk, envelope_for_deploy(deployment2.pk))
    deployment2.refresh_from_db()
    assert deployment2.status == "succeeded"
    assert ("dns", site2.dns_zone_id) in constructed
    assert ("issuer", site2.dns_zone_id) in constructed


def test_execute_without_refs_refuses_and_does_not_fake(monkeypatch):
    """No token refs: execute(pk) files a Finding and refuses. No Fake client.

    What would make this fail: falling through to _default_dns / FakeOriginCertIssuer
    so a Settings-connected (or unconnected) site deploys a local no-op.
    """
    from deploys.pipeline import DeploySeamRefused, execute

    counts = _track_fakes(monkeypatch)
    site, deployment = queued_deployment("seam-refuse")
    account = site.dns_zone.account
    assert not account.dns_token_ref
    assert not account.origin_ca_key_ref

    with pytest.raises(DeploySeamRefused, match="dns_token_ref|origin_ca_key_ref"):
        execute(deployment.pk, transport=PipelineTransport())

    deployment.refresh_from_db()
    assert deployment.status == "failed"
    row = Finding.objects.filter(fingerprint=f"deploy-seam:{site.pk}").get()
    assert row.severity == Finding.Severity.P2
    assert "dns_token_ref" in row.body
    assert "origin_ca_key_ref" in row.body
    assert counts["dns"] == 0
    assert counts["issuer"] == 0


def test_missing_origin_ca_key_ref_fails_closed_and_names_it(monkeypatch):
    """Settings-connect writes dns_token_ref only. Origin certs must refuse
    by name, not mint a local leaf (phase-exit I5).

    What would make this fail: constructing FakeOriginCertIssuer when
    origin_ca_key_ref is empty, or a refusal that does not name the missing ref.
    """
    from deploys.pipeline import DeploySeamRefused, execute

    factory_calls = []

    def dns_for(zone):
        factory_calls.append("dns")
        return FakeDnsProvider()

    def issuer_for(zone):
        factory_calls.append("issuer")
        return FakeOriginCertIssuer()

    monkeypatch.setattr("deploys.seams.dns_provider_for", dns_for)
    monkeypatch.setattr("deploys.seams.origin_cert_issuer_for", issuer_for)
    counts = _track_fakes(monkeypatch)

    site, deployment = queued_deployment("seam-no-oca")
    _plant_refs(site, dns=True, origin_ca=False)
    assert site.dns_zone.account.dns_token_ref
    assert not site.dns_zone.account.origin_ca_key_ref

    with pytest.raises(DeploySeamRefused, match="origin_ca_key_ref"):
        execute(deployment.pk, transport=PipelineTransport())

    deployment.refresh_from_db()
    assert deployment.status == "failed"
    row = Finding.objects.get(fingerprint=f"deploy-seam:{site.pk}")
    assert "origin_ca_key_ref" in row.title or "origin_ca_key_ref" in row.body
    assert "origin_ca_key_ref" in row.fix_action
    assert "issuer" not in factory_calls
    assert counts["issuer"] == 0


def test_injected_seams_still_skip_the_factory(monkeypatch):
    """T1/T2 injection and --fake stay: explicit dns=/cert_issuer= must not
    call the product factories.
    """
    from deploys.pipeline import execute

    def boom(zone):
        raise AssertionError("factory must not run when seams are injected")

    monkeypatch.setattr("deploys.seams.dns_provider_for", boom)
    monkeypatch.setattr("deploys.seams.origin_cert_issuer_for", boom)

    _site, deployment = queued_deployment("seam-inject")
    result = execute(
        deployment.pk,
        transport=PipelineTransport(),
        dns=FakeDnsProvider(),
        cert_issuer=FakeOriginCertIssuer(),
    )
    deployment.refresh_from_db()
    assert deployment.status == "succeeded", result

"""Abandoned-flip reaper (Phase 3b Task 7 / design note §1.1(c), §7 S4).

A CheckRun(kind=adopt) older than 24 h from results.started_at calls
adopt_flow.cleanup — the one owner. Public rows still naming a temp_name
lose that hostname; mesh-only empty temp_name still gets container cleanup.
Failed cleanup files adopt-temp-orphan:{site_pk}:{name} (P2). The provider
is reconstructed from Site.dns_zone; a token is never persisted.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from test_adopt_flow import (
    ADOPT_RESULT_KEYS,
    AdoptTransport,
    _checkrun,
    _desired,
    _prod_values,
    _site,
    _volume_rm_argvs,
)

from providers.fakes import FakeDnsProvider

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.req("PROV-E6-ADOPT-TEMP-SUBDOMAIN"),
]

PLANTED_TOKEN = "cf-dns-reaper-must-not-persist-7e1b"  # nosec B105


class BoomOnDelete(FakeDnsProvider):
    """Provider that keeps the temp record when delete is refused."""

    def delete_record(self, zone, record_id):
        self.calls.append(("delete_record", zone, record_id))
        raise RuntimeError("provider delete failed")


def _age_started(site, hours):
    run = _checkrun(site)
    results = dict(run.results)
    results["started_at"] = (timezone.now() - timedelta(hours=hours)).isoformat()
    run.results = results
    run.save(update_fields=["results"])
    return run


def _wire(monkeypatch, transport, dns):
    """Reaper reconstructs seams; tests inject the in-memory provider/transport."""
    import deploys.adopt_reaper as reaper

    monkeypatch.setattr(reaper, "dns_provider_for", lambda zone: dns)
    monkeypatch.setattr(
        reaper,
        "resolve_production_seams",
        lambda site: (
            (None, None)
            if getattr(site, "exposure", None) == "mesh_only"
            else (dns, None)
        ),
    )
    monkeypatch.setattr(reaper, "_default_transport", lambda site: transport)


def _surfaces():
    from core.models import CheckRun, Finding

    parts = []
    for run in CheckRun.objects.filter(kind=CheckRun.Kind.ADOPT):
        parts.append(json.dumps(run.results, sort_keys=True))
        parts.append(run.status)
    for row in Finding.objects.all():
        parts.append(
            f"{row.fingerprint}\n{row.title}\n{row.body}\n{row.fix_action}"
        )
    return "\n".join(parts)


def test_reaper_deletes_temp_older_than_24h(monkeypatch):
    """started_at older than 24 h: cleanup deletes the temp name.

    Mesh-only empty temp_name still reaches cleanup (temp container stop).
    Beat adopt-temp-reaper is hourly.

    What would make this fail: ignoring results.started_at, skipping mesh
    rows because temp_name is empty, or leaving the temp hostname in the zone.
    """
    from core.models import DnsRecord, Site
    from deploys.adopt_flow import ensure_temp_dns
    from deploys.adopt_reaper import reap
    from deploys.tasks import reap_adopt_temps

    site, deployment = _site("reap-old")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    temp = _checkrun(site).results["temp_name"]
    assert any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))
    _age_started(site, hours=25)

    mesh, mesh_dep = _site(
        "reap-mesh", exposure=Site.Exposure.MESH_ONLY, compose="web-only",
    )
    mesh_desired = _desired(mesh, mesh_dep, transport, dns=None)
    from deploys.adopt_flow import _write_checkrun

    _write_checkrun(mesh_desired, temp_name="", stage="verify")
    _age_started(mesh, hours=25)
    adopt = f"site-{mesh.name}-adopt"
    transport.containers[adopt] = "running"

    _wire(monkeypatch, transport, dns)
    reap()

    assert not any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))
    assert not DnsRecord.objects.filter(site=site, name=temp).exists()
    assert transport.containers[adopt] == "exited"

    entry = settings.CELERY_BEAT_SCHEDULE["adopt-temp-reaper"]
    assert entry["task"] == reap_adopt_temps.name
    assert float(entry["schedule"]) == 3600.0


def test_reaper_leaves_fresh_temp_alone(monkeypatch):
    """started_at inside 24 h: the temp name is not deleted.

    What would make this fail: reap-on-sight without the abandon TTL, or
    dating the TTL from CheckRun.started instead of results.started_at.
    """
    from core.models import DnsRecord
    from deploys.adopt_flow import ensure_temp_dns
    from deploys.adopt_reaper import reap

    site, deployment = _site("reap-fresh")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    temp = _checkrun(site).results["temp_name"]
    _age_started(site, hours=1)
    # CheckRun.started is old; results.started_at is fresh — TTL is the latter.
    run = _checkrun(site)
    run.started = timezone.now() - timedelta(hours=30)
    run.save(update_fields=["started"])

    _wire(monkeypatch, transport, dns)
    reap()

    assert any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))
    assert DnsRecord.objects.filter(site=site, name=temp).exists()


def test_cleanup_failure_files_orphan_finding(monkeypatch):
    """Failed cleanup files adopt-temp-orphan:{site_pk}:{name} at P2.

    What would make this fail: swallowing the provider error, filing P1 /
    Hub-down / REL-P2, or a fingerprint that omits the temp name.
    """
    from core.models import Finding
    from deploys.adopt_flow import ensure_temp_dns
    from deploys.adopt_reaper import reap

    site, deployment = _site("reap-orphan")
    transport = AdoptTransport()
    dns = BoomOnDelete()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    temp = _checkrun(site).results["temp_name"]
    _age_started(site, hours=25)

    _wire(monkeypatch, transport, dns)
    reap()

    row = Finding.objects.get(fingerprint=f"adopt-temp-orphan:{site.pk}:{temp}")
    assert row.severity == Finding.Severity.P2
    blob = f"{row.title}\n{row.body}\n{row.fix_action}".lower()
    assert "hub-down" not in blob
    assert "rel-p2" not in blob
    assert any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))


def test_successful_cleanup_resolves_orphan_finding():
    """A later successful cleanup resolves adopt-temp-orphan:{pk}:{name}.

    What would make this fail: leaving the P2 OPEN after the temp is gone,
    so the inbox keeps a leftover the zone no longer has.
    """
    from core.models import Finding
    from deploys.adopt_flow import cleanup, ensure_temp_dns

    site, deployment = _site("reap-resolve")
    transport = AdoptTransport()
    boom = BoomOnDelete()
    desired = _desired(site, deployment, transport, boom)
    ensure_temp_dns(desired)
    temp = _checkrun(site).results["temp_name"]
    with pytest.raises(RuntimeError):
        cleanup(desired)
    row = Finding.objects.get(fingerprint=f"adopt-temp-orphan:{site.pk}:{temp}")
    assert row.state == Finding.State.OPEN

    dns = FakeDnsProvider()
    dns.upsert_record(
        site.dns_zone, temp, "A", ["203.0.113.10"], proxied=site.proxied,
    )
    desired["dns"] = dns
    cleanup(desired)
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert not any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))


def test_reaper_does_not_delete_prod_name_or_registered_volume(monkeypatch):
    """cleanup deletes the temp name only. Prod DNS and SiteVolume stay.

    What would make this fail: delete_record on the prod hostname, or
    `docker volume rm` of a registered name (same M1 as decommission).
    """
    from core.models import DnsRecord, SiteVolume
    from deploys.adopt_flow import ensure_temp_dns
    from deploys.adopt_reaper import reap

    site, deployment = _site("reap-safe")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    temp = _checkrun(site).results["temp_name"]
    SiteVolume.objects.update_or_create(
        site=site, name="pgdata", defaults={"container_path": "/var/lib/postgresql/data"},
    )
    transport.volumes.add("pgdata")
    transport.containers[f"site-{site.name}-adopt"] = "running"
    _age_started(site, hours=25)

    _wire(monkeypatch, transport, dns)
    reap()

    assert not any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]
    assert DnsRecord.objects.filter(site=site, name=site.domain).exists()
    assert SiteVolume.objects.filter(site=site, name="pgdata").exists()
    assert "pgdata" in transport.volumes
    for argv in _volume_rm_argvs(transport):
        assert "pgdata" not in " ".join(str(part) for part in argv)


def test_reaper_reconstructs_provider_from_site_dns_zone_and_stores_no_token(
    monkeypatch,
):
    """Load Site from results['site_id']; dns_provider_for(site.dns_zone).

    S4: never persist a token on the CheckRun or in reaper state. Closed
    results schema stays closed.

    What would make this fail: constructing Cloudflare in deploys/, reading
    a stored token off the CheckRun, or writing a sixth results key.
    """
    from deploys.adopt_flow import ensure_temp_dns
    from deploys.adopt_reaper import reap

    site, deployment = _site("reap-seams")
    account = site.dns_zone.account
    account.dns_token_ref = PLANTED_TOKEN
    account.save(update_fields=["dns_token_ref"])
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    dns.token = PLANTED_TOKEN
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    _age_started(site, hours=25)

    seen = []

    import deploys.adopt_reaper as reaper

    def fake_provider(zone):
        seen.append(zone)
        return dns

    monkeypatch.setattr(reaper, "dns_provider_for", fake_provider)
    monkeypatch.setattr(reaper, "_default_transport", lambda _site: transport)

    reap()

    assert seen == [site.dns_zone]
    run = _checkrun(site)
    assert set(run.results) == ADOPT_RESULT_KEYS
    assert "token" not in run.results
    assert PLANTED_TOKEN not in _surfaces()
    source = (settings.BASE_DIR / "deploys" / "adopt_reaper.py").read_text(
        encoding="utf-8"
    )
    assert "providers.cloudflare" not in source
    assert "HUB_TEST_CF_TOKEN" not in source

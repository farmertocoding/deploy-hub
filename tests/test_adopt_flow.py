"""Temp-subdomain adopt flow (Phase 3b Task 6 / design note §1.1 c,d, §7).

Temp deploy → verify → point DB/volumes → flip DNS → decommission.
Never flip before verify. Never strand a volume. Never docker volume rm a
registered name. CheckRun.results stay the closed S2 schema.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from dns_fixtures import default_dns_zone

from core.transport import CommandResult
from deploys.testing import READY_JSON, PipelineTransport, _inspect_target
from providers.fakes import FakeDnsProvider

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.req("PROV-E6-ADOPT-TEMP-SUBDOMAIN"),
    pytest.mark.req("PROV-J7-COMPOSE-AWARE-ADOPT"),
]

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "compose"
DB_URL = "postgres://adopt:super-secret-db-url@db:5432/app"
CACHE_URL = "redis://redis:6379/0"
ADOPT_RESULT_KEYS = frozenset(
    {"schema_version", "site_id", "temp_name", "stage", "started_at"}
)
TEMP_NAME_RE = re.compile(r"^[a-z0-9-]+-adopt-[0-9a-f]{8}\.[a-z0-9.-]+$")


class AdoptTransport(PipelineTransport):
    """Old stack stays addressable; temp healthz only succeeds on the adopt container."""

    def __init__(self):
        super().__init__()
        self.inspect_env = {}
        self.inspect_mounts = {}
        self.container_images = {}
        self.curl_stdout = None

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv[:2] == ["docker", "run"]:
            name = _flag(argv, "--name")
            if name:
                n = 10 + len(self.container_ips)
                self.container_ips[name] = f"10.0.0.{n}"
                self.container_images[name] = argv[-1]
        if argv[:2] == ["docker", "rm"] or (
            len(argv) >= 3 and argv[0] == "docker" and "rm" in argv[1:3]
        ):
            gone = argv[-1]
            self.container_images.pop(gone, None)
        return result

    def _inspect_container(self, argv):
        name = _inspect_target(argv)
        fmt = ""
        if "--format" in argv:
            fmt = argv[argv.index("--format") + 1]
        if "Image" in fmt:
            present = name in self.containers
            return CommandResult(
                argv,
                exit_code=0 if present else 1,
                stdout=self.container_images.get(name, "") if present else "",
                stderr="" if present else "Error: No such container",
            )
        if "Env" in fmt:
            lines = self.inspect_env.get(name, [])
            present = name in self.containers or bool(lines)
            return CommandResult(
                argv,
                exit_code=0 if present else 1,
                stdout="\n".join(lines),
                stderr="" if present else "Error: No such container",
            )
        if "Mounts" in fmt or (".Name" in fmt and ".Type" in fmt):
            mounts = self.inspect_mounts.get(name, [])
            if name not in self.containers and not mounts:
                return CommandResult(argv, exit_code=1, stderr="Error: No such container")
            stdout = "".join(f"{vol} volume\n" for vol in mounts)
            return CommandResult(argv, exit_code=0, stdout=stdout)
        return super()._inspect_container(argv)

    def _curl_probe(self, argv):
        url = ""
        for part in argv:
            text = str(part)
            if text.startswith("http://") or text.startswith("https://"):
                url = text
        adopt = _adopt_container(self)
        temp_host = getattr(self, "temp_host", "")
        adopt_ip = self.container_ips.get(adopt, "") if adopt else ""
        wants_temp = bool(
            "-adopt-" in url
            or (temp_host and temp_host in url)
            or (adopt_ip and adopt_ip in url)
            or (adopt and adopt in url)
        )
        if wants_temp:
            if adopt and self.containers.get(adopt) == "running":
                body = self.curl_stdout if self.curl_stdout is not None else READY_JSON
                return CommandResult(argv, stdout=body)
            return CommandResult(argv, exit_code=1, stderr="temp not ready")
        if any(state == "running" for state in self.containers.values()):
            return CommandResult(argv, stdout=READY_JSON)
        return CommandResult(argv, exit_code=1, stderr="not ready")


def _flag(argv, name):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _adopt_container(transport):
    names = [name for name in transport.containers if name.endswith("-adopt")]
    return names[0] if names else None


def _target(slug):
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name=f"lan-{slug}", slug=f"lan-{slug}")
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref=f"vault-{slug}",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def _site(slug, *, exposure="public", compose="web-worker-beat-migrate", domain=None):
    from core.models import Project, Site
    from deploys.models import Deployment, Manifest

    project = Project.objects.create(
        name=slug,
        slug=slug,
        source_kind=Project.Source.LOCAL_PATH,
        local_path=str(FIXTURES / compose),
    )
    kwargs = {
        "project": project,
        "name": slug,
        "exposure": exposure,
        "primary_target": _target(slug),
        "proxied": True,
    }
    if exposure == Site.Exposure.PUBLIC:
        kwargs["domain"] = domain or f"{slug}.example.com"
        kwargs["dns_zone"] = default_dns_zone()
    site = Site.objects.create(**kwargs)
    body = {
        "git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_dir": project.local_path,
        "domain": site.domain,
        "readiness_path": "/healthz.ready",
        "liveness_path": "/healthz",
        "warmup_timeout_s": 5,
    }
    manifest = Manifest.objects.create(site=site, version=1, body=body)
    deployment = Deployment.objects.create(manifest=manifest)
    return site, deployment


def _site_from_tree(tmp_path, slug, compose_text, *, exposure="public"):
    from core.models import Project, Site
    from deploys.models import Deployment, Manifest

    root = tmp_path / slug
    root.mkdir()
    (root / "docker-compose.yml").write_text(compose_text)
    project = Project.objects.create(
        name=slug,
        slug=slug,
        source_kind=Project.Source.LOCAL_PATH,
        local_path=str(root),
    )
    kwargs = {
        "project": project,
        "name": slug,
        "exposure": exposure,
        "primary_target": _target(slug),
        "proxied": True,
    }
    if exposure == "public":
        kwargs["domain"] = f"{slug}.example.com"
        kwargs["dns_zone"] = default_dns_zone()
    site = Site.objects.create(**kwargs)
    manifest = Manifest.objects.create(
        site=site,
        version=1,
        body={"git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    )
    return site, Deployment.objects.create(manifest=manifest)


def _desired(site, deployment, transport, dns, **extra):
    old = extra.pop("old_container", f"site-{site.name}-old")
    image_tag = extra.pop("image_tag", f"adopt-{site.name}-tag")
    desired = {
        "transport": transport,
        "site": site,
        "site_slug": site.name,
        "deployment_id": deployment.pk,
        "deployment": deployment,
        "manifest_body": deployment.manifest.body or {},
        "git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_dir": site.project.local_path,
        "image_tag": image_tag,
        "old_container": old,
        "dns": dns,
        "zone": site.dns_zone.name if site.dns_zone_id else "",
        "dns_zone": site.dns_zone,
        "domain": site.domain,
        "dns_values": ["203.0.113.10"],
        "poll_interval_s": 0,
        "internal_port": 8000,
        "sleep": lambda _s: None,
        "env_names": [],
        "firewall_argv": [],
    }
    desired.update(extra)
    transport.containers[old] = "running"
    transport.container_ips[old] = "10.0.0.8"
    transport.volumes.update({"pgdata", "media"})
    if site.dns_zone_id and dns is not None and site.domain:
        dns.upsert_record(
            site.dns_zone, site.domain, "A", ["198.51.100.1"], proxied=site.proxied,
        )
        from core.models import DnsRecord

        DnsRecord.objects.update_or_create(
            site=site,
            name=site.domain,
            rtype="A",
            defaults={"value": "198.51.100.1", "zone": site.dns_zone},
        )
        dns.calls.clear()
    return desired


def _checkrun(site):
    from core.models import CheckRun

    for row in CheckRun.objects.filter(kind=CheckRun.Kind.ADOPT).order_by("-pk"):
        if row.results.get("site_id") == site.pk:
            return row
    return None


def _finding_blob():
    from core.models import Finding

    parts = []
    for row in Finding.objects.all():
        parts.append(f"{row.fingerprint}\n{row.title}\n{row.body}\n{row.fix_action}")
    return "\n".join(parts)


def _volume_rm_argvs(transport):
    found = []
    for kind, payload in transport.calls:
        if kind != "run" or not isinstance(payload, list):
            continue
        argv = [str(part) for part in payload]
        if "volume" in argv and "rm" in argv[argv.index("volume") + 1:]:
            found.append(list(payload))
    return found


def _prod_values(dns, zone, name):
    for rec in dns.list_records(zone):
        if rec["name"] == name:
            return list(rec.get("values") or [])
    return []


def test_dns_flip_refuses_before_verification():
    """Flip is gated on verify for this image tag, not on temp DNS existing.

    What would make this fail: upserting the prod name after temp_dns alone,
    or treating a missing _adopt_verified_tag as success.
    """
    from core.models import DnsRecord
    from deploys.adopt_flow import AdoptRefused, ensure_flip, ensure_temp_dns

    site, deployment = _site("flip-early")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    with pytest.raises(AdoptRefused):
        ensure_flip(desired)
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]
    assert DnsRecord.objects.get(site=site, name=site.domain).value == "198.51.100.1"
    assert transport.containers[desired["old_container"]] == "running"


def test_verified_flip_upserts_then_decommissions():
    """After verify, flip writes the prod name and decommission stops the old path.

    What would make this fail: leaving prod on the old origin, or skipping
    docker stop of old_container after a successful flip.
    """
    from deploys.adopt_flow import adopt_flow

    site, deployment = _site("flip-ok")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    adopt_flow(desired)
    assert _prod_values(dns, site.dns_zone, site.domain) == ["203.0.113.10"]
    assert transport.containers[desired["old_container"]] == "exited"
    run = _checkrun(site)
    assert run.results["stage"] == "cleanup"


def test_abandoned_flip_cleans_up_its_temp_subdomain():
    """cleanup deletes the temp DnsRecord + provider record, never prod.

    What would make this fail: delete_record on the prod name, or leaving the
    temp hostname in the zone after abandon.
    """
    from core.models import DnsRecord
    from deploys.adopt_flow import cleanup, ensure_temp_dns

    site, deployment = _site("abandon")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    temp = _checkrun(site).results["temp_name"]
    assert temp
    assert any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))
    assert DnsRecord.objects.filter(site=site, name=temp).exists()
    cleanup(desired)
    assert not any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))
    assert not DnsRecord.objects.filter(site=site, name=temp).exists()
    assert DnsRecord.objects.filter(site=site, name=site.domain).exists()
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]


def test_temp_name_is_slug_adopt_token_hex_4_on_site_dns_zone():
    """Temp hostname is {slug}-adopt-{8hex}.{DnsZone.name} on Site.dns_zone.

    What would make this fail: a dedicated adoption zone, token_hex(8) (16
    hex chars), or upserting against a string zone name that is not the row.
    """
    from deploys.adopt_flow import ensure_temp_dns

    site, deployment = _site("name-shape")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    temp = _checkrun(site).results["temp_name"]
    assert TEMP_NAME_RE.match(temp)
    assert temp == f"{site.name}-adopt-{temp.split('-adopt-')[1]}"
    assert temp.endswith(f".{site.dns_zone.name}")
    assert len(temp.split("-adopt-")[1].split(".")[0]) == 8
    upserts = [call for call in dns.calls if call[0] == "upsert_record"]
    assert upserts
    assert upserts[0][1] is site.dns_zone
    assert upserts[0][2] == temp


def test_temp_hex_is_stored_on_first_upsert_and_reused(monkeypatch):
    """token_hex(4) runs once; CheckRun.results['temp_name'] is reused.

    What would make this fail: minting a new hex on the second ensure_temp_dns,
    or storing only the 8hex fragment so reuse cannot rebuild the FQDN.
    """
    from deploys import adopt_flow as adopt_mod

    minted = []

    def fake_hex(n):
        minted.append(n)
        return "abcd1234"[: n * 2]

    monkeypatch.setattr(adopt_mod.secrets, "token_hex", fake_hex)
    site, deployment = _site("hex-reuse")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    adopt_mod.ensure_temp_dns(desired)
    first = _checkrun(site).results["temp_name"]
    dns.calls.clear()
    adopt_mod.ensure_temp_dns(desired)
    second = _checkrun(site).results["temp_name"]
    assert minted == [4]
    assert first == second
    assert first.endswith(f"-adopt-abcd1234.{site.dns_zone.name}")
    assert not any(call[0] == "upsert_record" for call in dns.calls)


def test_checkrun_results_closed_schema_includes_site_id():
    """kind=adopt results are exactly the S2 keys and name this Site.

    What would make this fail: dropping site_id, adding image_tag/token, or
    writing verify success into a sixth key.
    """
    from deploys.adopt_flow import adopt_flow

    site, deployment = _site("closed-schema")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    adopt_flow(_desired(site, deployment, transport, dns))
    run = _checkrun(site)
    assert set(run.results) == ADOPT_RESULT_KEYS
    assert run.results["site_id"] == site.pk
    assert run.results["schema_version"] == 1
    assert run.results["started_at"]
    assert "image_tag" not in run.results
    assert "token" not in run.results


def test_no_dedicated_adoption_zone_is_constructed():
    """Temp record lives on the site's DnsZone. No new zone row.

    What would make this fail: DnsZone.objects.create for an adopt zone, or
    handing the provider a different zone than Site.dns_zone.
    """
    from core.models import DnsZone
    from deploys.adopt_flow import ensure_temp_dns

    site, deployment = _site("no-adopt-zone")
    before = set(DnsZone.objects.values_list("pk", "name"))
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    ensure_temp_dns(_desired(site, deployment, transport, dns))
    assert set(DnsZone.objects.values_list("pk", "name")) == before
    upserts = [call for call in dns.calls if call[0] == "upsert_record"]
    assert all(call[1] is site.dns_zone for call in upserts)


def test_flow_run_twice_records_zero_mutating_calls():
    """Second adopt_flow against a completed CheckRun mutates nothing (§D6).

    What would make this fail: minting a new temp name after cleanup, or
    docker run / DNS upsert / docker stop on the second pass.
    """
    from deploys.adopt_flow import adopt_flow

    site, deployment = _site("twice")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    adopt_flow(desired)
    dns.calls.clear()
    transport.calls.clear()
    adopt_flow(desired)
    assert dns.mutating_calls() == []
    assert transport.mutating_calls() == []


def test_decommission_never_docker_volume_rm_a_registered_name():
    """Decommission stops old containers and never `docker volume rm` pgdata/media.

    What would make this fail: issuing docker volume rm for a SiteVolume name
    (M1 — this is not a 'without confirmation' test).
    """
    from core.models import SiteVolume
    from deploys.adopt_flow import adopt_flow

    site, deployment = _site("vol-rm")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    adopt_flow(_desired(site, deployment, transport, dns))
    registered = set(SiteVolume.objects.filter(site=site).values_list("name", flat=True))
    assert {"pgdata", "media"} <= registered
    for argv in _volume_rm_argvs(transport):
        joined = " ".join(str(part) for part in argv)
        for name in registered:
            assert name not in joined
    assert transport.volumes >= {"pgdata", "media"}


def test_unmapped_named_volume_blocks_the_flip():
    """A live named volume that is not a SiteVolume refuses the flip.

    What would make this fail: flipping while orphanvol is mounted on the old
    container and missing from SiteVolume — that is a silent strand.
    """
    from core.models import DnsRecord
    from deploys.adopt_flow import AdoptRefused, adopt_flow

    site, deployment = _site("unmap")
    transport = AdoptTransport()
    transport.inspect_mounts[f"site-{site.name}-old"] = ["pgdata", "media", "orphanvol"]
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    with pytest.raises(AdoptRefused):
        adopt_flow(desired)
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]
    assert DnsRecord.objects.get(site=site, name=site.domain).value == "198.51.100.1"
    assert transport.containers[desired["old_container"]] == "running"


def test_compose_db_is_pointed_not_reprovisioned():
    """Compose DATABASE_URL is vaulted for the Site; ensure_site_db never runs.

    What would make this fail: docker run postgres:16 / site-{slug}-postgres,
    or skipping vault.put so _env_mapping_for_deploy cannot see the URL.
    """
    from deploys.adopt_flow import adopt_flow
    from deploys.pipeline import _env_mapping_for_deploy
    from vault import service as vault_service
    from vault.models import Secret

    site, deployment = _site("db-point")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    calls = []

    def boom(desired):
        calls.append(desired)
        raise AssertionError("ensure_site_db must not run on adopt")

    import provision.db as db_mod

    original = db_mod.ensure_site_db
    db_mod.ensure_site_db = boom
    try:
        adopt_flow(_desired(site, deployment, transport, dns))
    finally:
        db_mod.ensure_site_db = original
    assert calls == []
    secret = Secret.objects.get(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
    )
    assert vault_service.get(secret, reason="adopt-test") == DB_URL.encode()
    assert _env_mapping_for_deploy(deployment)["DATABASE_URL"] == DB_URL
    for kind, payload in transport.calls:
        if kind != "run" or not isinstance(payload, list):
            continue
        blob = " ".join(str(part) for part in payload)
        assert "postgres:16" not in blob
        assert f"site-{site.name}-postgres" not in blob


def test_missing_database_url_files_finding_and_skips_ensure_site_db(tmp_path):
    """No compose/inspect URL → adopt-db-url-missing Finding, never ensure_site_db.

    What would make this fail: starting a second Postgres, or putting the
    connection string (there is none) into the Finding copy.
    """
    from core.models import Finding
    from deploys.adopt_flow import adopt_flow
    from vault.models import Secret

    compose = (
        "services:\n"
        "  web:\n"
        "    image: blog:prod\n"
        "    ports: ['8000:8000']\n"
        "  db:\n"
        "    image: postgres:16\n"
        "    volumes: ['pgdata:/var/lib/postgresql/data']\n"
        "volumes:\n"
        "  pgdata:\n"
    )
    site, deployment = _site_from_tree(tmp_path, "db-miss", compose)
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    calls = []

    import provision.db as db_mod

    original = db_mod.ensure_site_db
    db_mod.ensure_site_db = lambda desired: calls.append(desired)
    try:
        adopt_flow(_desired(site, deployment, transport, dns))
    finally:
        db_mod.ensure_site_db = original
    assert calls == []
    assert not Secret.objects.filter(
        kind=Secret.Kind.DATABASE_URL, owner_type="site", owner_id=str(site.pk),
    ).exists()
    row = Finding.objects.get(fingerprint=f"adopt-db-url-missing:{site.pk}")
    blob = f"{row.title}\n{row.body}\n{row.fix_action}"
    assert "postgres://" not in blob
    assert DB_URL not in blob


def test_compose_cache_is_pointed_not_reprovisioned():
    """Classified redis is an ENV_BUNDLE pointer, not a Hub-started cache.

    What would make this fail: docker run redis:7, or inventing a new
    Secret.Kind instead of the existing env-bundle path.
    """
    from deploys.adopt_flow import adopt_flow
    from deploys.env import _desired_mapping
    from vault.models import Secret

    site, deployment = _site("cache-point")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    adopt_flow(_desired(site, deployment, transport, dns))
    mapping = _desired_mapping(site)
    assert mapping.get("REDIS_URL") == CACHE_URL
    assert not Secret.objects.filter(kind=Secret.Kind.DATABASE_URL).exclude(
        owner_id=str(site.pk),
    ).exists()
    for kind, payload in transport.calls:
        if kind != "run" or not isinstance(payload, list):
            continue
        blob = " ".join(str(part) for part in payload)
        assert "redis:7" not in blob
        assert "memcached" not in blob


def test_database_url_never_enters_manifest_checkrun_or_finding():
    """The obtained URL stays in the vault. S2 / S3 surfaces stay clean.

    What would make this fail: copying postgres://… into Manifest.body,
    CheckRun.results, or a Finding title/body/fix_action.
    """
    from core.models import Finding
    from deploys.adopt_flow import adopt_flow

    site, deployment = _site("url-surfaces")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    adopt_flow(_desired(site, deployment, transport, dns))
    run = _checkrun(site)
    surfaces = [
        json.dumps(deployment.manifest.body),
        json.dumps(run.results),
        _finding_blob(),
    ]
    for blob in surfaces:
        assert DB_URL not in blob
        assert "postgres://adopt:" not in blob
    for row in Finding.objects.all():
        assert DB_URL not in json.dumps(row.__dict__, default=str)


def test_live_compose_path_unset_skips_drift_check():
    """Unset live_compose_path means no Transport.get and no /srv/sites walk.

    What would make this fail: defaulting to /srv/sites/{slug} or getting any
    remote compose when the argument is omitted.
    """
    from deploys.adopt_flow import adopt_flow

    site, deployment = _site("drift-off")
    transport = AdoptTransport()
    transport.files[f"/srv/sites/{site.name}/docker-compose.yml"] = b"services: {}\n"
    dns = FakeDnsProvider()
    adopt_flow(_desired(site, deployment, transport, dns))
    gets = [payload for kind, payload in transport.calls if kind == "get"]
    assert gets == []
    assert _checkrun(site).results["stage"] == "cleanup"


def test_live_compose_path_drift_blocks_the_flip():
    """Set path → Transport.get that path only; mismatch blocks the flip.

    What would make this fail: walking /srv/sites/{slug}, ignoring the
    argument, or flipping after a drifted live compose.
    """
    from deploys.adopt_flow import AdoptRefused, adopt_flow

    site, deployment = _site("drift-on")
    transport = AdoptTransport()
    path = "/opt/live/docker-compose.yml"
    transport.files[path] = b"services:\n  web:\n    image: other:drifted\n"
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    with pytest.raises(AdoptRefused):
        adopt_flow(desired, live_compose_path=path)
    gets = [payload for kind, payload in transport.calls if kind == "get"]
    assert gets == [path]
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]
    assert transport.containers[desired["old_container"]] == "running"


def test_live_site_stays_up_until_flip():
    """QE I3 / E6: the old container is not stopped during temp deploy or verify.

    What would make this fail: docker stop of old_container before flip, or
    recreate-style ensure_start that takes the live writer down to verify.
    """
    from deploys.adopt_flow import ensure_flip, ensure_temp_dns, ensure_verify

    site, deployment = _site("stay-up")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    old = desired["old_container"]
    ensure_temp_dns(desired)
    ensure_verify(desired)
    assert transport.containers[old] == "running"
    stops = [
        payload for kind, payload in transport.calls
        if kind == "run" and isinstance(payload, list)
        and payload[:2] == ["docker", "stop"] and old in payload
    ]
    assert stops == []
    ensure_flip(desired)
    assert transport.containers[old] == "running"


def test_mesh_only_adopt_skips_temp_dns_verifies_over_seams_and_still_decommissions():
    """Mesh-only: temp_name='', dns is None, Transport healthz, decommission runs.

    What would make this fail: upserting a temp hostname, or skipping
    decommission because there was no DNS flip.
    """
    from core.models import Site
    from deploys.adopt_flow import adopt_flow

    site, deployment = _site(
        "mesh-adopt", exposure=Site.Exposure.MESH_ONLY, compose="web-only",
    )
    transport = AdoptTransport()
    desired = _desired(site, deployment, transport, dns=None)
    assert site.dns_zone_id is None
    adopt_flow(desired)
    run = _checkrun(site)
    assert run.results["temp_name"] == ""
    assert desired["dns"] is None
    assert transport.containers[desired["old_container"]] == "exited"
    curls = [
        payload for kind, payload in transport.calls
        if kind == "probe" and isinstance(payload, list) and payload[:1] == ["curl"]
    ]
    assert curls, "mesh verify must probe healthz over Transport"
    assert run.results["stage"] == "cleanup"


def test_adopt_refuses_without_primary_target():
    """Adopt reads Site.primary_target and refuses if null. No implicit host.

    What would make this fail: falling back to the first Target, or running
    stages against a None transport host.
    """
    from deploys.adopt_flow import AdoptRefused, adopt_flow

    site, deployment = _site("no-target")
    site.primary_target = None
    site.save(update_fields=["primary_target"])
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    with pytest.raises(AdoptRefused):
        adopt_flow(desired)
    assert _checkrun(site) is None
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]


def test_no_cloudflare_import_in_deploys_adopt_flow():
    """SEC-B2: adopt_flow never imports providers.cloudflare.

    What would make this fail: `from providers.cloudflare import …` or
    constructing a Cloudflare client inside deploys/.
    """
    root = Path(__file__).resolve().parent.parent
    source = (root / "deploys" / "adopt_flow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "cloudflare" not in alias.name
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "cloudflare" not in module
            for alias in node.names:
                assert "cloudflare" not in alias.name
    assert "providers.cloudflare" not in source


def test_non_json_200_healthz_does_not_verify():
    """A 200 default page is not healthz. Product treats non-JSON as not ready.

    What would make this fail: _ready_payload treating HTML (or a bare '200')
    as success so flip proceeds against a default page.
    """
    from deploys.adopt_flow import AdoptRefused, ensure_flip, ensure_temp_dns, ensure_verify

    site, deployment = _site("html-200")
    transport = AdoptTransport()
    transport.curl_stdout = "<!doctype html><title>ok</title>"
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    with pytest.raises(AdoptRefused):
        ensure_verify(desired)
    assert desired.get("_adopt_verified_tag") != desired["image_tag"]
    with pytest.raises(AdoptRefused):
        ensure_flip(desired)
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]
    assert transport.containers[desired["old_container"]] == "running"


def test_adopt_container_for_a_different_image_tag_is_not_reused():
    """A leftover site-{slug}-adopt for another tag is not this verify.

    What would make this fail: docker start/reuse of the old container, or
    stamping _adopt_verified_tag for the new tag without recreating.
    """
    from deploys.adopt_flow import ensure_temp_dns, ensure_verify

    site, deployment = _site("retag")
    transport = AdoptTransport()
    name = f"site-{site.name}-adopt"
    transport.containers[name] = "running"
    transport.container_images[name] = "stale-adopt-tag"
    transport.container_ips[name] = "10.0.0.12"
    dns = FakeDnsProvider()
    desired = _desired(
        site, deployment, transport, dns, image_tag="fresh-adopt-tag",
    )
    ensure_temp_dns(desired)
    ensure_verify(desired)
    rms = [
        payload for kind, payload in transport.calls
        if kind == "run" and isinstance(payload, list)
        and "rm" in payload and name in payload
        and "volume" not in payload
    ]
    runs = [
        payload for kind, payload in transport.calls
        if kind == "run" and isinstance(payload, list)
        and payload[:2] == ["docker", "run"]
        and payload[-1] == "fresh-adopt-tag"
    ]
    assert rms, "mismatched adopt container must be removed, not reused"
    assert runs, "verify must start the current image_tag"
    assert transport.container_images.get(name) == "fresh-adopt-tag"
    assert desired["_adopt_verified_tag"] == "fresh-adopt-tag"


def test_temp_name_slugifies_human_site_name_to_dns_safe_host():
    """A Site named 'My Shop' mints {slug}-adopt-{8hex}.{zone}, not spaces/caps.

    What would make this fail: interpolating site.name so the temp is
    'My Shop-adopt-…' (invalid DNS).
    """
    from core.validators import validate_domain
    from deploys.adopt_flow import ensure_temp_dns

    site, deployment = _site("shop-human")
    site.name = "My Shop"
    site.save(update_fields=["name"])
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    temp = _checkrun(site).results["temp_name"]
    assert " " not in temp
    assert temp == temp.lower()
    assert TEMP_NAME_RE.match(temp)
    assert temp.startswith("my-shop-adopt-")
    assert temp.endswith(f".{site.dns_zone.name}")
    validate_domain(temp)

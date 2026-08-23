"""Temp-subdomain adopt flow (design note §1.1 c/d, §7 I-live/I-run/I-dburl/I-mesh).

MUST start. `desired` uses the same keys `_assemble_desired` already publishes.
`desired["dns"]` comes from `dns_provider_for(site.dns_zone)` (None for
mesh_only). Cloudflare HTTP stays under providers/; this module does not
import that adapter.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import yaml
from django.utils import timezone

from core.findings import finding, resolve
from core.models import CheckRun, DnsRecord, Finding, SiteVolume
from deploys.env import merge_env
from deploys.pipeline import _env_mapping_for_deploy
from deploys.steps import _container_running, _put_env_file
from provision.adopt import (
    CACHE_URL_MISSING_FP,
    DB_URL_MISSING_FP,
    _env_map,
    _named_volume_targets,
    _services,
    classify_services,
    read_compose,
)
from vault import service as vault_service
from vault.models import Secret

_PAST_TEMP = frozenset({"verify", "flip", "decommission", "cleanup"})
_PAST_VERIFY = frozenset({"flip", "decommission", "cleanup"})
_PAST_FLIP = frozenset({"decommission", "cleanup"})
_CACHE_KEYS = ("REDIS_URL", "CACHE_URL")


class AdoptRefused(RuntimeError):
    """Adopt will not flip or start: verify, drift, volume, or target gate."""


def adopt_flow(desired, *, live_compose_path=None):
    """Temp deploy → verify → point → flip prod DNS → decommission → cleanup."""
    site = desired["site"]
    if site.primary_target_id is None:
        raise AdoptRefused("adopt refuses without a primary_target")
    _bind_dns(desired)
    run = _find_checkrun(site)
    if run is not None and run.results.get("stage") == "cleanup":
        return run
    _point_db_cache_volumes(desired)
    if not _is_mesh(site):
        ensure_temp_dns(desired)
    ensure_verify(desired)
    ensure_flip(desired, live_compose_path=live_compose_path)
    ensure_decommission(desired)
    cleanup(desired)
    return _find_checkrun(site)


def ensure_temp_dns(desired):
    """Upsert `{slug}-adopt-{token_hex(4)}.{zone.name}` on Site.dns_zone."""
    site = desired["site"]
    if _is_mesh(site):
        desired["dns"] = None
        return
    run = _find_checkrun(site)
    stage = (run.results.get("stage") if run else "") or ""
    if stage == "cleanup":
        return
    temp = (run.results.get("temp_name") if run else "") or ""
    if not temp:
        temp = f"{site.name}-adopt-{secrets.token_hex(4)}.{site.dns_zone.name}"
        _write_checkrun(desired, temp_name=temp, stage="temp_dns")
    zone = site.dns_zone
    dns = desired["dns"]
    values = list(desired.get("dns_values") or ["127.0.0.1"])
    existing = _records_by_name(dns, zone)
    current = existing.get((temp, "A"))
    if (
        current is None
        or list(current.get("values") or []) != values
        or bool(current.get("proxied", False)) != bool(site.proxied)
    ):
        dns.upsert_record(zone, temp, "A", values, proxied=site.proxied)
    DnsRecord.objects.update_or_create(
        site=site,
        name=temp,
        rtype="A",
        defaults={"value": values[0] if values else "", "zone": zone},
    )
    if stage not in _PAST_TEMP:
        _write_checkrun(desired, temp_name=temp, stage="temp_dns")


def ensure_verify(desired):
    """Start the temp container (old stack stays up) and probe healthz."""
    site = desired["site"]
    _bind_dns(desired)
    run = _find_checkrun(site)
    stage = (run.results.get("stage") if run else "") or ""
    if stage == "cleanup":
        if _container_image_matches(desired):
            desired["_adopt_verified_tag"] = desired.get("image_tag")
        return
    if _is_mesh(site) and (run is None or not run.results.get("temp_name")):
        _write_checkrun(desired, temp_name="", stage=stage)
    _point_db_cache_volumes(desired)
    _start_temp_container(desired)
    if not _temp_healthz_ready(desired):
        raise AdoptRefused("verify failed for this image tag")
    desired["_adopt_verified_tag"] = desired.get("image_tag")
    if stage not in _PAST_VERIFY:
        _write_checkrun(desired, stage="verify")


def ensure_flip(desired, *, live_compose_path=None):
    """Point the prod name at the verified stack. Refuses without verify."""
    site = desired["site"]
    if site.primary_target_id is None:
        raise AdoptRefused("adopt refuses without a primary_target")
    if desired.get("_adopt_verified_tag") != desired.get("image_tag"):
        raise AdoptRefused("verify has not succeeded for this image tag")
    _bind_dns(desired)
    run = _find_checkrun(site)
    stage = (run.results.get("stage") if run else "") or ""
    if stage in _PAST_FLIP:
        return
    _point_db_cache_volumes(desired)
    _refuse_unmapped(desired)
    _refuse_drift(desired, live_compose_path)
    if _is_mesh(site):
        _write_checkrun(desired, stage="flip")
        return
    zone = site.dns_zone
    dns = desired["dns"]
    values = list(desired.get("dns_values") or ["127.0.0.1"])
    existing = _records_by_name(dns, zone)
    current = existing.get((site.domain, "A"))
    if (
        current is None
        or list(current.get("values") or []) != values
        or bool(current.get("proxied", False)) != bool(site.proxied)
    ):
        dns.upsert_record(zone, site.domain, "A", values, proxied=site.proxied)
    DnsRecord.objects.update_or_create(
        site=site,
        name=site.domain,
        rtype="A",
        defaults={"value": values[0] if values else "", "zone": zone},
    )
    _write_checkrun(desired, stage="flip")


def ensure_decommission(desired):
    """Stop the old path. Never `docker volume rm` a registered name."""
    site = desired["site"]
    run = _find_checkrun(site)
    stage = (run.results.get("stage") if run else "") or ""
    if stage == "cleanup":
        return
    old = desired.get("old_container")
    transport = desired["transport"]
    if old and _container_running(transport, old) is True:
        result = transport.run(["docker", "stop", old])
        if not result.ok:
            raise AdoptRefused(f"docker stop failed: {result.stderr}")
    if stage != "cleanup":
        _write_checkrun(desired, stage="decommission")


def cleanup(desired):
    """Delete the temp DnsRecord + provider record. Never the prod name.

    One owner for cancel, successful flip, and the adopt-temp-reaper Beat.
    A failed delete files `adopt-temp-orphan:{site_pk}:{name}` (P2) and
    re-raises; a later success resolves that fingerprint. This is an
    abandon leftover, not a Hub-down and not REL-P2.
    """
    site = desired["site"]
    try:
        _bind_dns(desired)
        run = _find_checkrun(site)
        temp = (run.results.get("temp_name") if run else "") or ""
        stage = (run.results.get("stage") if run else "") or ""
        dns = desired.get("dns")
        if temp and dns is not None and site.dns_zone_id:
            zone = site.dns_zone
            for rec in dns.list_records(zone):
                if rec.get("name") == temp:
                    dns.delete_record(zone, rec["id"])
            DnsRecord.objects.filter(site=site, name=temp).exclude(
                name=site.domain,
            ).delete()
        if stage in ("", "temp_dns", "verify"):
            name = _temp_container_name(desired)
            transport = desired["transport"]
            if _container_running(transport, name) is True:
                transport.run(["docker", "stop", name])
        if run is not None:
            _write_checkrun(desired, stage="cleanup", status=CheckRun.Status.SUCCEEDED)
        _resolve_fp(f"adopt-temp-orphan:{site.pk}:{temp}")
    except Exception:
        run = _find_checkrun(site)
        temp = (run.results.get("temp_name") if run else "") or ""
        _file_orphan(site, temp)
        raise


def _bind_dns(desired):
    site = desired["site"]
    if _is_mesh(site):
        desired["dns"] = None
        return
    if desired.get("dns") is None and site.dns_zone_id:
        from providers.registry import dns_provider_for

        desired["dns"] = dns_provider_for(site.dns_zone)


def _is_mesh(site):
    return getattr(site, "exposure", None) == "mesh_only"


def _temp_container_name(desired):
    return f"site-{desired['site_slug']}-adopt"


def _records_by_name(dns, zone):
    return {(rec["name"], rec["rtype"]): rec for rec in dns.list_records(zone)}


def _find_checkrun(site):
    for row in CheckRun.objects.filter(kind=CheckRun.Kind.ADOPT).order_by("-pk"):
        if row.results.get("site_id") == site.pk:
            return row
    return None


def _write_checkrun(desired, *, temp_name=None, stage=None, status=None):
    site = desired["site"]
    run = _find_checkrun(site)
    if run is None:
        results = {
            "schema_version": 1,
            "site_id": site.pk,
            "temp_name": "" if temp_name is None else temp_name,
            "stage": stage or "",
            "started_at": timezone.now().isoformat(),
        }
        return CheckRun.objects.create(
            kind=CheckRun.Kind.ADOPT,
            status=status or CheckRun.Status.RUNNING,
            started=timezone.now(),
            results=results,
        )
    current = dict(run.results)
    if temp_name is not None:
        current["temp_name"] = temp_name
    if stage is not None:
        current["stage"] = stage
    run.results = {
        "schema_version": 1,
        "site_id": site.pk,
        "temp_name": current.get("temp_name") or "",
        "stage": current.get("stage") or "",
        "started_at": current["started_at"],
    }
    if status is not None:
        run.status = status
        run.finished = timezone.now()
        run.save(update_fields=["results", "status", "finished"])
    else:
        run.save(update_fields=["results"])
    return run


def _compose_doc(site):
    tree = Path(site.project.local_path) if site.project.local_path else None
    if tree is None:
        return {}, Path()
    try:
        return read_compose(tree), tree
    except FileNotFoundError:
        return {}, tree


def _point_db_cache_volumes(desired):
    """Register compose volumes; vault DATABASE_URL; env-bundle the cache URL."""
    site = desired["site"]
    compose, tree = _compose_doc(site)
    roles = classify_services(compose)
    services = _services(compose)
    for name, dest in _named_volume_targets(compose).items():
        SiteVolume.objects.update_or_create(
            site=site,
            name=name,
            defaults={"container_path": dest or "/"},
        )
    if roles.get("db"):
        url = _obtain_env(desired, roles, services, tree, "db", ("DATABASE_URL",))
        if url:
            _vault_database_url(site, url)
            _resolve_fp(DB_URL_MISSING_FP.format(site_id=site.pk))
        else:
            _file_missing_db(site)
    if roles.get("cache"):
        url, key = _obtain_cache(desired, roles, services, tree)
        if url:
            merge_env(site, {key: url})
            _resolve_fp(CACHE_URL_MISSING_FP.format(site_id=site.pk))
        else:
            _file_missing_cache(site)


def _obtain_env(desired, roles, services, tree, role, keys):
    name = roles.get(role)
    if name:
        env = _env_map(services.get(name) or {}, tree)
        for key in keys:
            if env.get(key):
                return env[key]
    web = roles.get("web")
    if web and web != name:
        env = _env_map(services.get(web) or {}, tree)
        for key in keys:
            if env.get(key):
                return env[key]
    for key in keys:
        found = _inspect_env_key(desired, roles, role, key)
        if found:
            return found
    return None


def _obtain_cache(desired, roles, services, tree):
    url = _obtain_env(desired, roles, services, tree, "cache", _CACHE_KEYS)
    if not url:
        return None, "REDIS_URL"
    name = roles.get("cache")
    env = _env_map(services.get(name) or {}, tree) if name else {}
    if web := roles.get("web"):
        env = {**_env_map(services.get(web) or {}, tree), **env}
    for key in _CACHE_KEYS:
        if env.get(key):
            return url, key
    inspected = _inspect_env_map(desired, roles, "cache")
    for key in _CACHE_KEYS:
        if inspected.get(key):
            return url, key
    return url, "REDIS_URL"


def _inspect_env_map(desired, roles, role):
    transport = desired["transport"]
    candidates = [roles.get(role), roles.get("web")]
    merged = {}
    for name in candidates:
        if not name:
            continue
        result = transport.probe([
            "docker", "inspect", "--format",
            "{{range .Config.Env}}{{println .}}{{end}}",
            name,
        ])
        if not result.ok:
            continue
        for line in (result.stdout or "").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                merged[key] = value
    return merged


def _inspect_env_key(desired, roles, role, key):
    return _inspect_env_map(desired, roles, role).get(key)


def _vault_database_url(site, url):
    exists = Secret.objects.filter(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
    ).exists()
    if exists:
        return
    vault_service.put(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
        plaintext=url.encode() if not isinstance(url, bytes) else url,
    )


def _file_orphan(site, name):
    finding(
        "adopt",
        f"adopt-temp-orphan:{site.pk}:{name}",
        severity=Finding.Severity.P2,
        entity=f"site:{site.pk}",
        title="Abandoned adopt temp was not cleaned up",
        body=(
            f"Cleanup could not remove {name or 'the adopt temp'} after the "
            "abandon TTL. The leftover is a temp name or container, not "
            "the production hostname."
        ),
        fix_action=(
            "Retry cleanup or delete the leftover temp name in the site DNS zone."
        ),
    )


def _file_missing_db(site):
    finding(
        "adopt",
        DB_URL_MISSING_FP.format(site_id=site.pk),
        severity=Finding.Severity.P2,
        entity=f"site:{site.pk}",
        title="Adopted database URL is missing from compose",
        body=(
            "The classified db service has no connection string in "
            "its compose environment or env_file. Hub will not start "
            "a second database."
        ),
        fix_action="Put the existing connection string on the db service env.",
    )


def _file_missing_cache(site):
    finding(
        "adopt",
        CACHE_URL_MISSING_FP.format(site_id=site.pk),
        severity=Finding.Severity.P2,
        entity=f"site:{site.pk}",
        title="Adopted cache URL is missing from compose",
        body=(
            "The classified cache service has no connection string in "
            "its compose environment or env_file. Cache is a pointer, "
            "not a Hub-provisioned cache."
        ),
        fix_action=(
            "Put the existing cache connection string on the cache service env."
        ),
    )


def _resolve_fp(fingerprint):
    row = Finding.objects.filter(fingerprint=fingerprint).first()
    if row is not None and row.state in (Finding.State.OPEN, Finding.State.ACKED):
        resolve(row, source="system")


def _refuse_unmapped(desired):
    site = desired["site"]
    compose, _tree = _compose_doc(site)
    registered = set(
        SiteVolume.objects.filter(site=site).values_list("name", flat=True)
    )
    wanted = set(_named_volume_targets(compose)) | _live_named_volumes(desired)
    unmapped = wanted - registered
    if unmapped:
        raise AdoptRefused(
            f"unmapped named volumes block the flip: {', '.join(sorted(unmapped))}"
        )


def _live_named_volumes(desired):
    old = desired.get("old_container")
    if not old:
        return set()
    result = desired["transport"].probe([
        "docker", "inspect", "--format",
        "{{range .Mounts}}{{.Name}} {{.Type}}\n{{end}}",
        old,
    ])
    if not result.ok:
        return set()
    found = set()
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "volume" and parts[0]:
            found.add(parts[0])
        elif len(parts) == 1 and parts[0]:
            found.add(parts[0])
    return found


def _refuse_drift(desired, live_compose_path):
    if not live_compose_path:
        return
    raw = desired["transport"].get(live_compose_path)
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8", "replace")
    else:
        text = "" if raw is None else str(raw)
    try:
        live_doc = yaml.safe_load(text)
    except yaml.YAMLError:
        live_doc = object()
    git_doc, _tree = _compose_doc(desired["site"])
    if live_doc != git_doc:
        raise AdoptRefused("live compose drifted from the Project tree")


def _container_image(transport, name):
    result = transport.probe([
        "docker", "inspect", "--format", "{{.Config.Image}}", name,
    ])
    if not result.ok:
        return ""
    return (result.stdout or "").strip()


def _container_image_matches(desired):
    name = _temp_container_name(desired)
    image = _container_image(desired["transport"], name)
    tag = desired.get("image_tag")
    return bool(image) and bool(tag) and image == tag


def _start_temp_container(desired):
    transport = desired["transport"]
    name = _temp_container_name(desired)
    tag = desired.get("image_tag")
    running = _container_running(transport, name)
    if running is not None:
        if _container_image(transport, name) != tag:
            result = transport.run(["docker", "rm", "-f", name])
            if not result.ok:
                raise AdoptRefused(
                    "adopt container image does not match this image_tag"
                )
        elif running is True:
            return
        else:
            result = transport.run(["docker", "start", name])
            if not result.ok:
                raise AdoptRefused(f"docker start failed: {result.stderr}")
            return
    deployment = desired.get("deployment")
    mapping = {}
    site = desired.get("site")
    if site is not None:
        from deploys.env import _desired_mapping

        mapping.update(_desired_mapping(site))
    if deployment is not None:
        mapping.update(_env_mapping_for_deploy(deployment))
    if mapping:
        desired["env_mapping"] = mapping
        _put_env_file(desired)
    argv = ["docker", "run", "-d", "--name", name]
    if desired.get("env_file"):
        argv.extend(["--env-file", desired["env_file"]])
    for vol in SiteVolume.objects.filter(site=desired["site"]):
        argv.extend(["-v", f"{vol.name}:{vol.container_path}"])
    port = int(desired.get("internal_port") or 8000)
    argv.extend(["-e", f"PORT={port}"])
    argv.append(desired["image_tag"])
    result = transport.run(argv)
    if not result.ok:
        raise AdoptRefused(f"docker run failed: {result.stderr}")


def _temp_healthz_ready(desired):
    transport = desired["transport"]
    site = desired["site"]
    path = getattr(site, "readiness_path", None) or "/healthz.ready"
    live = getattr(site, "liveness_path", None) or "/healthz"
    port = int(desired.get("internal_port") or 8000)
    if _is_mesh(site):
        name = _temp_container_name(desired)
        ip_r = transport.probe([
            "docker", "inspect", "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            name,
        ])
        host = (ip_r.stdout or "").strip().split()[0] if ip_r.ok else ""
        host = host or "127.0.0.1"
        url = f"http://{host}:{port}{path}"
        result = transport.probe(["curl", "-sf", url])
        return _ready_payload(result)
    run = _find_checkrun(site)
    temp = (run.results.get("temp_name") if run else "") or ""
    if not temp:
        return False
    code = transport.probe([
        "curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}",
        f"http://{temp}{live}",
    ])
    if not code.ok:
        return False
    result = transport.probe(["curl", "-sf", f"http://{temp}{path}"])
    return _ready_payload(result)


def _ready_payload(result):
    """Same gate as product `_healthz_payload`: JSON with ready, else not ready."""
    if not result.ok or not (result.stdout or "").strip():
        return False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("ready"))

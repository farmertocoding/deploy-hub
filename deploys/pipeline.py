"""Deployment state machine. Reads Manifest.body only — never scanner.

Lock boundary: OperationLock kind=deploy on the site and the target, holder =
the deployment id. A new deploy while one is running supersedes the old row
before taking the unique (scope, object_id, kind) lock.
"""
import ipaddress
import json
import os
import signal
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from core import locks
from core.models import OperationLock
from core.test_mode import assert_test_zone
from deploys.models import Deployment, DeploymentArtifact, DeploymentStep
from deploys.seams import DeploySeamRefused, resolve_production_seams
from deploys.steps import (
    _caddy_route,
    _desired_dns_records,
    _dockerfile_from_body,
    ensure_build,
    ensure_cutover,
    ensure_dns,
    ensure_health_check,
    ensure_migrate,
    ensure_route_tls,
    ensure_ship,
    ensure_smoke,
    ensure_start,
    ensure_volume,
    ensure_volume_rollback,
    image_tag,
)

CRASH_AFTER_ENV = "HUB_TEST_CRASH_AFTER_STEP"
CRASH_SIGNAL_ENV = "HUB_TEST_CRASH_SIGNAL"
DEFAULT_GIT_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_REPO_ROOT = Path(__file__).resolve().parent.parent
TERMINAL_STATUSES = {
    Deployment.Status.SUCCEEDED,
    Deployment.Status.FAILED,
    Deployment.Status.CANCELLED,
    Deployment.Status.SUPERSEDED,
    Deployment.Status.ROLLED_BACK,
}


def resume_step(deployment):
    """First step whose status is not succeeded or skipped."""
    done = {DeploymentStep.Status.SUCCEEDED, DeploymentStep.Status.SKIPPED}
    for step in deployment.steps.order_by("seq"):
        if step.status not in done:
            return step
    return None


def persist_steps(deployment):
    """Create all nine named steps in seq order as pending, once."""
    if deployment.steps.exists():
        return
    for seq, name in enumerate(DeploymentStep.Name.values, start=1):
        DeploymentStep.objects.create(
            deployment=deployment,
            seq=seq,
            name=name,
            status=DeploymentStep.Status.PENDING,
        )


def release_deploy_locks(deployment):
    """Drop every deploy lock held by this deployment id."""
    holder = str(deployment.pk)
    rows = list(
        OperationLock.objects.filter(
            kind=OperationLock.Kind.DEPLOY, holder=holder,
        )
    )
    for row in rows:
        locks.release(row.scope, row.object_id, row.kind, holder=holder)


def touch_heartbeat(deployment):
    """Stamp Deployment.last_heartbeat; also touch held OperationLock rows."""
    from django.db import close_old_connections, connection
    from django.db.utils import OperationalError

    now = timezone.now()
    try:
        _write_heartbeat(deployment, now)
    except OperationalError:
        if connection.vendor != "sqlite":
            raise
        close_old_connections()
        try:
            _write_heartbeat(deployment, now)
        except OperationalError:
            if connection.vendor != "sqlite":
                raise
            close_old_connections()


def _write_heartbeat(deployment, now):
    Deployment.objects.filter(pk=deployment.pk).update(last_heartbeat=now)
    deployment.last_heartbeat = now
    holder = str(deployment.pk)
    rows = OperationLock.objects.filter(
        kind=OperationLock.Kind.DEPLOY, holder=holder,
    )
    for row in rows:
        locks.heartbeat(row.scope, row.object_id, row.kind, holder=holder)


def load_env_snapshot(deployment):
    """Decrypt the manifest env bundle via vault. Caller must not persist the bytes."""
    ref = (deployment.manifest.body or {}).get("env_bundle_ref")
    if not ref:
        return None
    from vault import service as vault_service
    from vault.models import Secret

    secret = Secret.objects.get(pk=ref)
    return vault_service.get(secret, reason=f"deploy {deployment.pk}")


def begin_deploy(deployment, *, target=None):
    """Acquire site+target deploy locks, persist steps, set running.

    Returns False (and does not start) if a lock cannot be taken.
    `target` defaults to site.primary_target; overflow passes the ephemeral Target.
    """
    site = deployment.manifest.site
    if target is None:
        target = site.primary_target
    if target is None:
        return False

    _supersede_running(site, except_pk=deployment.pk)

    holder = str(deployment.pk)
    site_lock = locks.acquire("site", site.pk, "deploy", holder)
    if site_lock is None:
        return False
    target_lock = locks.acquire("target", target.pk, "deploy", holder)
    if target_lock is None:
        locks.release("site", site.pk, "deploy", holder=holder)
        return False

    persist_steps(deployment)
    deployment.status = Deployment.Status.RUNNING
    deployment.last_heartbeat = timezone.now()
    deployment.save(update_fields=["status", "last_heartbeat"])
    return True


def _default_transport(site):
    from core.ssh import SshTransport

    return SshTransport(site.primary_target)


def _default_dns():
    from providers.fakes import FakeDnsProvider

    return FakeDnsProvider()


def _default_cert_issuer():
    from providers.fakes import FakeOriginCertIssuer

    return FakeOriginCertIssuer()


def _noop_sleep(_seconds):
    return None


def execute(deployment_id, *, transport=None, dns=None, sleep=None, cert_issuer=None):
    """Run (or resume) a deployment. Task kwargs must stay ids-only."""
    deployment = Deployment.objects.select_related(
        "manifest__site__primary_target__zone",
        "manifest__site__dns_zone__account",
    ).get(pk=deployment_id)
    if settings.HUB_TEST_MODE:
        assert_test_zone(deployment.manifest.site.primary_target.zone)
    try:
        dns, cert_issuer = _resolve_seams(
            deployment.manifest.site, dns=dns, cert_issuer=cert_issuer,
        )
    except DeploySeamRefused:
        deployment.status = Deployment.Status.FAILED
        deployment.save(update_fields=["status"])
        release_deploy_locks(deployment)
        raise
    if deployment.status == Deployment.Status.QUEUED:
        if not begin_deploy(deployment):
            return {"started": False}
        deployment.refresh_from_db()
    if deployment.status != Deployment.Status.RUNNING:
        return {"started": False, "status": deployment.status}

    touch_heartbeat(deployment)
    try:
        return _execute_running(
            deployment, transport=transport, dns=dns, sleep=sleep,
            cert_issuer=cert_issuer,
        )
    finally:
        deployment.refresh_from_db()
        if deployment.status in TERMINAL_STATUSES:
            release_deploy_locks(deployment)


def _resolve_seams(site, *, dns, cert_issuer):
    """Prod path (both unset) uses the factory. Partial injection stays T1/T2."""
    if dns is None and cert_issuer is None:
        return resolve_production_seams(site)
    if dns is None:
        dns = _default_dns()
    if cert_issuer is None:
        cert_issuer = _default_cert_issuer()
    return dns, cert_issuer


def _execute_running(deployment, *, transport, dns, sleep, cert_issuer=None):
    site = deployment.manifest.site
    if transport is None:
        transport = _default_transport(site)
    desired = _assemble_desired(
        deployment, transport=transport, dns=dns, sleep=sleep,
        cert_issuer=cert_issuer,
    )
    desired["env_mapping"] = _env_mapping_for_deploy(deployment)

    for step in deployment.steps.order_by("seq"):
        deployment.refresh_from_db()
        if deployment.status != Deployment.Status.RUNNING:
            return {"started": True, "status": deployment.status}
        if step.status in (
            DeploymentStep.Status.SUCCEEDED,
            DeploymentStep.Status.SKIPPED,
        ):
            continue
        _run_step(deployment, step, desired)

    deployment.refresh_from_db()
    if deployment.status != Deployment.Status.RUNNING:
        return {"started": True, "status": deployment.status}
    deployment.status = Deployment.Status.SUCCEEDED
    deployment.save(update_fields=["status"])
    site = deployment.manifest.site
    site.config_stale = False
    site.save(update_fields=["config_stale"])
    return {"started": True, "status": Deployment.Status.SUCCEEDED}


def rollback(deployment_id, *, transport=None, dns=None, sleep=None, cert_issuer=None):
    """Enqueue a new Deployment that re-applies the original artifact set."""
    original = Deployment.objects.select_related(
        "manifest__site__primary_target",
    ).get(pk=deployment_id)
    created = Deployment.objects.create(
        manifest=original.manifest,
        status=Deployment.Status.QUEUED,
        rollback_of=original,
    )
    return execute(
        created.pk, transport=transport, dns=dns, sleep=sleep,
        cert_issuer=cert_issuer,
    )


def _supersede_running(site, *, except_pk):
    others = Deployment.objects.filter(
        manifest__site=site,
        status=Deployment.Status.RUNNING,
    ).exclude(pk=except_pk)
    for old in others:
        old.status = Deployment.Status.SUPERSEDED
        old.save(update_fields=["status"])
        release_deploy_locks(old)


def _previous_succeeded(deployment):
    return (
        Deployment.objects.filter(
            manifest__site=deployment.manifest.site,
            status=Deployment.Status.SUCCEEDED,
        )
        .exclude(pk=deployment.pk)
        .order_by("-pk")
        .first()
    )


def _build_skipped(deployment):
    return deployment.steps.filter(
        name=DeploymentStep.Name.BUILD,
        status=DeploymentStep.Status.SKIPPED,
    ).exists()


def _stored_image_tag(deployment):
    row = DeploymentArtifact.objects.filter(
        deployment=deployment, kind="image_tag",
    ).first()
    if row is None:
        return None
    tag = (row.content or "").strip()
    return tag or None


def _walk_to_built_deploy(deployment):
    """Nearest succeeded deploy that actually built (build not skipped)."""
    rows = (
        Deployment.objects.filter(
            manifest__site=deployment.manifest.site,
            status=Deployment.Status.SUCCEEDED,
        )
        .exclude(pk=deployment.pk)
        .order_by("-pk")
    )
    for row in rows:
        build = row.steps.filter(name=DeploymentStep.Name.BUILD).first()
        if build is None or build.status != DeploymentStep.Status.SKIPPED:
            return row
    return None


def _pin_from_succeeded_history(deployment, fallback_sha):
    """Reuse the on-disk tag: stored artifact, else walk back to a real build."""
    prev = _previous_succeeded(deployment)
    if prev is not None:
        stored = _stored_image_tag(prev)
        if stored:
            sha = (prev.manifest.body or {}).get("git_sha") or fallback_sha
            return sha, stored
    built = _walk_to_built_deploy(deployment)
    if built is None:
        return fallback_sha, image_tag(fallback_sha, deployment.manifest.body or {})
    body = built.manifest.body or {}
    sha = body.get("git_sha") or fallback_sha
    return sha, _stored_image_tag(built) or image_tag(sha, body)


def _assemble_desired(deployment, *, transport, dns, sleep, cert_issuer=None):
    site = deployment.manifest.site
    body = deployment.manifest.body or {}
    slug = site.name
    git_sha = body.get("git_sha") or DEFAULT_GIT_SHA
    source_dir = body.get("source_dir") or str(_REPO_ROOT / "sample-node-site")
    domain = site.domain or body.get("domain") or f"{slug}.local"
    zone = body.get("dns_zone")
    if not zone and "." in domain:
        zone = domain.split(".", 1)[1]
    zone = zone or "example.test"
    # The DNS hand-off is Site.dns_zone — a DnsZone row a provider can be
    # constructed from — NEVER Site.primary_target.zone, which is a
    # NetworkZone (panel r2). None only for mesh_only, where ensure_dns skips.
    dns_zone = site.dns_zone

    from core.ssh import SshTransport

    if sleep is None and not isinstance(transport, SshTransport):
        sleep = _noop_sleep
        poll = 0
    else:
        poll = 1
    poll = body.get("poll_interval_s", poll)

    prev = _previous_succeeded(deployment)
    old_container = f"site-{slug}-{prev.pk}" if prev else None
    env = body.get("env")
    if isinstance(env, dict):
        env_names = list(env.keys())
    else:
        env_names = list(body.get("env_names") or [])

    if prev is not None and _build_skipped(deployment):
        git_sha, pinned_tag = _pin_from_succeeded_history(deployment, git_sha)
    else:
        pinned_tag = image_tag(git_sha, body)

    desired = {
        "transport": transport,
        "site": site,
        "site_slug": slug,
        "deployment_id": deployment.pk,
        "deployment": deployment,
        "manifest_body": body,
        "git_sha": git_sha,
        "source_dir": source_dir,
        "image_tag": pinned_tag,
        "heartbeat": lambda: touch_heartbeat(deployment),
        "old_container": old_container,
        "dns": dns,
        "zone": zone,
        "dns_zone": dns_zone,
        "domain": domain,
        "dns_values": list(body.get("dns_values") or ["127.0.0.1"]),
        "dns_proxied": bool(getattr(site, "proxied", True)),
        "poll_interval_s": poll,
        "internal_port": int(body.get("internal_port") or 20000),
        "docker_run_extra": body.get("docker_run_extra"),
        "env_names": env_names,
        "firewall_argv": list(body.get("firewall_argv") or []),
        "cert_issuer": cert_issuer,
    }
    if sleep is not None:
        desired["sleep"] = sleep
    if body.get("upstream"):
        desired["upstream"] = body["upstream"]

    arts = {}
    if deployment.rollback_of_id:
        for row in DeploymentArtifact.objects.filter(
            deployment_id=deployment.rollback_of_id,
        ):
            arts[row.kind] = row.content

    desired["dockerfile"] = arts.get("dockerfile")
    if desired["dockerfile"] is None:
        desired["dockerfile"] = _dockerfile_from_body(body)

    desired["caddy_route"] = arts.get("caddy_route")
    if desired["caddy_route"] is None:
        route_id = f"site-{slug}"
        desired["caddy_route"] = json.dumps(
            _caddy_route(desired, route_id),
            sort_keys=True,
            separators=(",", ":"),
        )

    joined = _joined_dns_values(site)
    if joined:
        desired["dns_values"] = joined
    desired["dns_set"] = arts.get("dns_set")
    if joined or desired["dns_set"] is None:
        desired["dns_set"] = json.dumps(_desired_dns_records(desired))

    if "env_names" in arts:
        desired["env_names"] = _json_list(arts["env_names"])
    if "firewall_argv" in arts:
        desired["firewall_argv"] = _json_list(arts["firewall_argv"])
    return desired


def _joined_dns_values(site):
    """Comma-joined A values from DnsRecord, or None.

    A joined overflow list must win over a stale single-A dns_set overlay.
    """
    if site is None or not getattr(site, "pk", None) or not getattr(site, "domain", None):
        return None
    from core.models import DnsRecord

    rec = DnsRecord.objects.filter(
        site=site, name=site.domain, rtype="A",
    ).first()
    if rec is None or not (rec.value or "").strip():
        return None
    parts = [part.strip() for part in rec.value.split(",") if part.strip()]
    if not parts:
        return None
    try:
        addrs = [ipaddress.IPv4Address(part) for part in parts]
    except ValueError:
        return None
    if any(addr.is_loopback or addr.is_link_local for addr in addrs):
        return None
    return [str(addr) for addr in addrs]


def _json_list(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return list(raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _run_step(deployment, step, desired=None):
    if desired is None:
        desired = _assemble_desired(
            deployment,
            transport=_default_transport(deployment.manifest.site),
            dns=_default_dns(),
            sleep=_noop_sleep,
            cert_issuer=_default_cert_issuer(),
        )
    step.status = DeploymentStep.Status.RUNNING
    step.started = timezone.now()
    step.save(update_fields=["status", "started"])
    touch_heartbeat(deployment)

    work = dict(desired)
    work["step"] = step
    try:
        _dispatch_step(deployment, step, work)
    except Exception:
        _mark_failed(deployment, step)
        raise
    try:
        _crash_if_configured(step)
    except Exception:
        _unmark_step_succeeded(step)
        raise

    if step.name == DeploymentStep.Name.CUTOVER:
        _snapshot_and_runbook(deployment, work)

    step.status = DeploymentStep.Status.SUCCEEDED
    step.finished = timezone.now()
    step.save(update_fields=["status", "finished"])
    touch_heartbeat(deployment)


def _dispatch_step(deployment, step, desired):
    name = step.name
    if name == DeploymentStep.Name.BUILD:
        ensure_build(desired)
    elif name == DeploymentStep.Name.SHIP:
        ensure_ship(desired)
    elif name == DeploymentStep.Name.MIGRATE:
        ensure_volume(desired)
        if deployment.rollback_of_id:
            ensure_volume_rollback(desired)
        ensure_migrate(desired)
    elif name == DeploymentStep.Name.START_GREEN:
        ensure_start(desired)
    elif name == DeploymentStep.Name.HEALTH_CHECK:
        ensure_health_check(desired)
    elif name == DeploymentStep.Name.DNS:
        ensure_dns(desired)
    elif name == DeploymentStep.Name.ROUTE_TLS:
        ensure_route_tls(desired)
    elif name == DeploymentStep.Name.SMOKE_TEST:
        ensure_smoke(desired)
    elif name == DeploymentStep.Name.CUTOVER:
        ensure_cutover(desired)
    else:
        raise RuntimeError(f"unknown deploy step {name}")


def _snapshot_and_runbook(deployment, desired):
    from deploys.artifacts import snapshot_artifacts
    from deploys.breakglass import write_runbook

    if not deployment.text_artifacts.exists():
        snapshot_artifacts(desired)
    if _runbook_present(desired):
        return

    slug = desired["site_slug"]
    path = f"/srv/sites/{slug}"
    transport = desired["transport"]
    made = transport.run(["mkdir", "-p", path])
    if not made.ok:
        transport.run(["sudo", "mkdir", "-p", path])
        transport.run(["sudo", "chown", f"{_ssh_user(transport)}:{_ssh_user(transport)}", path])
    runbook = f"{path}/BREAK-GLASS.md"
    transport.run(["chmod", "u+w", runbook])
    write_runbook(desired)


def _runbook_present(desired):
    transport = desired["transport"]
    path = f"/srv/sites/{desired['site_slug']}/BREAK-GLASS.md"
    return transport.probe(["test", "-f", path]).ok


def _ssh_user(transport):
    target = getattr(transport, "target", None)
    return getattr(target, "ssh_user", None) or "deploy"


def _mark_failed(deployment, step):
    """ensure_* raised: persist FAILED so the row cannot look immortal (F3)."""
    now = timezone.now()
    step.status = DeploymentStep.Status.FAILED
    step.finished = now
    step.save(update_fields=["status", "finished"])
    deployment.status = Deployment.Status.FAILED
    deployment.save(update_fields=["status"])
    release_deploy_locks(deployment)


def _env_mapping_for_deploy(deployment):
    """Decrypt env bundle + vaulted DATABASE_URL. Values stay in-process only."""
    mapping = {}
    raw = load_env_snapshot(deployment)
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            mapping = {
                str(key): "" if value is None else str(value)
                for key, value in parsed.items()
                if str(key).strip()
            }
    site = deployment.manifest.site
    from vault import service as vault_service
    from vault.models import Secret

    secret = (
        Secret.objects.filter(
            kind=Secret.Kind.DATABASE_URL,
            owner_type="site",
            owner_id=str(site.pk),
        )
        .order_by("-pk")
        .first()
    )
    if secret is not None:
        url = vault_service.get(secret, reason=f"deploy {deployment.pk} database_url")
        if isinstance(url, (bytes, bytearray)):
            url = url.decode()
        mapping["DATABASE_URL"] = str(url)
    return mapping


def _unmark_step_succeeded(step):
    """ensure_migrate may persist SUCCEEDED before the hook; resume must see it open."""
    step.refresh_from_db()
    if step.status == DeploymentStep.Status.SUCCEEDED:
        step.status = DeploymentStep.Status.RUNNING
        step.save(update_fields=["status"])


def _crash_if_configured(step):
    """Kill-matrix hook. Fires after ensure_* and before the step is succeeded."""
    flag = os.environ.get(CRASH_AFTER_ENV, "")
    if not flag:
        return
    if flag == step.name or flag == str(step.seq):
        if os.environ.get(CRASH_SIGNAL_ENV, "") == "SIGKILL":
            _unmark_step_succeeded(step)
            os.kill(os.getpid(), signal.SIGKILL)
        raise RuntimeError(f"{CRASH_AFTER_ENV}={flag}")

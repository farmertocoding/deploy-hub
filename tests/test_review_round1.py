"""Phase 2 review-round 1 regressions. Each test names the production change
that would make it fail; they must go red on HEAD 8855ef6.
"""
import json

import pytest
from django.test import override_settings
from dns_fixtures import default_dns_zone
from pipeline_fakes import REPO, PipelineTransport, fixture_body, queued_deployment

from core.models import AuditEvent, NetworkZone, Project, Site, Target
from core.transport import CommandResult, FakeTransport
from deploys.models import Deployment, DeploymentArtifact, DeploymentStep
from providers.fakes import FakeDnsProvider

pytestmark = pytest.mark.django_db

PLANTED_DB_PASSWORD = "planted-db-password-do-not-argv"
PLANTED_ENV = "PIPELINE-ENVFILE-MARKER-do-not-log"
PLANTED_DB_URL = "postgres://app:planted-dburl-do-not-log@db:5432/app"
PLANTED_LOG = "PLANTED-LOG-CHUNK-MARKER-do-not-log"
HUB_MESH = "100.64.9.9"
LINK_LOCAL_GIT = "https://169.254.169.254/o/r.git"
HUB_COLLECT = "/home/deploy/.hub/collect-once"


def _target(*, slug="r1", status=None):
    zone = NetworkZone.objects.create(name="lan", slug=f"lan-{slug}")
    kwargs = dict(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref=f"vault-{slug}",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=status or Target.Status.READY,
    )
    return Target.objects.create(**kwargs)


def _calls_blob(transport):
    return json.dumps(transport.calls, default=str)


# --- 1. provision/db.py: passwords off argv and exception text ---


class ModePostgresTransport(FakeTransport):
    """Inspect keyed on full argv. Captures put mode. Postgres exists after docker run."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.containers = set()
        self.put_modes = {}
        self.fail_psql = False

    def put(self, local_path_or_bytes, remote_path, *, mode=0o644):
        super().put(local_path_or_bytes, remote_path, mode=mode)
        self.put_modes[remote_path] = mode

    def probe(self, argv, *, timeout=60):
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv[:2] == ["docker", "inspect"] and len(argv) >= 3:
            name = argv[-1]
            if name in self.containers:
                return CommandResult(argv, exit_code=0, stdout=name)
            return CommandResult(argv, exit_code=1, stderr="Error: No such container")
        if "pg_isready" in argv:
            return CommandResult(argv)
        return CommandResult(argv)

    def run(self, argv, *, timeout=60):
        argv = list(argv)
        self.calls.append(("run", argv))
        if argv[:2] == ["docker", "run"] and "--name" in argv:
            self.containers.add(argv[argv.index("--name") + 1])
            return CommandResult(argv)
        if self.fail_psql and "psql" in argv:
            return CommandResult(
                argv, exit_code=1,
                stderr=f"ERROR: password {PLANTED_DB_PASSWORD} leaked in stderr",
            )
        return CommandResult(argv)


def test_site_db_password_absent_from_calls_and_exceptions(monkeypatch):
    """Role/superuser secrets travel in a 0600 env/SQL file, never docker argv or raised text.

    What would make this fail: -e POSTGRES_PASSWORD=…, psql -c with PASSWORD, or
    interpolating stderr that contains SQL into RuntimeError.
    """
    from core.models import Project, Site
    from provision import db as dbmod
    from provision.db import ensure_site_db

    monkeypatch.setattr(dbmod.secrets, "token_hex", lambda n=16: PLANTED_DB_PASSWORD)
    site = Site.objects.create(
        project=Project.objects.create(name="shop", slug="p-r1-shop"),
        name="shop",
        dns_zone=default_dns_zone(),
    )
    transport = ModePostgresTransport()
    ensure_site_db({"transport": transport, "site": site, "site_slug": "shop"})

    assert PLANTED_DB_PASSWORD not in _calls_blob(transport)
    assert any(mode == 0o600 for mode in transport.put_modes.values()), transport.put_modes
    env_puts = [
        remote for remote, payload in transport.files.items()
        if PLANTED_DB_PASSWORD.encode() in (
            payload if isinstance(payload, (bytes, bytearray)) else str(payload).encode()
        )
    ]
    assert env_puts, "expected the planted password in a 0600 put, not on argv"
    assert all(transport.put_modes[remote] == 0o600 for remote in env_puts)
    runs = [argv for kind, argv in transport.calls if kind == "run"]
    assert any("--env-file" in argv for argv in runs), runs
    assert any("pg_isready" in (kind, *argv) for kind, argv in transport.calls)

    transport = ModePostgresTransport()
    transport.fail_psql = True
    with pytest.raises(RuntimeError) as exc:
        ensure_site_db({"transport": transport, "site": site, "site_slug": "shop2"})
    assert PLANTED_DB_PASSWORD not in str(exc.value)
    assert PLANTED_DB_PASSWORD not in (exc.value.args[0] if exc.value.args else "")


# --- 2. monitor/tasks.py: collect_all must not return log bytes ---


def test_collect_all_result_omits_log_chunk_bytes(monkeypatch):
    """Celery/Redis must not see log_chunk.bytes. Result is {ok, n} (or ignored).

    What would make this fail: returning collect() payloads, or omitting ignore_result.
    """
    from monitor import collector as collector_mod
    from monitor.tasks import collect_all, envelope_for_collect

    target = _target(slug="clog")

    def fake_collect(tgt, transport, **kwargs):
        return {
            "schema_version": 1,
            "target_id": tgt.pk,
            "log_chunk": {"bytes": PLANTED_LOG, "file": "/var/log/caddy/access.log"},
        }

    monkeypatch.setattr(collector_mod, "collect", fake_collect)
    result = collect_all(
        envelope=envelope_for_collect(),
        transport_for=lambda _t: FakeTransport(), sleep=lambda _s: None,
    )
    assert PLANTED_LOG not in json.dumps(result)
    assert "log_chunk" not in json.dumps(result)
    assert result.get("ok") is True
    assert result.get("n") == 1
    assert collect_all.ignore_result is True
    assert target.pk


# --- 3. deploys/pipeline.py: env-file put, never body/artifacts/logs/argv ---


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True, HUB_LOCAL_SOURCE_ROOT=str(REPO))
def test_execute_injects_env_via_env_file_not_argv_or_artifacts():
    """load_env_snapshot lands in a 0600 env file and docker --env-file; values stay off exhaust.

    What would make this fail: -e KEY=secret, copying values into Manifest.body /
    DeploymentArtifact / step logs / execute kwargs, or omitting vaulted DATABASE_URL.
    """
    from deploys.env import put_env
    from deploys.pipeline import execute
    from vault import service
    from vault.models import Secret

    bundle = service.put(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type="manifest",
        owner_id="envfile-v1",
        plaintext=json.dumps({"API_KEY": PLANTED_ENV}).encode(),
    )
    site, deployment = queued_deployment(
        "envfile",
        body=fixture_body("envfile", extra={
            "env_bundle_ref": bundle.pk,
            "env_names": ["API_KEY"],
        }),
    )
    put_env(site, {"API_KEY": PLANTED_ENV})
    service.put(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
        plaintext=PLANTED_DB_URL.encode(),
    )
    transport = PipelineTransport()
    execute(deployment.pk, transport=transport, dns=FakeDnsProvider())
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED

    env_puts = []
    for remote, payload in transport.files.items():
        raw = payload if isinstance(payload, (bytes, bytearray)) else str(payload).encode()
        if PLANTED_ENV.encode() in raw and PLANTED_DB_URL.encode() in raw:
            env_puts.append((remote, raw, transport.put_modes.get(remote)))
    assert env_puts, "expected env-file put containing snapshot + DATABASE_URL"
    for remote, _raw, mode in env_puts:
        assert "/tmp/" not in remote
        assert mode == 0o600

    runs = [argv for kind, argv in transport.calls if kind == "run"]
    docker_runs = [argv for argv in runs if argv[:2] == ["docker", "run"]]
    assert docker_runs
    assert any("--env-file" in argv for argv in docker_runs)
    joined = " ".join(str(p) for argv in docker_runs for p in argv)
    assert PLANTED_ENV not in joined
    assert PLANTED_DB_URL not in joined
    assert PLANTED_ENV not in json.dumps(deployment.manifest.body)
    for artifact in DeploymentArtifact.objects.filter(deployment=deployment):
        assert PLANTED_ENV not in artifact.content
        assert PLANTED_DB_URL not in artifact.content
    for step in deployment.steps.all():
        assert PLANTED_ENV not in (step.log_text or "")
        assert PLANTED_DB_URL not in (step.log_text or "")


# --- 4. deploys/poller.py: validate git URL before ls-remote ---


def test_git_ls_remote_refuses_rebind_to_link_local(monkeypatch):
    """A host that is public at check time must not ls-remote after rebinding to IMDS."""
    from deploys.poller import git_ls_remote

    calls = {"n": 0}

    def fake_getaddrinfo(host, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 1:
            return [(2, 1, 6, "", ("8.8.8.8", 0))]
        return [(2, 1, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr("core.validators.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("deploys.poller.shutil.which", lambda _n: "/usr/bin/git")

    def boom(*args, **kwargs):
        raise AssertionError("git must not run after a blocked rebind")

    monkeypatch.setattr("deploys.poller.subprocess.run", boom)
    assert git_ls_remote("https://rebind.example.test/repo.git", "main") == ""
    assert calls["n"] >= 2


def test_poll_skips_link_local_url_without_invoking_git(monkeypatch):
    """A link-local git URL must not reach git ls-remote; skip and audit.

    What would make this fail: calling subprocess git (or injected ls_remote)
    for 169.254.169.254, or skipping without an audit row.
    """
    from deploys import poller
    from deploys.models import Manifest
    from deploys.poller import poll

    invoked = []

    def boom(*args, **kwargs):
        invoked.append((args, kwargs))
        raise AssertionError("git must not run for a blocked URL")

    monkeypatch.setattr(poller.subprocess, "run", boom)
    project = Project.objects.create(
        name="ssrf", slug="p-ssrf", git_url=LINK_LOCAL_GIT, git_ref="main",
    )
    site = Site.objects.create(project=project, name="ssrf",
                               dns_zone=default_dns_zone())
    Manifest.objects.create(site=site, version=1, body={"git_sha": "aaa"})

    poll()
    assert invoked == []
    assert AuditEvent.objects.filter(action="git-url-blocked").exists()
    assert not Deployment.objects.filter(manifest__site=site).exists()


# --- 5. catalog fail2ban: substitute Hub mesh IP ---


def test_fail2ban_apply_substitutes_mesh_ip_and_refuses_if_missing(monkeypatch):
    """Put/apply jail.local must whitelist HUB_MESH_IP; refuse rather than ship 100.64.1.1.

    What would make this fail: installing the placeholder ignoreip, or applying
    when HUB_MESH_IP is unset.
    """
    from catalog.apply import apply_entry
    from catalog.entries import ENTRIES
    from catalog.models import AppliedCatalogEntry

    target = _target(slug="f2b")
    entry = ENTRIES["fail2ban-ignoreip"]
    monkeypatch.delenv("HUB_MESH_IP", raising=False)
    transport = FakeTransport()
    assert apply_entry(target, entry, transport) is None
    assert AppliedCatalogEntry.objects.filter(target=target, entry_id=entry.id).count() == 0
    for _remote, payload in transport.files.items():
        text = payload.decode() if isinstance(payload, (bytes, bytearray)) else str(payload)
        for line in text.splitlines():
            if line.lstrip().startswith("ignoreip"):
                assert "100.64.1.1" not in line.split("#")[0]

    monkeypatch.setenv("HUB_MESH_IP", HUB_MESH)
    transport = FakeTransport()
    row = apply_entry(target, entry, transport)
    assert row is not None
    bodies = []
    for remote, payload in transport.files.items():
        text = payload.decode() if isinstance(payload, (bytes, bytearray)) else str(payload)
        bodies.append(text)
        if "ignoreip" in text:
            live = [
                line for line in text.splitlines()
                if line.lstrip().startswith("ignoreip")
            ]
            assert live, remote
            assert all(HUB_MESH in line for line in live)
            assert all("100.64.1.1" not in line.split("#")[0] for line in live)
    assert any("ignoreip" in body for body in bodies), transport.files


# --- 6. reconcile: skip mutate while site deploy lock is held ---


def test_reconcile_skips_mutate_when_site_deploy_lock_held():
    """A held site deploy OperationLock is a brake: observe, do not docker run.

    What would make this fail: repairing drift while execute() holds kind=deploy.
    """
    from test_reconciler import _mutating, _world

    from core import locks
    from core.models import OperationLock
    from reconcile.loop import tick

    site, inst, transport = _world("deplock")
    held = locks.acquire(
        OperationLock.Scope.SITE, site.pk, OperationLock.Kind.DEPLOY, "deploy-1",
    )
    assert held is not None
    tick(site, transport=transport, jitter=0)
    assert _mutating(transport) == []
    inst.refresh_from_db()
    assert inst.observed_state  # still observed


# --- 7. pipeline: ensure_* exception persists FAILED ---


def test_ensure_exception_marks_step_and_deployment_failed(monkeypatch):
    """ensure_build raising must persist FAILED on the step and deployment, not RUNNING.

    What would make this fail: leaving both rows RUNNING so the sweep thinks work continues.
    """
    from deploys import pipeline

    site, deployment = queued_deployment("failopen", body=fixture_body("failopen"))

    def boom(*_a, **_k):
        raise RuntimeError("ensure_build exploded")

    monkeypatch.setattr(pipeline, "ensure_build", boom)
    with pytest.raises(RuntimeError, match="ensure_build exploded"):
        pipeline.execute(
            deployment.pk, transport=PipelineTransport(), dns=FakeDnsProvider(),
        )
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.FAILED
    build = deployment.steps.get(name=DeploymentStep.Name.BUILD)
    assert build.status == DeploymentStep.Status.FAILED


# --- 8. health_check: pulse heartbeat during poll ---


def test_health_check_pulses_heartbeat_while_polling():
    """Warmup polls must heartbeat so a long warm cannot look stale to the sweep.

    What would make this fail: probing healthz for >2 min with no touch_heartbeat.
    """
    from deploys.steps import ensure_health_check

    pulses = []
    payloads = [
        {"live": True, "ready": False, "checks": {"n": 1}},
        {"live": True, "ready": False, "checks": {"n": 2}},
        {"live": True, "ready": True, "checks": {"n": 3}},
    ]

    def fetch():
        return payloads[len(pulses) if len(pulses) < len(payloads) else -1]

    # heartbeat counted separately from fetch
    fetches = []

    def fetch_count():
        payload = payloads[len(fetches)]
        fetches.append(payload)
        return payload

    ensure_health_check({
        "transport": FakeTransport(),
        "site_slug": "warm",
        "deployment_id": 1,
        "manifest_body": {"warmup_timeout_s": 300},
        "healthz_fetch": fetch_count,
        "heartbeat": lambda: pulses.append(1),
        "sleep": lambda _s: None,
        "poll_interval_s": 0,
    })
    assert len(fetches) == 3
    assert len(pulses) >= 2, f"expected a pulse per poll, got {len(pulses)}"


# --- 9. collector jitter offset from tick start; overlapping skip ---


def test_collect_all_jitter_offsets_from_tick_start(monkeypatch, tmp_path):
    """Fleet jitter is an offset from the Beat tick, not stacked full sleeps.

    What would make this fail: collect() sleeping jitter_s serially so two
    targets wait jitter_a + jitter_b.
    """
    from test_collector import CollectorTransport, _run_producer

    from monitor.collector import jitter_s
    from monitor.tasks import collect_all, envelope_for_collect

    a = _target(slug="jita")
    b = _target(slug="jitb")
    slept = []
    clock = {"t": 0.0}

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    def mono():
        return clock["t"]

    stdout, _log = _run_producer(tmp_path, target_id=a.pk)
    transport = CollectorTransport(stdout=stdout)
    collect_all(
        envelope=envelope_for_collect(),
        transport_for=lambda _t: transport,
        sleep=sleep,
        monotonic=mono,
    )
    ordered = list(Target.objects.filter(pk__in=[a.pk, b.pk]).order_by("pk"))
    first_j = jitter_s(ordered[0].pk)
    second_j = jitter_s(ordered[1].pk)
    assert slept[0] == first_j
    assert slept[1] == max(0, second_j - first_j)
    assert sum(slept) == max(first_j, second_j)


def test_collect_all_skips_target_when_collect_lock_held(tmp_path):
    """Overlapping ticks skip a target that already holds kind=collect.

    What would make this fail: a second collect_all putting/probing while the
    previous tick still holds the lock.
    """
    from test_collector import CollectorTransport, _noop, _run_producer

    from core import locks
    from monitor.collector import collect
    from monitor.tasks import collect_all, envelope_for_collect

    target = _target(slug="ovlap")
    stdout, _log = _run_producer(tmp_path, target_id=target.pk)
    transport = CollectorTransport(stdout=stdout)
    lock = locks.acquire("target", target.pk, "collect", "tick-other")
    assert lock is not None
    collect_all(
        envelope=envelope_for_collect(),
        transport_for=lambda _t: transport, sleep=_noop,
    )
    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts == []
    probes = [
        argv for kind, argv in transport.calls
        if kind == "probe" and argv and argv[0] == HUB_COLLECT
    ]
    assert probes == []
    # unlocked path still works
    locks.release("target", target.pk, "collect", holder="tick-other")
    collect(target, transport, sleep=_noop)
    assert any(kind == "put" for kind, _ in transport.calls)


def test_collector_script_is_not_world_writable_tmp(tmp_path):
    """Collector script lands under ~/.hub (0700), never world-writable /tmp.

    What would make this fail: putting to /tmp/hub-collect-once.
    """
    from test_collector import CollectorTransport, _noop, _run_producer

    from monitor.collector import collect

    stdout, log = _run_producer(tmp_path)
    transport = CollectorTransport(stdout=stdout)
    collect(type("T", (), {"pk": 42, "ssh_user": "deploy"})(), transport, sleep=_noop)
    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts
    assert puts[0] == HUB_COLLECT
    assert not puts[0].startswith("/tmp/")
    assert log

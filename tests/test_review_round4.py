"""Phase 2 review-round 4 regressions. Each test names the production change
that would make it fail; they must go red on HEAD 0637fe6.
"""
import json
import os
import subprocess
import sys

import pytest
from pipeline_fakes import PipelineTransport
from test_ensure_start import IMAGE_TAG, StartTransport
from test_review_round3 import PRODUCER, _fake_empty_health_on_port, _zone_target

from core.models import Project, Site, SiteInstance
from core.transport import FakeTransport

LISTEN = 21000
SECRET = "r4-secret-do-not-argv"


def _docker_runs(transport):
    return [
        argv for kind, argv in transport.calls
        if kind == "run" and argv[:2] == ["docker", "run"]
    ]


def _port_envs(argv):
    return [
        argv[i + 1]
        for i, part in enumerate(argv[:-1])
        if part == "-e" and str(argv[i + 1]).startswith("PORT=")
    ]


def _start_desired(transport, *, extra=None, body=None):
    desired = {
        "transport": transport,
        "site_slug": "r4port",
        "deployment_id": 4,
        "manifest_body": body if body is not None else {},
        "image_tag": IMAGE_TAG,
    }
    if extra:
        desired.update(extra)
    return desired


@pytest.mark.parametrize("extra, body, want", [
    ({"internal_port": LISTEN}, {"port": 3000}, LISTEN),
    ({}, {"port": 3000}, 3000),
    ({}, {"PORT": 9090}, 9090),
    ({}, {}, 8080),
])
def test_docker_run_argv_sets_numeric_port_env(extra, body, want):
    """docker run must pass -e PORT=<listen> (numeric), never Hub-invented -p.

    What would make this fail: omitting -e PORT, using a non-numeric value, or
    publishing -p/EXPOSE from _docker_run_argv itself.
    """
    from deploys.steps import ensure_start

    transport = StartTransport()
    ensure_start(_start_desired(transport, extra=extra, body=body))
    runs = _docker_runs(transport)
    assert runs, transport.calls
    argv = runs[0]
    port_vals = _port_envs(argv)
    assert port_vals, argv
    raw = str(port_vals[0]).split("=", 1)[1]
    assert raw.isdigit(), argv
    assert int(raw) == want, argv
    assert "-p" not in argv


def test_docker_run_keeps_env_file_and_omits_secrets():
    """--env-file stays; vaulted values must not appear as docker -e.

    What would make this fail: stuffing env_mapping onto argv, dropping
    --env-file, or skipping -e PORT once the env file exists.
    """
    from deploys.steps import ensure_start

    transport = StartTransport()
    ensure_start(_start_desired(transport, extra={
        "internal_port": LISTEN,
        "env_mapping": {"API_KEY": SECRET},
    }))
    runs = _docker_runs(transport)
    assert runs, transport.calls
    argv = runs[0]
    joined = " ".join(str(part) for part in argv)
    assert SECRET not in joined, argv
    assert "--env-file" in argv
    port_vals = _port_envs(argv)
    assert port_vals, argv
    assert str(port_vals[0]).split("=", 1)[1] == str(LISTEN)


@pytest.mark.django_db
def test_hub_shaped_inspect_curls_env_port_from_docker_run(tmp_path):
    """Empty Health/PortBindings/ExposedPorts still curls PORT from inspect Env.

    The Env value is the listen _docker_run_argv actually emits (internal_port),
    not a magic 18080 the pipeline never sets.

    What would make this fail: docker run omitting PORT so inspect Env has none,
    curling :80, or mapping Hub-shaped inspect to {live:false} then docker restart.
    """
    from test_collector import CollectorTransport, _noop

    from deploys.steps import ensure_start
    from monitor.collector import collect
    from reconcile.loop import tick

    slug = "hubhz"
    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    target = _zone_target(slug)
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(
        project=project, name=slug, primary_target=target, reconcile_enabled=True,
        dns_zone=default_dns_zone(),
    )
    inst = SiteInstance.objects.create(
        site=site,
        target=target,
        desired_image_tag="app:recon",
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.ABSENT,
        consecutive_failures=0,
        internal_port=LISTEN,
    )
    name = f"site-{slug}-{inst.pk}"
    start_transport = StartTransport()
    ensure_start({
        "transport": start_transport,
        "site_slug": slug,
        "deployment_id": inst.pk,
        "manifest_body": {},
        "image_tag": IMAGE_TAG,
        "internal_port": inst.internal_port,
    })
    runs = _docker_runs(start_transport)
    assert runs, start_transport.calls
    port_vals = _port_envs(runs[0])
    assert port_vals, runs[0]
    raw = str(port_vals[0]).split("=", 1)[1]
    assert raw.isdigit()
    listen = int(raw)
    assert listen == LISTEN
    assert listen != 18080

    payload = {
        "live": True,
        "ready": False,
        "checks": {"upstream": "upstream-down"},
    }
    _fake_empty_health_on_port(
        tmp_path, name, port=listen, body=json.dumps(payload),
    )
    log = tmp_path / "access.log"
    log.write_bytes(b'{"status":200}\n')
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [sys.executable, str(PRODUCER), str(target.pk), "0", str(log)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    produced = json.loads(proc.stdout)
    checks = (produced.get("healthz") or {}).get("checks") or {}
    assert name in checks, produced.get("healthz")
    per = checks[name]
    assert per.get("live") is True, per
    assert per.get("ready") is False, per

    transport = CollectorTransport(stdout=proc.stdout)
    collect(target, transport, sleep=_noop)
    tick_transport = PipelineTransport()
    tick(site, transport=tick_transport, jitter=0)
    restarts = [
        argv for kind, argv in tick_transport.calls
        if kind == "run" and argv[:2] == ["docker", "restart"]
    ]
    assert restarts == [], tick_transport.calls


@pytest.mark.django_db
def test_tick_skips_restart_when_inspect_has_no_port(tmp_path):
    """Empty Health + no PortBindings/ExposedPorts + no Env PORT must not restart.

    What would make this fail: mapping that inspect to {live:false} → UNHEALTHY
    → docker restart of a container Hub cannot curl yet.
    """
    from test_collector import CollectorTransport, _noop

    from monitor.collector import collect
    from reconcile.loop import tick

    slug = "noport"
    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    target = _zone_target(slug)
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(
        project=project, name=slug, primary_target=target, reconcile_enabled=True,
        dns_zone=default_dns_zone(),
    )
    inst = SiteInstance.objects.create(
        site=site,
        target=target,
        desired_image_tag="app:recon",
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.ABSENT,
        consecutive_failures=0,
        internal_port=LISTEN,
    )
    name = f"site-{slug}-{inst.pk}"
    _fake_empty_health_on_port(tmp_path, name, port=None, body="{}")
    log = tmp_path / "access.log"
    log.write_bytes(b'{"status":200}\n')
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [sys.executable, str(PRODUCER), str(target.pk), "0", str(log)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    produced = json.loads(proc.stdout)
    checks = (produced.get("healthz") or {}).get("checks") or {}
    assert name in checks, produced.get("healthz")

    transport = CollectorTransport(stdout=proc.stdout)
    collect(target, transport, sleep=_noop)
    tick_transport = PipelineTransport()
    tick(site, transport=tick_transport, jitter=0)
    inst.refresh_from_db()
    restarts = [
        argv for kind, argv in tick_transport.calls
        if kind == "run" and argv[:2] == ["docker", "restart"]
    ]
    assert restarts == [], tick_transport.calls
    assert inst.observed_state != SiteInstance.ObservedState.UNHEALTHY, inst.observed_state
    assert inst.observed_state == SiteInstance.ObservedState.WARMING


def test_fake_transport_docker_run_records_port_flag():
    """Same PORT contract on FakeTransport (not only StartTransport).

    What would make this fail: _docker_run_argv skipping -e PORT when inspect
    is the stock FakeTransport success-empty path.
    """
    from deploys.steps import _docker_run_argv

    argv = _docker_run_argv({
        "internal_port": LISTEN,
        "image_tag": IMAGE_TAG,
        "site_slug": "ft",
        "deployment_id": 1,
        "manifest_body": {},
        "env_file": "/home/deploy/.hub/site-ft-1.env",
    }, "site-ft-1")
    transport = FakeTransport()
    transport.run(argv)
    recorded = [a for kind, a in transport.calls if kind == "run"]
    assert recorded
    port_vals = _port_envs(recorded[0])
    assert port_vals, recorded[0]
    raw = str(port_vals[0]).split("=", 1)[1]
    assert raw.isdigit()
    assert int(raw) == LISTEN
    assert "--env-file" in recorded[0]
    assert SECRET not in " ".join(str(p) for p in recorded[0])

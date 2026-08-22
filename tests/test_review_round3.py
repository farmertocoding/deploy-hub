"""Phase 2 review-round 3 regressions. Each test names the production change
that would make it fail; they must go red on HEAD a7999f0.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from pipeline_fakes import PipelineTransport

from core.models import AuditEvent, NetworkZone, Project, Site, SiteInstance, Target
from core.transport import FakeTransport

pytestmark = pytest.mark.django_db

HUB_MESH = "100.64.9.9"
LIVE_JAIL = "/etc/fail2ban/jail.local"
PRODUCER = Path(__file__).resolve().parent.parent / "monitor" / "collect_once.py"
CONTAINER_IP = "192.0.2.1"


def _zone_target(slug, *, ssh_user="deploy"):
    zone = NetworkZone.objects.create(name="lan", slug=f"lan-{slug}")
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user=ssh_user,
        ssh_key_ref=f"vault-{slug}",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def _installs(transport):
    return [
        argv for kind, argv in transport.mutating_calls()
        if kind == "run" and argv and argv[0] == "install"
    ]


def test_fail2ban_install_keeps_live_jail_dest(monkeypatch):
    """install must copy hub staging onto /etc/fail2ban/jail.local, not collapse dest.

    What would make this fail: _jail_pin_paths treating every jail.local as a pin
    so install staging staging, or recording AppliedCatalogEntry after that collapse.
    """
    from catalog.apply import apply_entry
    from catalog.entries import ENTRIES
    from catalog.models import AppliedCatalogEntry

    target = _zone_target("f2b-dest", ssh_user="root")
    entry = ENTRIES["fail2ban-ignoreip"]
    monkeypatch.setenv("HUB_MESH_IP", HUB_MESH)
    transport = FakeTransport()
    row = apply_entry(target, entry, transport)
    staging = "/home/root/.hub/jail.local"
    installs = _installs(transport)
    assert installs, transport.calls
    assert all(staging in argv for argv in installs)
    assert all(LIVE_JAIL in argv for argv in installs), installs
    assert row is not None
    assert AppliedCatalogEntry.objects.filter(target=target, entry_id=entry.id).exists()
    assert staging in transport.files
    body = transport.files[staging]
    text = body.decode() if isinstance(body, (bytes, bytearray)) else str(body)
    live = [line for line in text.splitlines() if line.lstrip().startswith("ignoreip")]
    assert live
    assert all(HUB_MESH in line for line in live)
    assert all("100.64.1.1" not in line.split("#")[0] for line in live)
    for argv in installs:
        assert argv[-1] == LIVE_JAIL
        assert staging in argv[:-1]


def test_fail2ban_collapsed_live_dest_does_not_record(monkeypatch):
    """Same-file install (live dest rewritten to staging) must not count as applied.

    What would make this fail: FakeTransport succeeding on install staging staging
    and still writing AppliedCatalogEntry.
    """
    from catalog import apply as apply_mod
    from catalog.apply import apply_entry, argv_steps
    from catalog.entries import ENTRIES
    from catalog.models import AppliedCatalogEntry

    def every_jail_local(entry):
        return {
            part
            for step in argv_steps(entry.fix)
            for part in step
            if str(part).endswith("jail.local")
        }

    monkeypatch.setattr(apply_mod, "_jail_pin_paths", every_jail_local)
    target = _zone_target("f2b-collapse", ssh_user="root")
    entry = ENTRIES["fail2ban-ignoreip"]
    monkeypatch.setenv("HUB_MESH_IP", HUB_MESH)
    transport = FakeTransport()
    row = apply_entry(target, entry, transport)
    assert row is None
    assert AppliedCatalogEntry.objects.filter(
        target=target, entry_id=entry.id,
    ).count() == 0
    assert all(LIVE_JAIL not in argv for argv in _installs(transport))


def _fake_empty_health_on_port(tmp_path, name, *, port, body):
    """Hub-shaped inspect: empty Health, PortBindings, ExposedPorts.

    ``port`` is the listen value `_docker_run_argv` would put in Config.Env as
    PORT=<n>. None means Env has no PORT (pre-fix Hub, or a container Hub did
    not start).
    """
    env = ["PATH=/usr/bin"]
    if port is not None:
        env = [f"PORT={port}", *env]
    inspect = {
        "State": {"Running": True},
        "NetworkSettings": {
            "IPAddress": CONTAINER_IP,
            "Networks": {"bridge": {"IPAddress": CONTAINER_IP}},
        },
        "HostConfig": {"PortBindings": {}},
        "Config": {
            "ExposedPorts": {},
            "Env": env,
        },
    }
    script = tmp_path / "tool.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"NAME = {name!r}\n"
        f"IP = {CONTAINER_IP!r}\n"
        f"PORT = {port!r}\n"
        f"BODY = {body!r}\n"
        f"INSPECT = {inspect!r}\n"
        "tool = os.path.basename(sys.argv[0])\n"
        "args = sys.argv[1:]\n"
        "if tool == 'docker':\n"
        "    if args and args[0] == 'ps':\n"
        "        sys.stdout.write(NAME + '\\trunning\\n')\n"
        "        sys.exit(0)\n"
        "    if args and args[0] == 'inspect':\n"
        "        fmt = ''\n"
        "        if '--format' in args:\n"
        "            fmt = args[args.index('--format') + 1]\n"
        "        if fmt:\n"
        "            if 'Health' in fmt:\n"
        "                sys.stdout.write('')\n"
        "            elif 'IPAddress' in fmt:\n"
        "                sys.stdout.write(IP + '\\n')\n"
        "            elif 'PortBindings' in fmt:\n"
        "                sys.stdout.write(json.dumps(INSPECT['HostConfig']['PortBindings']))\n"
        "            elif 'ExposedPorts' in fmt:\n"
        "                sys.stdout.write(json.dumps(INSPECT['Config']['ExposedPorts']))\n"
        "            elif 'Env' in fmt or 'PORT' in fmt:\n"
        "                sys.stdout.write('\\n'.join(INSPECT['Config']['Env']) + '\\n')\n"
        "            elif 'json' in fmt:\n"
        "                sys.stdout.write(json.dumps(INSPECT))\n"
        "            sys.exit(0)\n"
        "        sys.stdout.write(json.dumps([INSPECT]))\n"
        "        sys.exit(0)\n"
        "    sys.exit(1)\n"
        "if tool == 'curl':\n"
        "    url = args[-1] if args else ''\n"
        "    if PORT is None:\n"
        "        sys.exit(22)\n"
        "    want = 'http://%s:%s/healthz' % (IP, PORT)\n"
        "    if url == want:\n"
        "        sys.stdout.write(BODY)\n"
        "        sys.exit(0)\n"
        "    sys.exit(22)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    docker = tmp_path / "docker"
    curl = tmp_path / "curl"
    docker.symlink_to(script)
    curl.symlink_to(script)
    return docker


def test_tick_uses_n2_healthz_json_on_listen_port(tmp_path, monkeypatch):
    """Empty Health + N2 JSON on $PORT must not docker restart without observe=.

    What would make this fail: curling implicit :80, treating HTTP 200 as
    live=ready, or _read_observed forcing reason to "" so N3 never brakes.
    """
    from test_collector import CollectorTransport, _noop

    from monitor.collector import collect
    from reconcile.loop import tick

    slug = "n2hz"
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
        internal_port=20000,
    )
    name = f"site-{slug}-{inst.pk}"
    payload = {
        "live": True,
        "ready": False,
        "checks": {"upstream": "upstream-down"},
    }
    _fake_empty_health_on_port(
        tmp_path, name, port=inst.internal_port, body=json.dumps(payload),
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
    nested = per.get("checks") if isinstance(per.get("checks"), dict) else {}
    reason = (per.get("reason") or nested.get("upstream") or "")
    assert "upstream-down" in str(reason) or nested.get("upstream") == "upstream-down", per

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
    warming = inst.observed_state == SiteInstance.ObservedState.WARMING
    braked = AuditEvent.objects.filter(action="reconcile_upstream_down").exists()
    assert warming or braked, inst.observed_state

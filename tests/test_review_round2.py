"""Phase 2 review-round 2 regressions. Each test names the production change
that would make it fail; they must go red on HEAD 6e72026.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from pipeline_fakes import PipelineTransport

from core.models import NetworkZone, Project, Site, SiteInstance, Target
from core.transport import FakeTransport
from deploys.models import Deployment, Manifest

pytestmark = pytest.mark.django_db

PLANTED_LOG = "PLANTED-LOG-CHUNK-MARKER-do-not-log"
HUB_MESH = "100.64.9.9"
PRODUCER = Path(__file__).resolve().parent.parent / "monitor" / "collect_once.py"


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


def _capture_git(monkeypatch):
    """Record git_ls_remote subprocess argv/env; validate_git_url still resolve=True."""
    from deploys import poller

    seen_validate = []
    captured = {}

    def fake_validate(url, *, resolve=True):
        seen_validate.append({"url": url, "resolve": resolve})
        return url

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(
            argv, 0, stdout="deadbeef\trefs/heads/main\n", stderr="",
        )

    monkeypatch.setattr(poller, "validate_git_url", fake_validate)
    monkeypatch.setattr(poller.shutil, "which", lambda _n: "/usr/bin/git")
    monkeypatch.setattr(poller.subprocess, "run", fake_run)
    return seen_validate, captured


# --- 1. deploys/poller.py: isolate Hub git client ---


def test_git_ls_remote_ssh_does_not_see_hub_agent(monkeypatch):
    """ssh:// ls-remote must not inherit SSH_AUTH_SOCK / GIT_ASKPASS.

    What would make this fail: subprocess.run without an isolated env, or
    validate_git_url(..., resolve=False) at use.
    """
    from deploys.poller import git_ls_remote

    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/hub-agent.sock")
    monkeypatch.setenv("GIT_ASKPASS", "/usr/bin/hub-askpass")
    monkeypatch.setenv("SSH_AGENT_PID", "999")
    seen, captured = _capture_git(monkeypatch)

    sha = git_ls_remote("ssh://git@example.test/o/r.git", "main")
    assert sha == "deadbeef"
    assert seen == [{"url": "ssh://git@example.test/o/r.git", "resolve": True}]
    env = captured["env"]
    assert env is not None, "git must pass an isolated env, not inherit the Hub process"
    assert "SSH_AUTH_SOCK" not in env
    assert "GIT_ASKPASS" not in env
    assert "SSH_AGENT_PID" not in env
    assert env.get("GIT_TERMINAL_PROMPT") == "0"
    ssh_cmd = env.get("GIT_SSH_COMMAND") or ""
    assert "IdentitiesOnly" in ssh_cmd
    assert "IdentityAgent=none" in ssh_cmd


def test_git_ls_remote_http_disables_redirects_and_credential_helper(monkeypatch):
    """Hub git must pass http.followRedirects=false so a public host cannot
    bounce onto link-local after validate_git_url.

    What would make this fail: bare `git ls-remote` with the process env.
    """
    from deploys.poller import git_ls_remote

    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/hub-agent.sock")
    monkeypatch.setenv("GIT_CONFIG", "/etc/hub/gitconfig")
    seen, captured = _capture_git(monkeypatch)

    sha = git_ls_remote("https://example.test/o/r.git", "main")
    assert sha == "deadbeef"
    assert seen == [{"url": "https://example.test/o/r.git", "resolve": True}]
    argv = captured["argv"]
    assert "ls-remote" in argv
    assert "http.followRedirects=false" in argv
    assert "credential.helper=" in argv
    assert argv.index("http.followRedirects=false") < argv.index("ls-remote")
    env = captured["env"]
    assert env is not None, "git must pass an isolated env, not inherit the Hub process"
    assert "SSH_AUTH_SOCK" not in env
    assert env.get("GIT_CONFIG") != "/etc/hub/gitconfig"
    assert env.get("GIT_TERMINAL_PROMPT") == "0"


# --- 2–3. catalog fail2ban: singular IPv4 + ssh_user hub path ---


@pytest.mark.parametrize("bad", [
    "100.64.0.0/10",
    "100.64.9.9 1.2.3.4",
    "100.64.9.9\n10.0.0.1",
    "not-an-ip",
    "::1",
    "2001:db8::1",
])
def test_fail2ban_refuses_non_single_ipv4_mesh_ip(monkeypatch, bad):
    """HUB_MESH_IP must be one IPv4, same as harden-ubuntu.sh. CIDR / extra
    tokens / IPv6 must not write AppliedCatalogEntry.

    What would make this fail: str.replace of any non-empty string into ignoreip.
    """
    from catalog.apply import apply_entry
    from catalog.entries import ENTRIES
    from catalog.models import AppliedCatalogEntry

    target = _zone_target("f2b-bad")
    entry = ENTRIES["fail2ban-ignoreip"]
    monkeypatch.setenv("HUB_MESH_IP", bad)
    transport = FakeTransport()
    assert apply_entry(target, entry, transport) is None
    assert AppliedCatalogEntry.objects.filter(target=target, entry_id=entry.id).count() == 0
    assert transport.files == {}


def test_fail2ban_apply_installs_via_target_ssh_user_path(monkeypatch):
    """fix argv must install the same hub_join path put used, including ssh_user=root.

    What would make this fail: rewriting only the literal /home/deploy/.hub/jail.local
    while Target.ssh_user defaults to root and put lands under /home/root/.hub.
    """
    import inspect

    from catalog import apply as apply_mod
    from catalog.apply import apply_entry
    from catalog.entries import ENTRIES

    source = inspect.getsource(apply_mod._apply_fail2ban)
    assert "/home/deploy/.hub/jail.local" not in source, (
        "fix argv rewrite must not special-case only /home/deploy"
    )
    target = _zone_target("f2b-root", ssh_user="root")
    entry = ENTRIES["fail2ban-ignoreip"]
    monkeypatch.setenv("HUB_MESH_IP", HUB_MESH)
    transport = FakeTransport()
    row = apply_entry(target, entry, transport)
    assert row is not None
    staging = "/home/root/.hub/jail.local"
    assert staging in transport.files
    assert "/home/deploy/.hub/jail.local" not in transport.files
    body = transport.files[staging]
    text = body.decode() if isinstance(body, (bytes, bytearray)) else str(body)
    live = [line for line in text.splitlines() if line.lstrip().startswith("ignoreip")]
    assert live
    assert all(HUB_MESH in line for line in live)
    assert all("100.64.1.1" not in line.split("#")[0] for line in live)
    installs = [
        argv for kind, argv in transport.mutating_calls()
        if kind == "run" and argv and argv[0] == "install"
    ]
    assert installs, transport.calls
    assert all(staging in argv for argv in installs)
    assert all("/home/deploy/.hub/jail.local" not in argv for argv in installs)


# --- 4. collector persist: drop log_chunk.bytes ---


def test_collect_payload_omits_planted_log_bytes(tmp_path):
    """Target.collect_payload (Hub dump) must not keep Caddy log_chunk.bytes.

    What would make this fail: assigning the full collect() JSON onto Target.
    """
    from test_collector import CollectorTransport, _noop

    from monitor.collector import collect

    log = tmp_path / "access.log"
    log.write_text(PLANTED_LOG + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(PRODUCER), "42", "0", str(log)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert PLANTED_LOG in proc.stdout
    target = _zone_target("clogbytes")
    transport = CollectorTransport(stdout=proc.stdout)
    result = collect(target, transport, sleep=_noop)
    assert PLANTED_LOG in (result.get("log_chunk") or {}).get("bytes", "")
    target.refresh_from_db()
    stored = target.collect_payload
    assert stored is not None
    blob = json.dumps(stored)
    assert PLANTED_LOG not in blob
    chunk = stored.get("log_chunk") or {}
    assert "inode" in chunk
    assert "offset" in chunk
    assert "bytes" not in chunk


# --- 7. reconcile _desired is last succeeded ---


@pytest.mark.parametrize("later_status", [
    Deployment.Status.FAILED,
    Deployment.Status.QUEUED,
])
def test_tick_does_not_run_failed_deployment_container(later_status):
    """After FAILED/QUEUED (lock released), tick must not docker-run site-{slug}-{N}.

    What would make this fail: _desired = latest pk, so the live succeeded
    container looks absent and ensure_start starts a second copy.
    """
    from test_reconciler import _start_stop_runs, _world

    from reconcile.loop import tick

    site, _inst, transport = _world("despk")
    m1 = Manifest.objects.create(site=site, version=1, body={"git_sha": "aaa"})
    succeeded = Deployment.objects.create(
        manifest=m1, status=Deployment.Status.SUCCEEDED,
    )
    m2 = Manifest.objects.create(site=site, version=2, body={"git_sha": "bbb"})
    later = Deployment.objects.create(
        manifest=m2, status=later_status,
    )
    live = f"site-despk-{succeeded.pk}"
    bad = f"site-despk-{later.pk}"
    transport.containers[live] = "running"
    tick(site, transport=transport, jitter=0)
    runs = _start_stop_runs(transport)
    assert all(bad not in argv for argv in runs), runs
    assert not any(argv[:2] == ["docker", "run"] and bad in argv for argv in runs)
    assert not any(argv[:2] == ["docker", "stop"] and live in argv for argv in runs)


def test_apply_rechecks_site_and_target_deploy_lock_before_mutate():
    """_apply must refuse mutate if a site or target kind=deploy lock exists.

    What would make this fail: re-checking only the reconcile holder, so a
    begin_deploy that wins after tick().exists() still docker-runs.
    """
    from django.utils import timezone
    from test_reconciler import _world

    from core import locks
    from core.models import OperationLock
    from reconcile.loop import _apply

    now = timezone.now()
    site, inst, transport = _world("rechk")
    held = locks.acquire(
        OperationLock.Scope.SITE, site.pk, OperationLock.Kind.DEPLOY, "deploy-race",
    )
    assert held is not None
    assert _apply(site, inst, transport, "start", now) is False
    assert not any(
        kind == "run" and isinstance(argv, list) and argv[:2] == ["docker", "run"]
        for kind, argv in transport.calls
    )

    locks.release(
        OperationLock.Scope.SITE, site.pk, OperationLock.Kind.DEPLOY,
        holder="deploy-race",
    )
    transport.calls.clear()
    tgt = locks.acquire(
        OperationLock.Scope.TARGET, inst.target_id, OperationLock.Kind.DEPLOY,
        "deploy-tgt",
    )
    assert tgt is not None
    assert _apply(site, inst, transport, "start", now) is False
    assert not any(
        kind == "run" and isinstance(argv, list) and argv[:2] == ["docker", "run"]
        for kind, argv in transport.calls
    )


# --- 8. collect_once healthz is per-container, not hardcoded true ---


def _fake_docker(tmp_path, name, health="unhealthy"):
    script = tmp_path / "docker"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"NAME = {name!r}\n"
        f"HEALTH = {health!r}\n"
        "args = sys.argv[1:]\n"
        "if args and args[0] == 'ps':\n"
        "    sys.stdout.write(NAME + '\\trunning\\n')\n"
        "    sys.exit(0)\n"
        "if args and args[0] == 'inspect':\n"
        "    fmt = ''\n"
        "    if '--format' in args:\n"
        "        fmt = args[args.index('--format') + 1]\n"
        "    if 'IPAddress' in fmt:\n"
        "        sys.stdout.write('192.0.2.1\\n')\n"
        "    else:\n"
        "        sys.stdout.write(HEALTH + '\\n')\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_tick_observes_unhealthy_from_producer_healthz(tmp_path, monkeypatch):
    """Producer JSON with a failing per-container healthz must drive unhealthy
    without observe=.

    What would make this fail: collect_once._healthz hardcoding live/ready true
    so every docker-ps running container looks RUNNING.
    """
    from test_collector import CollectorTransport, _noop

    from monitor.collector import collect
    from reconcile.loop import tick

    slug = "prodhz"
    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    target = _zone_target(slug)
    site = Site.objects.create(
        project=project, name=slug, primary_target=target, reconcile_enabled=True,
    )
    inst = SiteInstance.objects.create(
        site=site,
        target=target,
        desired_image_tag="app:recon",
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.ABSENT,
        consecutive_failures=1,
        internal_port=20000,
    )
    name = f"site-{slug}-{inst.pk}"
    _fake_docker(tmp_path, name, health="unhealthy")
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
    payload = json.loads(proc.stdout)
    checks = (payload.get("healthz") or {}).get("checks") or {}
    assert name in checks, payload.get("healthz")
    per = checks[name]
    assert per.get("live") is False or per.get("ready") is False, per

    transport = CollectorTransport(stdout=proc.stdout)
    collect(target, transport, sleep=_noop)
    tick_transport = PipelineTransport()
    tick(site, transport=tick_transport, jitter=0)
    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.UNHEALTHY

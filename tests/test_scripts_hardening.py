"""Host scripts under scripts/ (HARD-Q8 / R2 / R3 / V2).

T1 tests drive the scripts with PATH stubs. The T2 twice-run uses
hub-test-target when docker is up; that one test is the only skipif.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess
import textwrap

import pytest

pytest_plugins = ["test_hub_test_target"]

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
HARDEN = SCRIPTS / "harden-ubuntu.sh"
CF_UFW = SCRIPTS / "update-cloudflare-ufw.sh"
VERIFY = SCRIPTS / "verify-hardening.sh"
WATCH = SCRIPTS / "server-watch.sh"
UPGRADE = SCRIPTS / "hub-upgrade.sh"

HUB_MESH_IP = "100.64.1.8"
TAILNET_SLASH10 = "100.64.0.0/10"


def _write_stub(bindir: pathlib.Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text("#!/bin/bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _stub_env(tmp_path: pathlib.Path, *, mesh_up: bool = True) -> tuple[dict, pathlib.Path]:
    """PATH stubs that record mutating argv. Return (env, mutate_log)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    mutate = tmp_path / "mutate.log"
    mutate.write_text("", encoding="utf-8")
    keys = tmp_path / "home" / ".ssh"
    keys.mkdir(parents=True)
    (keys / "authorized_keys").write_text("ssh-ed25519 AAAA test-key\n", encoding="utf-8")
    log_q = str(mutate)

    _write_stub(
        bindir,
        "systemctl",
        f"""
printf 'systemctl %s\\n' "$*" >> "{log_q}"
case "${{1:-}}" in
  reload|restart|enable|disable|start|stop) echo "MUTATE systemctl $*" >> "{log_q}" ;;
  is-active|is-enabled|is-system-running) echo "active"; exit 0 ;;
esac
exit 0
""",
    )
    _write_stub(
        bindir,
        "ufw",
        f"""
printf 'ufw %s\\n' "$*" >> "{log_q}"
case " $* " in
  *" enable "*|*" --force enable "*) echo "MUTATE ufw $*" >> "{log_q}" ;;
esac
echo "Status: inactive"
exit 0
""",
    )
    _write_stub(
        bindir,
        "sshd",
        f"""
printf 'sshd %s\\n' "$*" >> "{log_q}"
case " $* " in
  *" -t "*) exit 0 ;;
esac
exit 0
""",
    )
    _write_stub(
        bindir,
        "apt-get",
        f"""
printf 'apt-get %s\\n' "$*" >> "{log_q}"
echo "MUTATE apt-get $*" >> "{log_q}"
exit 0
""",
    )
    _write_stub(
        bindir,
        "apt",
        f"""
printf 'apt %s\\n' "$*" >> "{log_q}"
echo "MUTATE apt $*" >> "{log_q}"
exit 0
""",
    )
    _write_stub(
        bindir,
        "tee",
        f"""
printf 'tee %s\\n' "$*" >> "{log_q}"
echo "MUTATE tee $*" >> "{log_q}"
cat >/dev/null
exit 0
""",
    )
    _write_stub(
        bindir,
        "sysctl",
        f"""
printf 'sysctl %s\\n' "$*" >> "{log_q}"
echo "MUTATE sysctl $*" >> "{log_q}"
exit 0
""",
    )
    if mesh_up:
        tailscale_body = """
if [[ "${1:-}" == "status" ]]; then
  echo "100.64.1.8  hub  linux  -"
  exit 0
fi
exit 0
"""
    else:
        tailscale_body = """
echo "Tailscale is stopped." >&2
exit 1
"""
    _write_stub(bindir, "tailscale", tailscale_body)
    _write_stub(
        bindir,
        "fail2ban-client",
        f'printf \'fail2ban-client %s\\n\' "$*" >> "{log_q}"; echo "{HUB_MESH_IP}"; exit 0\n',
    )
    _write_stub(bindir, "chronyc", 'echo "Leap status     : Normal"; exit 0\n')
    _write_stub(bindir, "curl", 'echo "stub-curl"; exit 0\n')
    _write_stub(bindir, "lsb_release", 'echo "jammy"; exit 0\n')

    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["HOME"] = str(tmp_path / "home")
    env["HUB_MESH_IP"] = HUB_MESH_IP
    env["PROFILE"] = "hub"
    env["SSH_CONNECTION"] = f"{HUB_MESH_IP} 54321 100.64.1.1 22"
    env.pop("SUDO_USER", None)
    return env, mutate


def _run(argv, *, env, cwd=None, timeout=30):
    return subprocess.run(
        argv,
        cwd=cwd or REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
def test_scripts_live_under_scripts_dir():
    """The host set lives in scripts/. hub-upgrade.sh may be the Task 19 stub.

    What would make this fail: scripts missing, or the Task 19 header gone.
    """
    for path in (HARDEN, CF_UFW, VERIFY, WATCH, UPGRADE):
        assert path.is_file(), f"missing {path.relative_to(REPO)}"
        assert path.stat().st_mode & stat.S_IXUSR
    header = UPGRADE.read_text(encoding="utf-8")
    assert "# Task 19 fills C6" in header


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
def test_dry_run_mutating_nothing(tmp_path):
    """DRY_RUN=1 prints the plan and must not reload sshd or enable ufw.

    What would make this fail: DRY_RUN still calling systemctl reload / ufw enable.
    """
    env, mutate = _stub_env(tmp_path)
    env["DRY_RUN"] = "1"
    env["PROFILE"] = "hub"
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "DRY_RUN" in combined
    log = mutate.read_text(encoding="utf-8")
    assert "MUTATE" not in log
    assert "systemctl reload" not in log
    assert "ufw --force enable" not in log
    assert "ufw enable" not in log


@pytest.mark.req("HARD-R2-SSHD-VALIDATE-FIRST")
def test_sshd_t_before_reload():
    """R2: sshd -t appears before any ssh reload in the apply path.

    What would make this fail: reload without a prior sshd -t, or -t only in a comment.
    """
    lines = []
    for raw in HARDEN.read_text(encoding="utf-8").splitlines():
        stripped = raw.split("#", 1)[0].strip()
        if stripped:
            lines.append(stripped)
    body = "\n".join(lines)
    t_pos = body.find("sshd -t")
    reload_pos = body.find("reload ssh")
    if reload_pos == -1:
        reload_pos = body.find("reload sshd")
    assert t_pos != -1, "harden-ubuntu.sh never calls sshd -t"
    assert reload_pos != -1, "harden-ubuntu.sh never reloads ssh"
    assert t_pos < reload_pos


@pytest.mark.req("HARD-R2-SSHD-VALIDATE-FIRST")
def test_refuses_disable_password_auth_without_authorized_keys(tmp_path):
    """Must not disable password auth when no authorized_keys file exists.

    What would make this fail: applying the drop-in anyway, or reloading sshd.
    """
    env, mutate = _stub_env(tmp_path)
    env["DRY_RUN"] = "0"
    (tmp_path / "home" / ".ssh" / "authorized_keys").unlink()
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode != 0
    text = (result.stdout + result.stderr).lower()
    assert "authorized_keys" in text
    log = mutate.read_text(encoding="utf-8")
    assert "MUTATE systemctl reload" not in log
    assert "sshd" not in log or "reload" not in log


@pytest.mark.req("HARD-R3-IGNOREIP")
def test_ignoreip_is_hub_mesh_ip_not_tailnet_slash10(tmp_path):
    """ignoreip is HUB_MESH_IP only; the /10 line is commented, never live.

    What would make this fail: ignoreip = 100.64.0.0/10, or omitting HUB_MESH_IP.
    """
    env, _mutate = _stub_env(tmp_path)
    env["DRY_RUN"] = "1"
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert HUB_MESH_IP in combined
    for raw in combined.splitlines():
        line = raw.strip()
        if "ignoreip" in line and TAILNET_SLASH10 in line:
            assert line.lstrip().startswith("#"), f"live /10 ignoreip: {line!r}"
    source = HARDEN.read_text(encoding="utf-8")
    for raw in source.splitlines():
        stripped = raw.strip()
        if TAILNET_SLASH10 in stripped and not stripped.startswith("#"):
            # Allow the string only in a comment or a refusal error.
            allowed = "refuse" in stripped.lower() or "never" in stripped.lower()
            assert allowed, f"uncommented /10: {stripped!r}"
    assert "HUB_MESH_IP" in source
    assert TAILNET_SLASH10 in source  # commented survival, per V1


@pytest.mark.req("HARD-V2-MESH-BEFORE-FIREWALL")
def test_refuses_tailscale0_posture_off_mesh(tmp_path):
    """V2: tailscale0-only firewall is refused unless the mesh is up.

    What would make this fail: enabling ufw allow in on tailscale0 while
    tailscale status fails, or treating the whole /10 as the session check.
    """
    env, mutate = _stub_env(tmp_path, mesh_up=False)
    env["DRY_RUN"] = "0"
    env["PROFILE"] = "hub"
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode != 0
    text = (result.stdout + result.stderr).lower()
    assert "mesh" in text or "tailscale" in text
    log = mutate.read_text(encoding="utf-8")
    assert "MUTATE ufw" not in log
    assert "tailscale0" not in log or "enable" not in log


@pytest.mark.req("HARD-V2-MESH-BEFORE-FIREWALL")
def test_refuses_tailscale0_when_sudo_drops_ssh_connection(tmp_path):
    """sudo env_reset drops SSH_CONNECTION; that is not a verified console.

    What would make this fail: treating unset SSH_CONNECTION as local console
    and enabling tailscale0-only ufw after `sudo ./harden-ubuntu.sh`.
    """
    env, mutate = _stub_env(tmp_path, mesh_up=True)
    env["DRY_RUN"] = "0"
    env["PROFILE"] = "hub"
    env["SUDO_USER"] = "deploy"
    env["HUB_STAMP_DIR"] = str(tmp_path / "stamps")
    env.pop("SSH_CONNECTION", None)
    env.pop("SSH_CLIENT", None)
    env.pop("SSH_TTY", None)
    env.pop("HUB_CONFIRM_LOCAL", None)
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode != 0
    text = (result.stdout + result.stderr).lower()
    assert "mesh" in text or "session" in text
    log = mutate.read_text(encoding="utf-8")
    assert "MUTATE ufw" not in log


@pytest.mark.req("HARD-V2-MESH-BEFORE-FIREWALL")
def test_mesh_session_via_ssh_client_survives_sudo_env_reset(tmp_path):
    """SSH_CLIENT kept through sudoers env_keep still proves a mesh session.

    What would make this fail: requiring SSH_CONNECTION only, so env_keep of
    SSH_CLIENT cannot save a mesh sudo.
    """
    env, mutate = _stub_env(tmp_path, mesh_up=True)
    env["DRY_RUN"] = "1"
    env["PROFILE"] = "hub"
    env["SUDO_USER"] = "deploy"
    env.pop("SSH_CONNECTION", None)
    env["SSH_CLIENT"] = f"{HUB_MESH_IP} 54321 22"
    env.pop("HUB_CONFIRM_LOCAL", None)
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode == 0, result.stderr
    assert "DRY_RUN" in result.stdout + result.stderr
    assert "MUTATE ufw" not in mutate.read_text(encoding="utf-8")


@pytest.mark.req("HARD-V2-MESH-BEFORE-FIREWALL")
def test_explicit_hub_confirm_local_allows_console(tmp_path):
    """A real console must set HUB_CONFIRM_LOCAL=1; silence is not enough.

    What would make this fail: allowing an unset SSH_* session without the flag.
    """
    env, _mutate = _stub_env(tmp_path, mesh_up=True)
    env["DRY_RUN"] = "1"
    env["PROFILE"] = "hub"
    env.pop("SSH_CONNECTION", None)
    env.pop("SSH_CLIENT", None)
    env["HUB_CONFIRM_LOCAL"] = "1"
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode == 0, result.stderr


@pytest.mark.req("HARD-R3-IGNOREIP")
def test_reloads_fail2ban_after_writing_ignoreip(tmp_path):
    """Writing jail.local must reload fail2ban when the unit is already active.

    What would make this fail: returning early on is-active and leaving the
    default ignoreip loaded.
    """
    env, _mutate = _stub_env(tmp_path, mesh_up=True)
    env["DRY_RUN"] = "1"
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "reload" in combined and "fail2ban" in combined
    assert HUB_MESH_IP in combined
    assert f"ignoreip = 127.0.0.1/8 {HUB_MESH_IP}" in combined


@pytest.mark.req("HARD-R2-SSHD-VALIDATE-FIRST")
def test_failed_sshd_t_leaves_live_dropin_untouched(tmp_path):
    """sshd -t -f a temp drop-in; on failure the live file is not replaced.

    What would make this fail: installing the drop-in first, then sshd -t.
    """
    bindir = tmp_path / "bin"
    live = tmp_path / "99-hub-hardening.conf"
    live.write_text("KEEPME\n", encoding="utf-8")
    env, mutate = _stub_env(tmp_path, mesh_up=True)
    env["DRY_RUN"] = "0"
    env["HUB_SSHD_DROPIN"] = str(live)
    env["HUB_JAIL_LOCAL"] = str(tmp_path / "jail.local")
    env["HUB_STAMP_DIR"] = str(tmp_path / "stamps")
    _write_stub(
        bindir,
        "sshd",
        f"""
printf 'sshd %s\\n' "$*" >> "{mutate}"
case " $* " in
  *" -t "*) echo "bad drop-in" >&2; exit 1 ;;
esac
exit 0
""",
    )
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    result = _run(["bash", str(HARDEN)], env=env)
    assert result.returncode != 0
    assert live.read_text(encoding="utf-8") == "KEEPME\n"
    log = mutate.read_text(encoding="utf-8")
    assert "sshd" in log and "-t" in log and "-f" in log
    assert "MUTATE systemctl reload" not in log


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
def test_update_cloudflare_ufw_aborts_on_bad_fetch(tmp_path):
    """Bad Cloudflare list (empty, HTML, non-CIDR) must abort before ufw changes.

    What would make this fail: continuing into ufw delete/allow after a bad body.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    mutate = tmp_path / "mutate.log"
    mutate.write_text("", encoding="utf-8")
    bad = tmp_path / "ips-v4.txt"
    bad.write_text("<html>error</html>\nnot-a-cidr\n", encoding="utf-8")
    _write_stub(
        bindir,
        "curl",
        f"""
if [[ "$*" == *"-f"* ]] || [[ "$*" == *"-fsSL"* ]] || [[ "$*" == *"-fsS"* ]]; then
  cat "{bad}"
  exit 0
fi
cat "{bad}"
exit 0
""",
    )
    _write_stub(
        bindir,
        "ufw",
        f'echo "MUTATE ufw $*" >> "{mutate}"; exit 0\n',
    )
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["CLOUDFLARE_IPS_V4_URL"] = "https://example.invalid/ips-v4"
    env["CLOUDFLARE_IPS_V6_URL"] = "https://example.invalid/ips-v6"
    result = _run(["bash", str(CF_UFW)], env=env)
    assert result.returncode != 0
    text = (result.stdout + result.stderr).lower()
    assert "abort" in text or "refuse" in text or "invalid" in text or "fetch" in text
    assert mutate.read_text(encoding="utf-8").strip() == ""


def _docker_available():
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    return probe.returncode == 0


@pytest.mark.t2
@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.skipif(not _docker_available(), reason="docker is not available")
def test_harden_twice_second_run_no_mutating_transport(hub_target):
    """T2: second harden-ubuntu.sh apply does not reload sshd or enable ufw (D6).

    What would make this fail: second run calling systemctl reload / ufw enable,
    or binding Hub docker.sock into the target.
    """
    from test_hub_test_target import SOCK, _docker, _exec

    inspect = _docker(["inspect", hub_target.container], check=True).stdout
    assert SOCK not in inspect

    _docker(
        ["cp", str(HARDEN), f"{hub_target.container}:/usr/local/sbin/harden-ubuntu.sh"],
        check=True,
    )
    _exec(hub_target.container, ["mkdir", "-p", "/root/.ssh"], check=True)
    _exec(
        hub_target.container,
        ["cp", "/home/deploy/.ssh/authorized_keys", "/root/.ssh/authorized_keys"],
        check=True,
    )
    stub_dir = "/tmp/hub-harden-stubs"
    log = "/tmp/hub-harden-mutate.log"
    _exec(hub_target.container, ["mkdir", "-p", stub_dir], check=True)
    stub_tailscale = textwrap.dedent(
        """\
        #!/bin/sh
        echo "100.64.1.8  hub  linux  -"
        exit 0
        """
    )
    _exec(
        hub_target.container,
        ["tee", f"{stub_dir}/tailscale"],
        stdin=stub_tailscale,
        check=True,
    )
    recorder = textwrap.dedent(
        f"""\
        #!/bin/sh
        echo "$0 $*" >> {log}
        case "$0 $*" in
          *reload*|*enable*|*restart*)
            echo "MUTATE $0 $*" >> {log}
            ;;
        esac
        case "$0" in
          *apt-get|*apt)
            echo "MUTATE $0 $*" >> {log}
            ;;
        esac
        exit 0
        """
    )
    for name in ("systemctl", "ufw", "apt-get", "apt"):
        _exec(
            hub_target.container,
            ["tee", f"{stub_dir}/{name}"],
            stdin=recorder,
            check=True,
        )
    _exec(hub_target.container, ["chmod", "-R", "a+x", stub_dir], check=True)
    _exec(hub_target.container, ["sh", "-c", f": > {log}"], check=True)

    run_env = [
        "env",
        f"PATH={stub_dir}:/usr/sbin:/usr/bin:/bin",
        "PROFILE=target",
        f"HUB_MESH_IP={HUB_MESH_IP}",
        f"SSH_CONNECTION={HUB_MESH_IP} 1 100.64.1.1 22",
        "DRY_RUN=0",
        "bash",
        "/usr/local/sbin/harden-ubuntu.sh",
    ]
    first = _exec(hub_target.container, run_env, timeout=120)
    assert first.returncode == 0, first.stdout + first.stderr

    _exec(hub_target.container, ["sh", "-c", f": > {log}"], check=True)
    second = _exec(hub_target.container, run_env, timeout=120)
    assert second.returncode == 0, second.stdout + second.stderr
    second_log = _exec(hub_target.container, ["cat", log], check=True).stdout
    assert "MUTATE" not in second_log
    lower = second_log.lower()
    assert "reload" not in lower
    assert "ufw --force enable" not in lower
    assert "ufw enable" not in lower

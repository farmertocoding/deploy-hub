"""hub-upgrade.sh (C6 / HARD-Q8 fifth script): drain-check, dump, rollback.

T1 drives the script with PATH stubs and injected HUB_CHECK_RUNNING. CI must
not pull Hub images — DRY_RUN and stubs only.
"""
from __future__ import annotations

import os
import pathlib
import stat
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
UPGRADE = REPO / "scripts" / "hub-upgrade.sh"
HARDENING_DOC = REPO / "docs" / "plan" / "server-hardening.md"
KEK_MARKER = "KEK-MARKER-NEVER-IN-HUB-DUMP"


def _write_stub(bindir: pathlib.Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text("#!/bin/bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _command_lines(source: str) -> list[str]:
    lines = []
    for raw in source.splitlines():
        stripped = raw.split("#", 1)[0].strip()
        if stripped:
            lines.append(stripped)
    return lines


def _pg_dump_lines(source: str) -> list[str]:
    return [line for line in _command_lines(source) if "pg_dump" in line]


def _stub_upgrade_env(
    tmp_path: pathlib.Path, *, running_count: str = "0"
) -> tuple[dict, pathlib.Path, pathlib.Path]:
    """PATH stubs that record docker/pg_dump/systemctl. Return (env, mutate, dumps)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    mutate = tmp_path / "mutate.log"
    mutate.write_text("", encoding="utf-8")
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    log_q = str(mutate)
    keyfile = tmp_path / "vault.key"
    keyfile.write_text(KEK_MARKER + "\n", encoding="utf-8")
    keyfile.chmod(0o600)

    _write_stub(
        bindir,
        "pg_dump",
        f"""
printf 'pg_dump %s\\n' "$*" >> "{log_q}"
echo "MUTATE pg_dump $*" >> "{log_q}"
out=""
prev=""
for a in "$@"; do
  if [[ "$prev" == "-f" || "$prev" == "--file" ]]; then
    out="$a"
  fi
  case "$a" in
    --file=*) out="${{a#--file=}}" ;;
  esac
  prev="$a"
done
if [[ -n "$out" ]]; then
  printf 'FAKE-HUB-DUMP\\n' > "$out"
fi
exit 0
""",
    )
    _write_stub(
        bindir,
        "docker",
        f"""
printf 'docker %s\\n' "$*" >> "{log_q}"
echo "MUTATE docker $*" >> "{log_q}"
exit 0
""",
    )
    _write_stub(
        bindir,
        "systemctl",
        f"""
printf 'systemctl %s\\n' "$*" >> "{log_q}"
echo "MUTATE systemctl $*" >> "{log_q}"
exit 0
""",
    )
    _write_stub(
        bindir,
        "curl",
        f'printf \'curl %s\\n\' "$*" >> "{log_q}"; exit 0\n',
    )

    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["DRY_RUN"] = "0"
    env["HUB_CHECK_RUNNING"] = f"printf '%s\\n' '{running_count}'"
    env["HUB_DUMP_DIR"] = str(dumps)
    env["HUB_VAULT_KEYFILE"] = str(keyfile)
    env["VAULT_KEYFILE"] = str(keyfile)
    env.pop("SUDO_USER", None)
    return env, mutate, dumps


def _run(argv, *, env, timeout=30):
    return subprocess.run(
        argv,
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
def test_bash_n_clean():
    """bash -n must accept hub-upgrade.sh (scripts-lint still applies).

    What would make this fail: a syntax error in scripts/hub-upgrade.sh.
    """
    result = _run(["bash", "-n", str(UPGRADE)], env=os.environ.copy())
    assert result.returncode == 0, result.stderr


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
def test_refuses_when_deployment_running(tmp_path):
    """A running Deployment count > 0 exits non-zero before dump/build.

    What would make this fail: proceeding into pg_dump/docker/systemctl when
    HUB_CHECK_RUNNING prints 1, or exiting 0 anyway (the Task 19 stub).
    """
    env, mutate, dumps = _stub_upgrade_env(tmp_path, running_count="1")
    result = _run(["bash", str(UPGRADE)], env=env)
    assert result.returncode != 0
    text = (result.stdout + result.stderr).lower()
    assert "running" in text
    assert "deployment" in text
    log = mutate.read_text(encoding="utf-8")
    assert "MUTATE" not in log
    assert "pg_dump" not in log
    assert "docker" not in log
    assert "systemctl" not in log
    assert list(dumps.iterdir()) == []


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
def test_hold_through_build_waits_then_proceeds(tmp_path):
    """HUB_DRAIN_TIMEOUT_S holds: a deploy that drains during the wait upgrades.

    What would make this fail: refusing immediately despite HUB_DRAIN_TIMEOUT_S,
    never re-checking the running count, or proceeding without pg_dump after
    the drain completes.
    """
    env, mutate, dumps = _stub_upgrade_env(tmp_path, running_count="1")
    marker = tmp_path / "first-check-done"
    # First invocation prints 1 (running), every later one prints 0 (drained).
    env["HUB_CHECK_RUNNING"] = (
        f"if [ -e '{marker}' ]; then echo 0; else touch '{marker}'; echo 1; fi"
    )
    env["HUB_DRAIN_TIMEOUT_S"] = "5"
    env["HUB_DRAIN_POLL_S"] = "1"
    result = _run(["bash", str(UPGRADE)], env=env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert marker.exists(), "running count was never checked"
    text = (result.stdout + result.stderr).lower()
    assert "waiting" in text
    log = mutate.read_text(encoding="utf-8")
    assert "pg_dump" in log
    assert list(dumps.iterdir()), "expected a Hub DB dump after the drain"


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
def test_hold_through_build_still_refuses_after_timeout(tmp_path):
    """A deploy that never drains still refuses after HUB_DRAIN_TIMEOUT_S.

    What would make this fail: waiting forever, or falling through into
    pg_dump/docker/systemctl when the count stays above zero at timeout.
    """
    env, mutate, dumps = _stub_upgrade_env(tmp_path, running_count="1")
    env["HUB_DRAIN_TIMEOUT_S"] = "2"
    env["HUB_DRAIN_POLL_S"] = "1"
    result = _run(["bash", str(UPGRADE)], env=env)
    assert result.returncode != 0
    text = (result.stdout + result.stderr).lower()
    assert "running" in text
    assert "deployment" in text
    log = mutate.read_text(encoding="utf-8")
    assert "MUTATE" not in log
    assert "pg_dump" not in log
    assert list(dumps.iterdir()) == []


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
def test_rollback_flag_documented():
    """--rollback is in --help and restores the previous kept image in the doc.

    What would make this fail: no --help/--rollback, or server-hardening.md
    omitting that --rollback restores the previous kept image.
    """
    result = _run(["bash", str(UPGRADE), "--help"], env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    help_text = result.stdout + result.stderr
    assert "--rollback" in help_text
    assert "previous" in help_text.lower()
    doc = HARDENING_DOC.read_text(encoding="utf-8")
    assert "--rollback" in doc
    assert "previous" in doc.lower()
    assert "image" in doc.lower()
    # Provenance block tracks this script's version in the same change.
    assert "hub-upgrade.sh" in doc
    assert "v2026-08-20 (Task 19 stub" not in doc


@pytest.mark.req("HARD-Q8-SCRIPTS-TESTED")
@pytest.mark.req("SEC-69-KEK-NEVER-IN-BACKUPS")
def test_dump_does_not_include_kek(tmp_path):
    """pg_dump is the Hub DB only; dump argv and bytes never include the KEK.

    What would make this fail: passing VAULT_KEYFILE / the keyfile path to
    pg_dump, catting the keyfile into the backup, or omitting pg_dump entirely.
    """
    source = UPGRADE.read_text(encoding="utf-8")
    dump_lines = _pg_dump_lines(source)
    assert dump_lines, "hub-upgrade.sh never calls pg_dump"
    for line in dump_lines:
        assert "VAULT_KEYFILE" not in line
        assert "HUB_VAULT_KEYFILE" not in line
        assert "vault.key" not in line
        assert "/etc/deploy-hub" not in line

    env, mutate, dumps = _stub_upgrade_env(tmp_path, running_count="0")
    result = _run(["bash", str(UPGRADE)], env=env)
    assert result.returncode == 0, result.stderr + result.stdout
    log = mutate.read_text(encoding="utf-8")
    assert "pg_dump" in log
    assert "VAULT_KEYFILE" not in log
    assert "vault.key" not in log
    assert str(tmp_path / "vault.key") not in log
    assert KEK_MARKER not in log

    dump_files = list(dumps.iterdir())
    assert dump_files, "expected a Hub DB dump under HUB_DUMP_DIR"
    for path in dump_files:
        data = path.read_bytes()
        assert KEK_MARKER.encode() not in data
        assert path.name != "vault.key"

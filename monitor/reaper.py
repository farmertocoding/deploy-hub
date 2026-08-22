"""Prefix-only test-plane reaper. argv lists; never touch names outside hub-t3-."""
from __future__ import annotations

import os
import subprocess  # nosec B404 — argv lists only (require_t3_name-guarded), never a shell
from pathlib import Path

NAME_PREFIX = "hub-t3-"
VERSION_TIMEOUT_S = 5
REPO = Path(__file__).resolve().parent.parent
DEFAULT_LEASE_ROOT = REPO / "tmp"
# Pinned test-plane token env (D-043). The NAME, never a credential.
TEST_ZONE_TOKEN_ENV = "HUB_TEST_CF_TOKEN"  # nosec B105


def test_zone_token_present():
    """True when the pinned test-plane token env is set (M4 / D-043)."""
    return bool(os.environ.get(TEST_ZONE_TOKEN_ENV, "").strip())


class T3NameError(ValueError):
    """Name is outside the hub-t3- reaper prefix."""


class ReaperUnavailable(Exception):
    """Multipass is missing or the host is not a test plane."""


def require_t3_name(name):
    if not str(name).startswith(NAME_PREFIX):
        raise T3NameError(
            f"refusing {name!r}: test-plane names must start with {NAME_PREFIX!r}"
        )
    return name


def list_argv():
    return ["multipass", "list", "--format", "csv"]


def delete_purge_argv(name):
    require_t3_name(name)
    return ["multipass", "delete", "--purge", name]


def version_argv():
    return ["multipass", "version"]


def _run(argv, *, timeout=60):
    if not isinstance(argv, (list, tuple)) or any(not isinstance(p, str) for p in argv):
        raise TypeError("argv must be a list of str — never a shell string")
    # nosec justification: argv is a typed list built by the *_argv helpers
    # above, every name passes require_t3_name, and shell=True never appears.
    return subprocess.run(  # nosec B603
        list(argv), capture_output=True, text=True, timeout=timeout)


def multipass_available():
    try:
        result = subprocess.run(  # nosec B603 — fixed ["multipass", "version"] argv
            version_argv(),
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def delete_purge(name, *, run_fn=None):
    require_t3_name(name)
    runner = run_fn or _run
    try:
        result = runner(delete_purge_argv(name))
    except OSError as exc:
        raise ReaperUnavailable("multipass absent") from exc
    if getattr(result, "returncode", 0) == 0:
        return result
    err = f"{getattr(result, 'stderr', '')} {getattr(result, 'stdout', '')}".lower()
    if "does not exist" in err or "not found" in err:
        return result
    raise RuntimeError(
        f"multipass delete --purge {name} failed: "
        f"{getattr(result, 'stderr', '') or getattr(result, 'stdout', '')}"
    )


def list_names(*, run_fn=None):
    runner = run_fn or _run
    try:
        result = runner(list_argv())
    except OSError as exc:
        raise ReaperUnavailable("multipass absent") from exc
    if getattr(result, "returncode", 0) != 0:
        err = f"{getattr(result, 'stderr', '')} {getattr(result, 'stdout', '')}".lower()
        if "does not exist" in err or "not found" in err:
            return []
        raise RuntimeError(f"multipass list failed: {getattr(result, 'stderr', '')}")
    names = []
    for i, line in enumerate((result.stdout or "").splitlines()):
        if i == 0 and line.lower().startswith("name"):
            continue
        raw = line.split(",", 1)[0].strip()
        if raw:
            names.append(raw)
    return names


def _lease_names(root):
    root = Path(root)
    if not root.is_dir():
        return []
    names = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name != ".t3-lease" and not path.name.endswith(".t3-lease"):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                names.append(name)
    return names


def reap_test_plane(*, list_fn=None, delete_fn=None, lease_root=None):
    """List, then delete+purge every `hub-t3-*`. Never touch other names.

    `list_fn` / `delete_fn` are injectable so T1 can use a Fake listing.
    """
    listed = list(list_fn() if list_fn is not None else list_names())
    leased = _lease_names(DEFAULT_LEASE_ROOT if lease_root is None else lease_root)
    delete = delete_fn if delete_fn is not None else delete_purge
    seen = set()
    for name in [*listed, *leased]:
        if not name.startswith(NAME_PREFIX) or name in seen:
            continue
        seen.add(name)
        delete(name)

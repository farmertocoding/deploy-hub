"""T3 Multipass driver. Argv lists only; never bind Hub docker.sock."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from dataclasses import dataclass

NAME_PREFIX = "hub-t3-"
DEFAULT_IMAGE = "22.04"
DEFAULT_USER = "deploy"
VERSION_TIMEOUT_S = 5

# `- default` keeps the image's default user (multipass injects its own SSH
# key there; a `users:` list without it drops that user and multipass exec
# can never connect again). The runcmd enables `ssh` only: Ubuntu has no
# `sshd` unit and a failing runcmd leaves cloud-init degraded.
CLOUD_INIT = """\
#cloud-config
package_update: true
packages:
  - openssh-server
users:
  - default
  - name: deploy
    gecos: one-shot deploy user
    groups: [sudo]
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: true
runcmd:
  - systemctl enable --now ssh
"""


class T3NameError(ValueError):
    """Name is outside the hub-t3- reaper prefix."""


@dataclass(frozen=True)
class MultipassVM:
    name: str
    ipv4: str
    user: str


def require_t3_name(name):
    if not str(name).startswith(NAME_PREFIX):
        raise T3NameError(
            f"refusing {name!r}: test-plane names must start with {NAME_PREFIX!r}"
        )
    return name


def version_argv():
    return ["multipass", "version"]


def list_argv():
    return ["multipass", "list", "--format", "csv"]


def launch_argv(name, cpus, mem, disk, image=DEFAULT_IMAGE, cloud_init_path=None):
    require_t3_name(name)
    argv = [
        "multipass",
        "launch",
        image,
        "--name",
        name,
        "--cpus",
        str(cpus),
        "--memory",
        str(mem),
        "--disk",
        str(disk),
    ]
    if cloud_init_path:
        argv.extend(["--cloud-init", str(cloud_init_path)])
    return argv


def exec_argv(vm, argv):
    require_t3_name(vm.name)
    if not isinstance(argv, (list, tuple)) or any(not isinstance(p, str) for p in argv):
        raise TypeError("exec argv must be a list of str")
    return ["multipass", "exec", vm.name, "--", *argv]


def transfer_argv(src, dest):
    if not isinstance(src, str) or not isinstance(dest, str):
        raise TypeError("transfer paths must be str")
    _require_transfer_name(src)
    _require_transfer_name(dest)
    return ["multipass", "transfer", src, dest]


def delete_purge_argv(name):
    require_t3_name(name)
    return ["multipass", "delete", "--purge", name]


def _require_transfer_name(spec):
    if ":" in spec and not spec.startswith("/"):
        require_t3_name(spec.split(":", 1)[0])


def _run(argv, *, timeout=60):
    if not isinstance(argv, (list, tuple)) or any(not isinstance(p, str) for p in argv):
        raise TypeError("argv must be a list of str — never a shell string")
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)


def multipass_available():
    try:
        result = subprocess.run(
            version_argv(),
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def waiver_illegal_if(probe):
    """A host-without-multipass waiver is illegal when Multipass is present.

    `probe` is `multipass_available` (or a bool / thunk). Task 16 may plant a
    dated waiver; this helper refuses that silent-green when the host can run T3.
    """
    present = probe() if callable(probe) else bool(probe)
    return bool(present)


def _runner(run_fn, timeout):
    """Use an injected run_fn as-is; default _run gets an explicit timeout."""
    if run_fn is not None:
        return run_fn
    return lambda argv: _run(argv, timeout=timeout)


def launch(name, cpus, mem, disk, image=DEFAULT_IMAGE, *, run_fn=None, timeout=900):
    require_t3_name(name)
    runner = _runner(run_fn, timeout)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", prefix="hub-t3-cloud-init-", delete=False
    ) as fh:
        fh.write(CLOUD_INIT)
        init_path = fh.name
    argv = launch_argv(name, cpus, mem, disk, image=image, cloud_init_path=init_path)
    result = runner(argv)
    if getattr(result, "returncode", 0) != 0:
        err = getattr(result, "stderr", "") or getattr(result, "stdout", "")
        raise RuntimeError(f"multipass launch {name} failed: {err}")
    ipv4 = info_ipv4(name, run_fn=runner)
    return MultipassVM(name=name, ipv4=ipv4, user=DEFAULT_USER)


def exec(vm, argv, *, run_fn=None, timeout=300):  # noqa: A001 — brief name; argv list only
    runner = _runner(run_fn, timeout)
    result = runner(exec_argv(vm, argv))
    if getattr(result, "returncode", 0) != 0:
        err = getattr(result, "stderr", "") or getattr(result, "stdout", "")
        raise RuntimeError(f"multipass exec {vm.name} failed: {err}")
    return result


def exec_result(vm, argv, *, run_fn=None, timeout=120):
    """multipass exec; return the CompletedProcess even when the command is red."""
    runner = _runner(run_fn, timeout)
    return runner(exec_argv(vm, argv))


# EHOSTUNREACH from `multipass exec` while the daemon-side launch succeeded is
# not a boot wait: on macOS 15+ it is the Local Network privacy permission
# denying the client process tree (canonical/multipass#3766/#3864/#4588).
# Waiting out the full deadline turns a host misconfiguration into an opaque
# TimeoutError, so after a short grace of nothing but no-route results the
# poll fails fast and says what to fix.
NO_ROUTE_MARKER = "No route to host"
NO_ROUTE_GRACE_S = 30
NO_ROUTE_HINT = (
    "every multipass client connection returns EHOSTUNREACH while the VM "
    "launched fine (daemon-side SSH worked) — on macOS this is the Local "
    "Network privacy permission denying the app running the tests, not a VM "
    "boot failure. Grant it under System Settings > Privacy & Security > "
    "Local Network, then re-run."
)


def wait_exec(vm, argv, *, ready, deadline, timeout=30, run_fn=None):
    """Poll exec_result until `ready(result)` or `deadline`."""
    last = None
    no_route_since = None
    while time.time() < deadline:
        last = exec_result(vm, argv, run_fn=run_fn, timeout=timeout)
        if ready(last):
            return last
        err = f"{getattr(last, 'stdout', '')} {getattr(last, 'stderr', '')}"
        if getattr(last, "returncode", 0) != 0 and NO_ROUTE_MARKER in err:
            no_route_since = no_route_since or time.time()
            if time.time() - no_route_since >= NO_ROUTE_GRACE_S:
                raise TimeoutError(
                    f"waiting for {argv!r} on {vm.name}: {NO_ROUTE_HINT}"
                )
        else:
            no_route_since = None
        time.sleep(2)
    stdout = getattr(last, "stdout", "") if last is not None else ""
    stderr = getattr(last, "stderr", "") if last is not None else ""
    raise TimeoutError(
        f"waiting for {argv!r} on {vm.name}: stdout={stdout!r} stderr={stderr!r}"
    )


def transfer(src, dest, *, run_fn=None, timeout=120):
    runner = _runner(run_fn, timeout)
    result = runner(transfer_argv(src, dest))
    if getattr(result, "returncode", 0) != 0:
        err = getattr(result, "stderr", "") or getattr(result, "stdout", "")
        raise RuntimeError(f"multipass transfer failed: {err}")
    return result


def delete_purge(name, *, run_fn=None):
    require_t3_name(name)
    runner = run_fn or _run
    result = runner(delete_purge_argv(name))
    if getattr(result, "returncode", 0) == 0:
        return result
    err = f"{getattr(result, 'stderr', '')} {getattr(result, 'stdout', '')}".lower()
    if "does not exist" in err or "not found" in err:
        return result
    raise RuntimeError(
        f"multipass delete --purge {name} failed: "
        f"{getattr(result, 'stderr', '') or getattr(result, 'stdout', '')}"
    )


def info_ipv4(name, *, run_fn=None):
    require_t3_name(name)
    runner = run_fn or _run
    result = runner(["multipass", "info", name, "--format", "json"])
    if getattr(result, "returncode", 0) != 0:
        return ""
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return ""
    info = payload.get("info") or {}
    entry = info.get(name) or {}
    addrs = entry.get("ipv4") or []
    if isinstance(addrs, list) and addrs:
        return str(addrs[0])
    return ""


def list_names(*, run_fn=None):
    runner = run_fn or _run
    result = runner(list_argv())
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

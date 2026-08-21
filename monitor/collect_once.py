#!/usr/bin/env python3
"""On-target collector: one JSON blob per SSH session (REL-C3)."""
import json
import os
import shutil
import subprocess  # nosec B404 — argv-list docker ps, never shell=True
import sys
import time

LOG = os.environ.get("HUB_COLLECT_LOG", "/var/log/caddy/access.log")
CHUNK = 65536
SCHEMA_VERSION = 1


def _metrics():
    load1 = mem_pct = disk_pct = None
    try:
        with open("/proc/loadavg", encoding="utf-8") as fh:
            load1 = float(fh.read().split()[0])
    except OSError:
        pass
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal") or 0
        avail = info.get("MemAvailable") or 0
        mem_pct = round(100.0 * (1 - avail / total), 2) if total else None
    except (OSError, ValueError):
        pass
    try:
        du = shutil.disk_usage("/")
        disk_pct = round(100.0 * du.used / du.total, 2) if du.total else None
    except OSError:
        pass
    return {"load1": load1, "mem_pct": mem_pct, "disk_pct": disk_pct}


def _containers():
    docker = shutil.which("docker") or "/usr/bin/docker"
    try:
        proc = subprocess.run(  # nosec B603 — argv list; absolute or which()'d docker
            [docker, "ps", "-a", "--format", "{{.Names}}\t{{.State}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    rows = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        name, _, state = line.partition("\t")
        rows.append({"name": name, "state": state or "unknown"})
    return rows


def _log_chunk(path, offset):
    try:
        st = os.stat(path)
        inode = st.st_ino
        with open(path, "rb") as fh:
            start = 0 if offset > st.st_size else offset
            fh.seek(start)
            data = fh.read(CHUNK)
            new_off = fh.tell()
        return {
            "file": path,
            "inode": inode,
            "offset": new_off,
            "bytes": data.decode("utf-8", "replace"),
        }
    except OSError:
        return {"file": path, "inode": 0, "offset": 0, "bytes": ""}


def _clock():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _healthz():
    return {"live": True, "ready": True, "checks": {}}


def main():
    target_id = sys.argv[1] if len(sys.argv) > 1 else ""
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    log_file = sys.argv[3] if len(sys.argv) > 3 else LOG
    try:
        typed_id = int(target_id)
    except (TypeError, ValueError):
        typed_id = target_id
    payload = {
        "schema_version": SCHEMA_VERSION,
        "target_id": typed_id,
        "ts": _clock(),
        "metrics": _metrics(),
        "containers": _containers(),
        "log_chunk": _log_chunk(log_file, offset),
        "clock": _clock(),
        "healthz": _healthz(),
    }
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

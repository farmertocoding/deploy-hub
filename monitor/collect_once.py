#!/usr/bin/env python3
"""On-target collector: one JSON blob per SSH session (REL-C3)."""
import json
import os
import shutil
import subprocess  # nosec B404 — argv-list docker ps, never shell=True
import sys
import time

LOG = os.environ.get("HUB_COLLECT_LOG", "/var/log/caddy/access.log")
CHUNK = 65536  # per-pull byte cap (§C4): raw lines never exceed this
SCHEMA_VERSION = 1

# Degrade mode (§C4): over the cap we aggregate on-host instead of shipping
# raw lines. Every bound below is a recorded fact in the summary, not silence.
SUMMARY_SCAN_CAP = 8 * 1024 * 1024  # bytes one degrade pull will consume
MAX_LINE = 1024 * 1024              # longer lines are swallowed + counted malformed
TOP_IPS = 10
MAX_TRACKED_IPS = 4096              # beyond this, new IPs land in dropped_ips
MAX_TRACKED_HOSTS = 64              # beyond this, new hosts aggregate into "~other"


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


def _log_chunk(path, offset, expected_inode=0):
    try:
        st = os.stat(path)
        inode = st.st_ino
        start = offset
        if expected_inode and inode != expected_inode:
            start = 0  # rotated: a new inode is a new file, resume at byte 0
        if start > st.st_size:
            start = 0  # truncated in place
        with open(path, "rb") as fh:
            fh.seek(start)
            if st.st_size - start <= CHUNK:
                data = fh.read(CHUNK)
                return {
                    "file": path,
                    "inode": inode,
                    "offset": fh.tell(),
                    "bytes": data.decode("utf-8", "replace"),
                }
            summary, new_off = _summarize(fh, start)
        return {
            "file": path,
            "inode": inode,
            "offset": new_off,
            "bytes": "",
            "sampled": True,
            "summary": summary,
        }
    except OSError:
        return {"file": path, "inode": 0, "offset": 0, "bytes": ""}


def _summarize(fh, start):
    """Aggregate the pending region: counts by status, top IPs, per-host totals.

    Bounded on purpose — dict caps and the scan cap keep memory and session
    time finite on a chatty container; whatever is not shipped is counted
    (malformed, dropped_ips, truncated), never silently dropped. The offset
    advances exactly to the last consumed line so nothing is read twice.
    """
    requests = bytes_total = malformed = dropped_ips = 0
    statuses = {}
    ips = {}
    hosts = {}
    pos = start
    while pos - start < SUMMARY_SCAN_CAP:
        line = fh.readline(MAX_LINE)
        if not line:
            break
        if not line.endswith(b"\n"):
            if len(line) < MAX_LINE:
                break  # partial tail still being written: next pull gets it
            # One pathological line longer than MAX_LINE: swallow to its
            # newline in bounded reads, count it malformed, keep going.
            pos += len(line)
            while True:
                extra = fh.readline(MAX_LINE)
                pos += len(extra)
                if not extra or extra.endswith(b"\n"):
                    break
            malformed += 1
            continue
        pos += len(line)
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            malformed += 1
            continue
        if not isinstance(record, dict) or "status" not in record:
            malformed += 1
            continue
        requests += 1
        try:
            bytes_total += int(record.get("size") or 0)
        except (TypeError, ValueError):
            pass
        status = str(record.get("status"))
        statuses[status] = statuses.get(status, 0) + 1
        req = record.get("request") if isinstance(record.get("request"), dict) else {}
        ip = str(req.get("remote_ip") or "")
        if ip:
            if ip in ips or len(ips) < MAX_TRACKED_IPS:
                ips[ip] = ips.get(ip, 0) + 1
            else:
                dropped_ips += 1
        host = str(req.get("host") or "").rsplit(":", 1)[0].lower()
        if host:
            if host not in hosts and len(hosts) >= MAX_TRACKED_HOSTS:
                host = "~other"
            bucket = hosts.setdefault(
                host, {"requests": 0, "bytes": 0, "status_counts": {}})
            bucket["requests"] += 1
            try:
                bucket["bytes"] += int(record.get("size") or 0)
            except (TypeError, ValueError):
                pass
            bucket["status_counts"][status] = bucket["status_counts"].get(status, 0) + 1
    top = sorted(ips.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_IPS]
    summary = {
        "requests": requests,
        "bytes": bytes_total,
        "malformed": malformed,
        "status_counts": statuses,
        "top_ips": [[ip, n] for ip, n in top],
        "dropped_ips": dropped_ips,
        "hosts": hosts,
        "scanned_bytes": pos - start,
        "truncated": (pos - start) >= SUMMARY_SCAN_CAP,
    }
    return summary, pos


def _clock():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _healthz(containers):
    checks = {}
    docker = shutil.which("docker") or "/usr/bin/docker"
    for row in containers:
        name = row.get("name") if isinstance(row, dict) else None
        if not name:
            continue
        checks[name] = _container_health(docker, name)
    lives = [bool(item.get("live")) for item in checks.values()]
    readies = [bool(item.get("ready")) for item in checks.values()]
    return {
        "live": all(lives) if lives else True,
        "ready": all(readies) if readies else True,
        "checks": checks,
    }


def _container_health(docker, name):
    status = _inspect_health(docker, name)
    if status == "healthy":
        return {"live": True, "ready": True}
    if status == "starting":
        return {"live": True, "ready": False}
    if status == "unhealthy":
        return {"live": False, "ready": False}
    return _curl_healthz(docker, name)


def _inspect_health(docker, name):
    try:
        proc = subprocess.run(  # nosec B603 — argv list; docker from which()
            [
                docker, "inspect", "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                name,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    return (proc.stdout or "").strip().lower()


def _curl_healthz(docker, name):
    info = _inspect_container(docker, name)
    ip = _ip_from_inspect(info) or _container_ip(docker, name)
    port = _listen_port_from_inspect(info)
    if not port:
        # No published/EXPOSE/$PORT: cannot curl, but that is not UNHEALTHY.
        return {"live": True, "ready": False, "reason": "listen-port-unknown"}
    if not ip:
        return {"live": False, "ready": False}
    curl = shutil.which("curl") or "/usr/bin/curl"
    raw = _curl_body(curl, _healthz_url(ip, port))
    if not raw.strip():
        return {"live": False, "ready": False}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"live": False, "ready": False}
    if not isinstance(payload, dict):
        return {"live": False, "ready": False}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    return {
        "live": bool(payload.get("live")),
        "ready": bool(payload.get("ready")),
        "checks": checks,
        "reason": _reason_from_checks(checks),
    }


def _inspect_container(docker, name):
    try:
        proc = subprocess.run(  # nosec B603 — argv list; docker from which()
            [docker, "inspect", name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {}
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return {}
    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    if isinstance(rows, list):
        return rows[0] if rows and isinstance(rows[0], dict) else {}
    return rows if isinstance(rows, dict) else {}


def _ip_from_inspect(info):
    nets = (info.get("NetworkSettings") or {}).get("Networks") or {}
    if isinstance(nets, dict):
        for net in nets.values():
            if isinstance(net, dict) and net.get("IPAddress"):
                return str(net["IPAddress"]).strip()
    ip = (info.get("NetworkSettings") or {}).get("IPAddress")
    return str(ip).strip() if ip else ""


def _first_container_port(mapping):
    if not isinstance(mapping, dict):
        return None
    for key in mapping:
        num = str(key).split("/", 1)[0]
        if num.isdigit():
            return int(num)
    return None


def _listen_port_from_inspect(info):
    host = info.get("HostConfig") or {}
    port = _first_container_port(host.get("PortBindings"))
    if port:
        return port
    cfg = info.get("Config") or {}
    port = _first_container_port(cfg.get("ExposedPorts"))
    if port:
        return port
    for item in cfg.get("Env") or []:
        if not isinstance(item, str) or not item.startswith("PORT="):
            continue
        raw = item.split("=", 1)[1].strip()
        if raw.isdigit():
            return int(raw)
    return None


def _healthz_url(ip, port, path="/healthz"):
    port = int(port)
    if port in {80, 443}:
        return f"http://{ip}{path}"
    return f"http://{ip}:{port}{path}"


def _reason_from_checks(checks):
    if not isinstance(checks, dict):
        return ""
    upstream = checks.get("upstream")
    if isinstance(upstream, str):
        key = upstream.strip().lower().replace("_", "-")
        if key == "upstream-down":
            return "upstream-down"
    for key, val in checks.items():
        for token in (key, val):
            text = str(token).strip().lower().replace("_", "-")
            if text in {"data-stale", "feed-stale", "feed-staleness", "staleness"}:
                return text
    return ""


def _container_ip(docker, name):
    try:
        proc = subprocess.run(  # nosec B603 — argv list; docker from which()
            [
                docker, "inspect", "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                name,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    return (proc.stdout or "").strip().split()[0] if proc.stdout else ""


def _curl_body(curl, url):
    try:
        proc = subprocess.run(  # nosec B603 — argv list; curl from which()
            [curl, "-sfS", "--max-time", "2", url],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


def main():
    target_id = sys.argv[1] if len(sys.argv) > 1 else ""
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    # argv[3] "-" or "" = the target's default log; argv[4] = last seen inode.
    log_file = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] not in ("", "-") else LOG
    try:
        expected_inode = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    except (TypeError, ValueError):
        expected_inode = 0
    try:
        typed_id = int(target_id)
    except (TypeError, ValueError):
        typed_id = target_id
    containers = _containers()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "target_id": typed_id,
        "ts": _clock(),
        "metrics": _metrics(),
        "containers": containers,
        "log_chunk": _log_chunk(log_file, offset, expected_inode),
        "clock": _clock(),
        "healthz": _healthz(containers),
    }
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

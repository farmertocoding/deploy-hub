"""Idempotent pipeline steps. Shared with the reconciler.

Reads Manifest.body only — never scanner. Builds run on the target Transport,
never on the Hub docker daemon (§B1). Env files and vault markers stay out of
the shipped context.
"""
import hashlib
import io
import json
import os
import tarfile
import threading
import time
from datetime import timedelta
from pathlib import Path

from core.hubfs import ensure_hub_dir, hub_join, ssh_user_from

HEARTBEAT_INTERVAL_S = 30
VAULT_CONTEXT_MARKERS = frozenset({
    b"VAULT-TEST-PLAINTEXT-MARKER-do-not-log",
    b"PIPELINE-ENV-SNAPSHOT-MARKER-do-not-log",
})


def image_tag(git_sha, manifest_body):
    """Deterministic tag: git sha plus a stable hash of canonical Manifest.body."""
    digest = hashlib.sha256(
        json.dumps(manifest_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return f"{git_sha}-{digest}"


def _desired_image_tag(desired):
    """Honor an explicit pin (env apply) before recomputing from the current body."""
    pinned = desired.get("image_tag")
    if pinned:
        return pinned
    return image_tag(desired["git_sha"], desired.get("manifest_body") or {})


def ensure_build(desired):
    """Probe the tag; on miss, put a vault-free context and docker build on the target."""
    transport = desired["transport"]
    tag = _desired_image_tag(desired)
    if _image_present(transport, tag):
        return {"status": "skipped", "tag": tag}

    archive = _context_tar(desired["source_dir"], _applied_dockerfile(desired))
    user = ssh_user_from(desired)
    remote = desired.get("remote_context") or hub_join("build", tag, ssh_user=user)
    tar_remote = f"{remote}.tar"
    heartbeat = desired.get("heartbeat")
    ensure_hub_dir(transport, user, heartbeat)
    _run(transport, ["mkdir", "-p", remote], heartbeat)
    transport.put(archive, tar_remote)
    _run(transport, ["tar", "-xf", tar_remote, "-C", remote], heartbeat)
    result = _run(transport, ["docker", "build", "-t", tag, remote], heartbeat)
    if not result.ok:
        raise RuntimeError(f"docker build failed: {result.stderr}")
    return {"status": "built", "tag": tag}


def ensure_ship(desired):
    """Probe the tag; docker load after put of an image archive only on miss."""
    transport = desired["transport"]
    body = desired["manifest_body"]
    tag = image_tag(desired["git_sha"], body)
    if _image_present(transport, tag):
        return {"status": "skipped", "tag": tag}

    user = ssh_user_from(desired)
    remote = desired.get("remote_context") or hub_join("build", tag, ssh_user=user)
    archive_path = f"{remote}.image.tar"
    ensure_hub_dir(transport, user, desired.get("heartbeat"))
    _run(transport, ["mkdir", "-p", str(Path(remote).parent)], desired.get("heartbeat"))
    transport.put(desired.get("image_archive", b""), archive_path)
    result = _run(
        transport, ["docker", "load", "-i", archive_path], desired.get("heartbeat"),
    )
    if not result.ok:
        raise RuntimeError(f"docker load failed: {result.stderr}")
    return {"status": "shipped", "tag": tag}


def ensure_volume(desired):
    """Create per-Site docker volumes on miss; never delete."""
    transport = desired["transport"]
    slug = desired["site_slug"]
    body = desired.get("manifest_body") or {}
    heartbeat = desired.get("heartbeat")
    specs = _volume_specs(slug, body)
    for spec in specs:
        name = spec["name"]
        if _volume_present(transport, name):
            continue
        result = _run(transport, ["docker", "volume", "create", name], heartbeat)
        if not result.ok:
            raise RuntimeError(f"docker volume create failed: {result.stderr}")

    site = desired.get("site")
    if site is not None:
        from core.models import SiteVolume

        for spec in specs:
            SiteVolume.objects.update_or_create(
                site=site,
                name=spec["name"],
                defaults={
                    "container_path": spec["container_path"],
                    "backup_policy": spec["backup_policy"],
                },
            )
    return {"status": "ensured", "names": [spec["name"] for spec in specs]}


def ensure_volume_rollback(desired):
    """T1 refuse: rollback must not docker volume rm. Volumes are per-Site."""
    return {
        "status": "refused",
        "reason": "docker volume rm is not permitted",
        "site_slug": desired.get("site_slug"),
    }


def ensure_migrate(desired):
    """Backup then migrate/pre-cutover unless the step already succeeded."""
    from deploys.models import DeploymentStep

    transport = desired["transport"]
    body = desired.get("manifest_body") or {}
    heartbeat = desired.get("heartbeat")
    step = desired.get("step")
    if step is not None and step.status == DeploymentStep.Status.SUCCEEDED:
        return {"status": "skipped"}

    backup_argv = desired.get("backup_argv")
    if backup_argv is None:
        backup_argv = body.get("backup_argv")
    migrate_argv = desired.get("migrate_argv")
    if migrate_argv is None:
        migrate_argv = body.get("migrate_argv") or body.get("pre_cutover")

    if backup_argv:
        result = _run(transport, list(backup_argv), heartbeat)
        if not result.ok:
            raise RuntimeError(f"backup failed: {result.stderr}")
    if migrate_argv:
        result = _run(transport, list(migrate_argv), heartbeat)
        if not result.ok:
            raise RuntimeError(f"migrate failed: {result.stderr}")

    if step is not None:
        step.status = DeploymentStep.Status.SUCCEEDED
        step.save(update_fields=["status"])
    return {"status": "migrated"}


def ensure_start(desired):
    """Start the named green container; recreate stops the old writer first."""
    transport = desired["transport"]
    heartbeat = desired.get("heartbeat")
    name = _container_name(desired)
    running = _container_running(transport, name)
    if running is True:
        return {"status": "skipped", "name": name}

    if running is False:
        result = _run(transport, ["docker", "start", name], heartbeat)
        if not result.ok:
            raise RuntimeError(f"docker start failed: {result.stderr}")
        return {"status": "started", "name": name}

    strategy = _deploy_strategy(desired)
    if strategy == "recreate":
        site = desired.get("site")
        if site is not None:
            _set_maintenance_until(site, desired)
        old = desired.get("old_container")
        if old and old != name and _container_running(transport, old) is True:
            result = _run(transport, ["docker", "stop", old], heartbeat)
            if not result.ok:
                raise RuntimeError(f"docker stop failed: {result.stderr}")

    _put_env_file(desired)
    result = _run(transport, _docker_run_argv(desired, name), heartbeat)
    if not result.ok:
        raise RuntimeError(f"docker run failed: {result.stderr}")
    return {"status": "started", "name": name}


def ensure_health_check(desired):
    """Poll pinned /healthz JSON until ready; frozen checks fail immediately."""
    timeout = _warmup_timeout_s(desired)
    sleep = desired.get("sleep") or time.sleep
    now = desired.get("now") or time.monotonic
    interval = desired.get("poll_interval_s", 1)
    heartbeat = desired.get("heartbeat")
    deadline = now() + timeout
    prev_checks = None
    have_prev = False
    while True:
        if heartbeat is not None:
            heartbeat()
        payload = _healthz_payload(desired)
        if payload.get("ready"):
            return {"status": "ready", "healthz": payload}
        if _checks_are_comparable(payload):
            checks = payload.get("checks")
            if have_prev and checks == prev_checks:
                raise RuntimeError("healthz checks frozen while not ready")
            prev_checks = checks
            have_prev = True
        if now() >= deadline:
            raise RuntimeError("warmup timeout: never ready")
        sleep(interval)


def ensure_dns(desired):
    """Skip mesh_only; public lists then upserts only on (name, rtype) diff.

    The zone handed to the provider is desired["dns_zone"] — the Site.dns_zone
    row (the DnsZone the product adapter is constructed from, D-033). The
    legacy string in desired["zone"] survives only as the fallback for callers
    without a Site (artifact overlays, bare-desired tests).
    """
    if _exposure(desired) == "mesh_only":
        return {"status": "skipped"}
    dns = desired["dns"]
    zone = desired.get("dns_zone") or desired["zone"]
    existing = {
        (rec["name"], rec["rtype"]): rec for rec in dns.list_records(zone)
    }
    wanted = _desired_dns_records(desired)
    upserted = []
    for rec in wanted:
        key = (rec["name"], rec["rtype"])
        current = existing.get(key)
        values = list(rec["values"])
        proxied = rec.get("proxied", True)
        if (
            current is not None
            and list(current.get("values") or []) == values
            and current.get("proxied", False) == proxied
        ):
            continue
        dns.upsert_record(zone, rec["name"], rec["rtype"], values, proxied=proxied)
        upserted.append(key)
    _persist_dns_rows(desired, wanted)
    return {"status": "ensured", "upserted": upserted}


def ensure_route_tls(desired):
    """PUT Caddy route by id site-{slug}; skip when the live route matches."""
    transport = desired["transport"]
    route_id = f"site-{desired['site_slug']}"
    route = _caddy_route(desired, route_id)
    current = _probe_caddy_route(transport, route_id)
    if current == route:
        return {"status": "skipped", "id": route_id}
    remote = hub_join(f"caddy-{route_id}.json", ssh_user=ssh_user_from(desired))
    payload = json.dumps(route, sort_keys=True, separators=(",", ":")).encode()
    ensure_hub_dir(transport, ssh_user_from(desired), desired.get("heartbeat"))
    transport.put(payload, remote)
    result = _run(
        transport,
        [
            "curl", "-sf", "-X", "PUT",
            f"http://127.0.0.1:2019/config/apps/http/servers/{route_id}",
            "-H", "Content-Type: application/json",
            "--data-binary", f"@{remote}",
        ],
        desired.get("heartbeat"),
    )
    if not result.ok:
        raise RuntimeError(f"caddy put failed: {result.stderr}")
    return {"status": "applied", "id": route_id}


def ensure_smoke(desired):
    """Probe the Caddy listen /healthz ready path; ws sites also receive one frame."""
    payload = _caddy_smoke_payload(desired)
    if not payload.get("ready"):
        raise RuntimeError("smoke failed: not ready")
    if _declares_ws(desired.get("manifest_body") or {}):
        if not _ws_frame(desired):
            raise RuntimeError("smoke failed: no ws frame")
    return {"status": "ready", "healthz": payload}


def ensure_cutover(desired):
    """Refuse unless ready; stop the old container and keep it for rollback."""
    if not _cutover_ready(desired):
        raise RuntimeError("cutover refused: not ready")
    transport = desired["transport"]
    old = desired.get("old_container")
    if old and _container_running(transport, old) is not False:
        result = _run(transport, ["docker", "stop", old], desired.get("heartbeat"))
        if not result.ok:
            raise RuntimeError(f"docker stop failed: {result.stderr}")
    step = desired.get("step")
    if step is not None:
        from django.utils import timezone

        artifacts = dict(step.artifacts or {})
        deadline = timezone.now() + timedelta(seconds=_cutover_grace_s(desired))
        artifacts["grace_deadline"] = deadline.isoformat()
        step.artifacts = artifacts
        step.save(update_fields=["artifacts"])
    return {"status": "cutover"}


def _exposure(desired):
    site = desired.get("site")
    body = desired.get("manifest_body") or {}
    site_exp = getattr(site, "exposure", None) if site is not None else None
    body_exp = body.get("exposure")
    if site_exp == "mesh_only" or body_exp == "mesh_only":
        return "mesh_only"
    return site_exp or body_exp or "public"


def _desired_dns_records(desired):
    overlay = _overlay_json(desired.get("dns_set"))
    if isinstance(overlay, list) and overlay:
        return overlay
    domain = desired.get("domain")
    site = desired.get("site")
    if not domain and site is not None:
        domain = getattr(site, "domain", None)
    values = desired.get("dns_values") or ["127.0.0.1"]
    return [{
        "name": domain,
        "rtype": desired.get("dns_rtype") or "A",
        "values": list(values),
        "proxied": desired.get("dns_proxied", True),
    }]


def _persist_dns_rows(desired, records):
    site = desired.get("site")
    if site is None or not getattr(site, "pk", None):
        return
    from core.models import DnsRecord

    for rec in records:
        value = rec["values"][0] if rec["values"] else ""
        DnsRecord.objects.update_or_create(
            site=site,
            name=rec["name"],
            rtype=rec["rtype"],
            defaults={"value": value},
        )


def _caddy_route(desired, route_id):
    overlay = _overlay_json(desired.get("caddy_route"))
    if isinstance(overlay, dict) and overlay:
        return overlay
    body = desired.get("manifest_body") or {}
    override = desired.get("caddy_listen") or body.get("caddy_listen")
    if override:
        listen = [override]
    elif _exposure(desired) == "mesh_only":
        host = body.get("mesh_bind") or "127.0.0.1"
        listen = [f"{host}:443"]
    else:
        listen = [":443"]
    domain = desired.get("domain") or f"{desired['site_slug']}.local"
    return {
        "@id": route_id,
        "listen": listen,
        "automatic_https": {"disable": True},
        "routes": [{
            "match": [{"host": [domain]}],
            "handle": [{
                "handler": "reverse_proxy",
                "upstreams": [{"dial": _caddy_upstream(desired)}],
            }],
        }],
    }


def _caddy_upstream(desired):
    if desired.get("upstream"):
        return desired["upstream"]
    return f"127.0.0.1:{desired.get('internal_port', 20000)}"


def _caddy_listen_hostport(desired):
    """Host:port smoke curls. Public :443 becomes 127.0.0.1:443 (no TLS this phase)."""
    route_id = f"site-{desired['site_slug']}"
    listen = (_caddy_route(desired, route_id).get("listen") or [":443"])[0]
    if listen.startswith(":"):
        return f"127.0.0.1{listen}"
    return listen


def _caddy_smoke_payload(desired):
    transport = desired["transport"]
    url = f"http://{_caddy_listen_hostport(desired)}{_readiness_path(desired)}"
    domain = desired.get("domain") or f"{desired['site_slug']}.local"
    result = transport.probe([
        "curl", "-sf", "-H", f"Host: {domain}", url,
    ])
    if not result.ok or not (result.stdout or "").strip():
        return {"live": False, "ready": False}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"live": False, "ready": False}


def _probe_caddy_route(transport, route_id):
    urls = [
        f"http://127.0.0.1:2019/id/{route_id}",
        f"http://127.0.0.1:2019/config/apps/http/servers/{route_id}",
    ]
    for url in urls:
        result = transport.probe(["curl", "-sf", url])
        if not result.ok or not (result.stdout or "").strip():
            continue
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
    return None


def _declares_ws(body):
    if body.get("ws") or body.get("websocket"):
        return True
    nested = body.get("healthz") or {}
    return bool(nested.get("ws") or nested.get("websocket"))


# Dependency-free ws probe run with the target's python3 (same contract as the
# curl healthz probe above). The old fallback ran `websocat -n1 ws://127.0.0.1/ws`
# — a binary no target ships, against port 80, without the Host header Caddy
# routes on — so the first live ws smoke (T3, panel fix wave) failed for every
# ws site. Handshake + first frame; prints the payload; exit 0 only on a real
# data frame.
_WS_PROBE_PY = b"""\
import base64
import os
import socket
import sys


def main(host, port, path, server_name):
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {path} HTTP/1.1\\r\\n"
        f"Host: {server_name}\\r\\n"
        f"Upgrade: websocket\\r\\n"
        f"Connection: Upgrade\\r\\n"
        f"Sec-WebSocket-Key: {key}\\r\\n"
        f"Sec-WebSocket-Version: 13\\r\\n"
        f"\\r\\n"
    )
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        sock.sendall(req.encode())
        header = b""
        while b"\\r\\n\\r\\n" not in header:
            chunk = sock.recv(4096)
            if not chunk:
                break
            header += chunk
        if b"\\r\\n\\r\\n" not in header:
            sys.stderr.write("no websocket handshake\\n")
            return 2
        head, rest = header.split(b"\\r\\n\\r\\n", 1)
        if b"101" not in head.split(b"\\r\\n", 1)[0]:
            sys.stderr.write(head.decode("latin1", "replace") + "\\n")
            return 2
        data = rest
        while len(data) < 2:
            more = sock.recv(4096)
            if not more:
                break
            data += more
        if len(data) < 2:
            return 3
        opcode = data[0] & 0x0F
        ln = data[1] & 0x7F
        idx = 2
        if ln == 126:
            while len(data) < 4:
                data += sock.recv(4096)
            ln = int.from_bytes(data[2:4], "big")
            idx = 4
        elif ln == 127:
            while len(data) < 10:
                data += sock.recv(4096)
            ln = int.from_bytes(data[2:10], "big")
            idx = 10
        while len(data) < idx + ln:
            more = sock.recv(4096)
            if not more:
                break
            data += more
        payload = data[idx : idx + ln]
        sys.stdout.write(payload.decode("utf-8", "replace"))
        return 0 if opcode in (1, 2) and payload else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4], sys.argv[4] if len(sys.argv) > 4 else sys.argv[1]))
"""


def _ws_path(body):
    if body.get("ws_path"):
        return body["ws_path"]
    nested = body.get("healthz") or {}
    return nested.get("ws_path") or "/ws"


def _ws_frame(desired):
    fetch = desired.get("ws_fetch")
    if fetch is not None:
        return fetch()
    transport = desired["transport"]
    body = desired.get("manifest_body") or {}
    host, _, port = _caddy_listen_hostport(desired).rpartition(":")
    domain = desired.get("domain") or f"{desired['site_slug']}.local"
    user = ssh_user_from(desired)
    ensure_hub_dir(transport, user, desired.get("heartbeat"))
    remote = hub_join("ws-probe.py", ssh_user=user)
    transport.put(_WS_PROBE_PY, remote, mode=0o644)
    result = transport.probe(["python3", remote, host, port, _ws_path(body), domain])
    if not result.ok:
        return None
    return result.stdout


def _cutover_ready(desired):
    if "ready" in desired:
        return bool(desired["ready"])
    fetch = desired.get("healthz_fetch")
    if fetch is not None:
        return bool(fetch().get("ready"))
    return bool(_healthz_payload(desired).get("ready"))


def _cutover_grace_s(desired):
    if desired.get("grace_s") is not None:
        return int(desired["grace_s"])
    body = desired.get("manifest_body") or {}
    if body.get("cutover_grace_s") is not None:
        return int(body["cutover_grace_s"])
    return 30


def _container_name(desired):
    return f"site-{desired['site_slug']}-{desired['deployment_id']}"


def _deploy_strategy(desired):
    body = desired.get("manifest_body") or {}
    if body.get("local_state") or body.get("exclusive_upstream"):
        return "recreate"
    if body.get("deploy_strategy"):
        return body["deploy_strategy"]
    site = desired.get("site")
    if site is not None:
        strategy = getattr(site, "deploy_strategy", None)
        if strategy:
            return strategy
    return "blue_green"


def _container_running(transport, name):
    result = transport.probe([
        "docker", "inspect", "--format", "{{.State.Running}}", name,
    ])
    if not result.ok:
        return None
    return result.stdout.strip().lower() in {"true", "running", "1"}


def _positive_port(raw):
    if raw is None or isinstance(raw, bool) or raw == "":
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    text = str(raw).strip()
    if text.isdigit():
        value = int(text)
        return value if value > 0 else None
    return None


def _listen_port(desired):
    """In-container listen port for -e PORT=. Never a secret; never from env_mapping."""
    port = _positive_port(desired.get("internal_port"))
    if port is not None:
        return port
    inst = desired.get("instance")
    if inst is not None:
        port = _positive_port(getattr(inst, "internal_port", None))
        if port is not None:
            return port
    body = desired.get("manifest_body") or {}
    for key in ("port", "PORT"):
        port = _positive_port(body.get(key))
        if port is not None:
            return port
    return 8080


def _docker_run_argv(desired, name):
    argv = ["docker", "run", "-d", "--name", name]
    if desired.get("env_file"):
        argv.extend(["--env-file", desired["env_file"]])
    extra = desired.get("docker_run_extra")
    if extra is None:
        extra = (desired.get("manifest_body") or {}).get("docker_run_extra")
    if extra:
        argv.extend(list(extra))
    body = desired.get("manifest_body") or {}
    for spec in _volume_specs(desired["site_slug"], body):
        argv.extend(["-v", f"{spec['name']}:{spec['container_path']}"])
    argv.extend(["-e", f"PORT={_listen_port(desired)}"])
    argv.extend(["--restart", "unless-stopped"])
    argv.append(desired["image_tag"])
    return argv


def _put_env_file(desired):
    """Write vaulted env to a 0600 file on the target; never on docker argv."""
    mapping = desired.get("env_mapping") or {}
    if not mapping:
        return
    transport = desired["transport"]
    user = ssh_user_from(desired)
    heartbeat = desired.get("heartbeat")
    ensure_hub_dir(transport, user, heartbeat)
    remote = hub_join(
        f"site-{desired['site_slug']}-{desired['deployment_id']}.env",
        ssh_user=user,
    )
    body = "".join(f"{key}={mapping[key]}\n" for key in sorted(mapping))
    transport.put(body.encode(), remote, mode=0o600)
    desired["env_file"] = remote


def _set_maintenance_until(site, desired):
    from django.utils import timezone

    site.maintenance_until = timezone.now() + timedelta(seconds=_warmup_timeout_s(desired))
    if hasattr(site, "save"):
        site.save(update_fields=["maintenance_until"])


def _warmup_timeout_s(desired):
    body = desired.get("manifest_body") or {}
    if body.get("warmup_timeout_s") is not None:
        return int(body["warmup_timeout_s"])
    nested = (body.get("healthz") or {}).get("warmup_timeout_s")
    if nested is not None:
        return int(nested)
    site = desired.get("site")
    if site is not None and getattr(site, "warmup_timeout_s", None) is not None:
        return int(site.warmup_timeout_s)
    return 60


def _readiness_path(desired):
    body = desired.get("manifest_body") or {}
    if body.get("readiness_path"):
        return body["readiness_path"]
    nested = (body.get("healthz") or {}).get("readiness_path")
    if nested:
        return nested
    site = desired.get("site")
    if site is not None and getattr(site, "readiness_path", None):
        return site.readiness_path
    return "/healthz.ready"


def _healthz_payload(desired):
    fetch = desired.get("healthz_fetch")
    if fetch is not None:
        return fetch()
    transport = desired["transport"]
    name = _container_name(desired)
    path = _readiness_path(desired)
    ip_r = transport.probe([
        "docker", "inspect", "--format",
        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        name,
    ])
    ip = (ip_r.stdout or "").strip().split()[0] if (ip_r.stdout or "").strip() else ""
    listen = _listen_port(desired)
    host = ip or "127.0.0.1"
    url = f"http://{host}:{listen}{path}"
    result = transport.probe(["curl", "-sf", url])
    if not result.ok or not (result.stdout or "").strip():
        return {"live": False, "ready": False}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"live": False, "ready": False}


def _checks_are_comparable(payload):
    """Frozen-check only after a live reply or a real checks object, not a curl miss."""
    return bool(payload.get("live")) or "checks" in payload


def _image_present(transport, tag):
    return transport.probe(["docker", "image", "inspect", tag]).ok


def _volume_present(transport, name):
    return transport.probe(["docker", "volume", "inspect", name]).ok


def _volume_specs(slug, body):
    """Always site-{slug}-data, then further Manifest volumes; names deduped."""
    default_name = f"site-{slug}-data"
    specs = []
    seen = set()

    def add(name, container_path, backup_policy):
        if name in seen:
            return
        seen.add(name)
        specs.append({
            "name": name,
            "container_path": container_path or "/data",
            "backup_policy": backup_policy or "none",
        })

    listed = body.get("volumes") or []
    match = next(
        (item for item in listed if isinstance(item, dict) and item.get("name") == default_name),
        {},
    )
    add(
        default_name,
        match.get("container_path"),
        match.get("backup_policy"),
    )
    for item in listed:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        add(item.get("name"), item.get("container_path"), item.get("backup_policy"))
    return specs


def _run(transport, argv, heartbeat=None, timeout=3600):
    """transport.run, with optional heartbeat immediately before and on a 30s cadence."""
    if heartbeat is None:
        return transport.run(argv, timeout=timeout)
    heartbeat()
    done = threading.Event()

    def pulse():
        from django.db import close_old_connections

        while not done.wait(HEARTBEAT_INTERVAL_S):
            close_old_connections()
            heartbeat()

    threading.Thread(target=pulse, daemon=True).start()
    try:
        return transport.run(argv, timeout=timeout)
    finally:
        done.set()


def _overlay_json(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _applied_dockerfile(desired):
    overlay = desired.get("dockerfile")
    if overlay:
        return overlay
    return _dockerfile_from_body(desired.get("manifest_body") or {})


def _dockerfile_from_body(manifest_body):
    template = manifest_body.get("dockerfile_template")
    if template:
        return template
    runtime = (manifest_body.get("runtime") or "").lower()
    if not runtime:
        kind = ((manifest_body.get("components") or {}).get("service") or {}).get("kind")
        runtime = (kind or "").lower()
    if runtime in {"python", "django"}:
        return (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --require-hashes -r requirements.txt\n"
            "COPY . .\n"
            'CMD ["python", "-m", "app"]\n'
        )
    return (
        "FROM node:22-alpine\n"
        "WORKDIR /app\n"
        "COPY package.json package-lock.json* ./\n"
        "RUN npm ci\n"
        "COPY . .\n"
        'CMD ["node", "app.js"]\n'
    )


def _context_tar(source_dir, dockerfile_text):
    source = Path(source_dir)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for dirpath, _dirnames, filenames in os.walk(source, followlinks=False):
            for filename in filenames:
                if filename == "Dockerfile" or _is_env_filename(filename):
                    continue
                path = Path(dirpath) / filename
                if path.is_symlink():
                    continue
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                if data in VAULT_CONTEXT_MARKERS:
                    continue
                _add_bytes(tf, path.relative_to(source).as_posix(), data)
        _add_bytes(tf, "Dockerfile", dockerfile_text.encode())
    return buf.getvalue()


def _is_env_filename(name):
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def _add_bytes(tf, name, data):
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))

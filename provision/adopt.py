"""Compose-aware adoption plan (design note §1.1 a/b/e). Reader only.

`read_compose` is `yaml.safe_load` on the Project tree (M1). Classification
compresses into one V5 Site. `adoption_plan` files Findings, proposes one
manifest, registers SiteVolume rows, and writes `Site.edge_owner` once.
Nothing is started, flipped, or materialized.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core.findings import finding, resolve
from core.models import Finding, Site, SiteVolume

COMPOSE_FILENAMES = (
    "docker-compose.prod.yml",
    "compose.prod.yaml",
    "docker-compose.yml",
    "compose.yaml",
)

EDGE_IMAGES = frozenset({"caddy", "nginx", "traefik"})
DB_IMAGES = frozenset({"postgres", "mysql", "mariadb", "postgis", "percona"})
CACHE_IMAGES = frozenset({"redis", "memcached", "keydb", "valkey"})
EDGE_PORTS = frozenset({80, 443})
ROLE_KEYS = (
    "web",
    "worker",
    "beat-scheduler",
    "one-shot migrate",
    "db",
    "cache",
    "site-owned edge",
)

AMBIGUOUS_FP = "adopt-edge-ambiguous:{site_id}"
UNCOMPRESSIBLE_FP = "adopt-uncompressible:{site_id}"
PLAN_FP = "adopt-plan:{site_id}"
DB_URL_MISSING_FP = "adopt-db-url-missing:{site_id}"
CACHE_URL_MISSING_FP = "adopt-cache-url-missing:{site_id}"


@dataclass
class AdoptionPlan:
    refused: bool
    blocked: bool
    classified: dict
    manifest: dict | None
    volumes: list = field(default_factory=list)
    findings: list = field(default_factory=list)


def read_compose(path):
    """Load the first compose filename that exists under `path`. Execute nothing."""
    root = Path(path)
    for name in COMPOSE_FILENAMES:
        candidate = root / name
        if not candidate.is_file():
            continue
        loaded = yaml.safe_load(candidate.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    raise FileNotFoundError(
        f"no compose file in {root} "
        f"(tried {', '.join(COMPOSE_FILENAMES)})"
    )


def classify_services(compose):
    """Map compose services onto the V5 roles. Extra public apps stay unassigned."""
    services = _services(compose)
    roles = {key: None for key in ROLE_KEYS}
    assigned = set()

    edge_name, _ambiguous = _edge_state(services)
    if edge_name is not None:
        roles["site-owned edge"] = edge_name
        assigned.add(edge_name)
    for name, svc in services.items():
        if name not in assigned and _is_edge_publisher(svc):
            assigned.add(name)

    for name, svc in services.items():
        if name in assigned:
            continue
        base = _image_basename(svc.get("image"))
        lowered = name.lower()
        if roles["db"] is None and (
            base in DB_IMAGES or lowered in {"db", "postgres", "mysql", "mariadb"}
        ):
            roles["db"] = name
            assigned.add(name)
            continue
        if roles["cache"] is None and (
            base in CACHE_IMAGES or lowered in {"redis", "cache", "memcached", "valkey"}
        ):
            roles["cache"] = name
            assigned.add(name)

    for name, svc in services.items():
        if name in assigned:
            continue
        lowered = name.lower()
        cmd = _command_text(svc).lower()
        if roles["one-shot migrate"] is None and ("migrate" in lowered or "migrate" in cmd):
            roles["one-shot migrate"] = name
            assigned.add(name)
            continue
        if roles["beat-scheduler"] is None and (
            "beat" in lowered
            or "scheduler" in lowered
            or "beat" in cmd
            or "scheduler" in cmd
        ):
            roles["beat-scheduler"] = name
            assigned.add(name)
            continue
        if roles["worker"] is None and ("worker" in lowered or "worker" in cmd):
            roles["worker"] = name
            assigned.add(name)

    remaining = [name for name in services if name not in assigned]
    public = [name for name in remaining if _published_ports(services[name])]
    if len(remaining) == 1:
        roles["web"] = remaining[0]
    elif len(public) == 1:
        roles["web"] = public[0]
    return roles


def adoption_plan(project):
    """Read the Project tree, classify, file Findings, write volumes and edge_owner."""
    site = project.sites.order_by("pk").first()
    if site is None:
        raise ValueError("adoption_plan requires a Site on the Project")
    tree = _project_tree(project)
    compose = read_compose(tree)
    roles = classify_services(compose)
    services = _services(compose)
    filed = []
    public = _unassigned_public(services, roles)
    refused = len(public) > 1
    _edge_name, ambiguous = _edge_state(services)
    blocked = False

    if refused:
        filed.append(_file_uncompressible(site, public))
        volumes = []
        return AdoptionPlan(
            refused=True,
            blocked=False,
            classified=roles,
            manifest=None,
            volumes=volumes,
            findings=filed,
        )

    if ambiguous:
        blocked = _block_ambiguous_edge(site, filed)

    if not blocked and not ambiguous:
        desired = (
            Site.EdgeOwner.SITE_CADDY
            if roles["site-owned edge"]
            else Site.EdgeOwner.HOST_CADDY
        )
        if site.edge_owner != desired:
            site.edge_owner = desired
            site.save(update_fields=["edge_owner"])

    volumes = _register_volumes(site, compose)
    _file_pointer_gaps(site, roles, services, tree, filed)
    manifest = _manifest_proposal(roles, services)
    filed.append(_file_plan(site, roles, blocked))
    return AdoptionPlan(
        refused=False,
        blocked=blocked,
        classified=roles,
        manifest=manifest,
        volumes=volumes,
        findings=filed,
    )


def _project_tree(project):
    if project.local_path:
        return Path(project.local_path)
    raise ValueError("adoption_plan reads the Project tree (local_path or clone)")


def _services(compose):
    raw = (compose or {}).get("services") or {}
    if not isinstance(raw, dict):
        return {}
    return {name: svc if isinstance(svc, dict) else {} for name, svc in raw.items()}


def _image_basename(image):
    if not image:
        return ""
    name = str(image).split("@", 1)[0].split(":", 1)[0]
    return name.rsplit("/", 1)[-1].lower()


def _command_text(svc):
    cmd = svc.get("command") or svc.get("entrypoint") or ""
    if isinstance(cmd, list):
        return " ".join(str(part) for part in cmd)
    return str(cmd)


def _published_ports(svc):
    found = set()
    for item in svc.get("ports") or []:
        try:
            if isinstance(item, dict):
                published = item.get("published")
                if published in (None, ""):
                    continue
                found.add(int(str(published).split("/", 1)[0]))
                continue
            if isinstance(item, int):
                found.add(item)
                continue
            text = str(item).split("/", 1)[0]
            parts = text.split(":")
            if len(parts) == 1:
                found.add(int(parts[0]))
            elif len(parts) == 2:
                found.add(int(parts[0]))
            else:
                found.add(int(parts[-2]))
        except (TypeError, ValueError):
            continue
    return found


def _edge_state(services):
    """I-edge: mystery 80/443 publisher, or two different edge images."""
    publishers = []
    for name, svc in services.items():
        ports = _published_ports(svc)
        if not ports & EDGE_PORTS:
            continue
        publishers.append((name, _image_basename(svc.get("image"))))
    if not publishers:
        return None, False
    non_edge = [item for item in publishers if item[1] not in EDGE_IMAGES]
    edge_images = {item[1] for item in publishers if item[1] in EDGE_IMAGES}
    if non_edge or len(edge_images) > 1:
        return None, True
    if len(edge_images) == 1:
        named = [item[0] for item in publishers if item[1] in EDGE_IMAGES]
        if len(named) == 1:
            return named[0], False
    return None, False


def _is_edge_publisher(svc):
    return bool(_published_ports(svc) & EDGE_PORTS) and (
        _image_basename(svc.get("image")) in EDGE_IMAGES
    )


def _unassigned_public(services, roles):
    taken = {roles[key] for key in ROLE_KEYS if roles[key] and key != "web"}
    public = []
    for name, svc in services.items():
        if name in taken or _is_edge_publisher(svc):
            continue
        if _published_ports(svc):
            public.append(name)
    return public


def _env_map(svc, root):
    env = {}
    files = svc.get("env_file") or []
    if isinstance(files, str):
        files = [files]
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            env[key] = value
    raw = svc.get("environment") or {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            env[str(key)] = "" if value is None else str(value)
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            if "=" in item:
                key, value = item.split("=", 1)
                env[key] = value
            else:
                env[item] = ""
    return env


def _has_env_key(roles, services, root, role, keys):
    name = roles.get(role)
    if not name:
        return False
    env = _env_map(services.get(name) or {}, root)
    if any(key in env for key in keys):
        return True
    web = roles.get("web")
    if web and web != name:
        env = _env_map(services.get(web) or {}, root)
        if any(key in env for key in keys):
            return True
    return False


def _named_volume_targets(compose):
    declared = (compose or {}).get("volumes") or {}
    if isinstance(declared, dict):
        names = set(declared)
    elif isinstance(declared, list):
        names = set()
        for item in declared:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict) and item.get("name"):
                names.add(item["name"])
    else:
        names = set()
    targets = {}
    for svc in _services(compose).values():
        for mount in svc.get("volumes") or []:
            source = dest = None
            if isinstance(mount, str):
                parts = mount.split(":")
                if len(parts) >= 2 and parts[0] in names:
                    source, dest = parts[0], parts[1]
            elif isinstance(mount, dict) and mount.get("source") in names:
                source = mount.get("source")
                dest = mount.get("target")
            if source and dest:
                targets.setdefault(source, dest)
    for name in names:
        targets.setdefault(name, "/")
    return targets


def _register_volumes(site, compose):
    rows = []
    for name, container_path in _named_volume_targets(compose).items():
        row, _created = SiteVolume.objects.update_or_create(
            site=site,
            name=name,
            defaults={"container_path": container_path or "/"},
        )
        rows.append(row)
    return rows


def _manifest_proposal(roles, services):
    web = roles["web"]
    svc = services.get(web) or {} if web else {}
    jobs = []
    if roles["worker"]:
        jobs.append({"name": roles["worker"], "kind": "worker"})
    if roles["beat-scheduler"]:
        jobs.append({"name": roles["beat-scheduler"], "kind": "beat-scheduler"})
    if roles["one-shot migrate"]:
        jobs.append({"name": roles["one-shot migrate"], "kind": "one-shot migrate"})
    body = {
        "components": {
            "service": (
                {"name": web, "image": svc.get("image") or ""} if web else None
            ),
            "static_route": None,
            "jobs": jobs,
        },
        "jobs_image": None,
    }
    if roles["cache"]:
        body["cache"] = {"service": roles["cache"], "pointer": True}
    if roles["db"]:
        body["db"] = {"service": roles["db"], "pointer": True}
    return body


def _file(site, fingerprint, *, severity, title, body, fix_action):
    return finding(
        "adopt",
        fingerprint,
        severity=severity,
        entity=f"site:{site.pk}",
        title=title,
        body=body,
        fix_action=fix_action,
    )


def _file_uncompressible(site, public):
    names = " and ".join(sorted(public))
    return _file(
        site,
        UNCOMPRESSIBLE_FP.format(site_id=site.pk),
        severity=Finding.Severity.P2,
        title="Compose stack cannot compress to one Site",
        body=(
            f"{names} both publish public ports; V5 is one service container "
            "per Site, so this stack must be split."
        ),
        fix_action="Split into two Projects, one public service each.",
    )


def _block_ambiguous_edge(site, filed):
    fingerprint = AMBIGUOUS_FP.format(site_id=site.pk)
    existing = Finding.objects.filter(fingerprint=fingerprint).first()
    if existing is not None and existing.state == Finding.State.RESOLVED:
        return False
    filed.append(
        _file(
            site,
            fingerprint,
            severity=Finding.Severity.P2,
            title="Caddy ownership is ambiguous",
            body=(
                "A publisher on 80/443 is not caddy/nginx/traefik, or two "
                "different edge images share those ports. The plan will not "
                "write edge_owner."
            ),
            fix_action=(
                f"PATCH /api/v1/sites/{site.pk}/ with body {{edge_owner}} only."
            ),
        )
    )
    return True


def _file_pointer_gaps(site, roles, services, tree, filed):
    if roles["db"] and not _has_env_key(
        roles, services, tree, "db", ("DATABASE_URL",)
    ):
        filed.append(
            _file(
                site,
                DB_URL_MISSING_FP.format(site_id=site.pk),
                severity=Finding.Severity.P2,
                title="Adopted database URL is missing from compose",
                body=(
                    "The classified db service has no connection string in "
                    "its compose environment or env_file. Hub will not start "
                    "a second database."
                ),
                fix_action="Put the existing connection string on the db service env.",
            )
        )
    if roles["cache"] and not _has_env_key(
        roles, services, tree, "cache", ("REDIS_URL", "CACHE_URL")
    ):
        filed.append(
            _file(
                site,
                CACHE_URL_MISSING_FP.format(site_id=site.pk),
                severity=Finding.Severity.P2,
                title="Adopted cache URL is missing from compose",
                body=(
                    "The classified cache service has no connection string in "
                    "its compose environment or env_file. Cache is a pointer, "
                    "not a Hub-provisioned cache."
                ),
                fix_action="Put the existing cache connection string on the cache service env.",
            )
        )


def apply_edge_owner(site, edge_owner, *, actor=None):
    """I-edge PATCH: write edge_owner only and unblock an ambiguous Finding."""
    site.edge_owner = edge_owner
    site.save(update_fields=["edge_owner"])
    fingerprint = AMBIGUOUS_FP.format(site_id=site.pk)
    row = Finding.objects.filter(fingerprint=fingerprint).first()
    if row is not None and row.state in (Finding.State.OPEN, Finding.State.ACKED):
        resolve(row, actor=actor, source="api")
    return site


def _file_plan(site, roles, blocked):
    parts = [f"web={roles['web']}"]
    if roles["worker"]:
        parts.append("worker")
    if roles["beat-scheduler"]:
        parts.append("beat-scheduler")
    if roles["one-shot migrate"]:
        parts.append("one-shot migrate")
    if roles["db"]:
        parts.append("db-pointer")
    if roles["cache"]:
        parts.append("cache-pointer")
    if roles["site-owned edge"]:
        parts.append("site-owned edge")
    status = "blocked on edge_owner" if blocked else "ready"
    return _file(
        site,
        PLAN_FP.format(site_id=site.pk),
        severity=Finding.Severity.P3,
        title="Adoption plan proposes one V5 Site",
        body=(
            f"Compose classified as {', '.join(parts)} ({status}). "
            "db/cache stay pointers; Hub will not provision a second copy."
        ),
        fix_action="Review volumes and edge_owner, then start the adopt flow.",
    )

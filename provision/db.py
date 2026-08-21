"""Ensure a per-site Postgres container + role; vault DATABASE_URL (not build context)."""
import re
import secrets

from vault import service
from vault.models import Secret

POSTGRES_IMAGE = "postgres:16"


def ensure_site_db(desired):
    """Probe site-{slug}-postgres; on miss docker run + CREATE ROLE, then vault the URL."""
    transport = desired["transport"]
    site = desired["site"]
    slug = desired.get("site_slug") or site.name
    heartbeat = desired.get("heartbeat")
    container = f"site-{slug}-postgres"
    if _container_present(transport, container):
        return {"status": "skipped", "container": container}

    ident = _ident(slug)
    password = secrets.token_hex(16)
    super_password = secrets.token_hex(16)
    started = _run(
        transport,
        [
            "docker", "run", "-d", "--name", container,
            "-e", f"POSTGRES_PASSWORD={super_password}",
            "-e", f"POSTGRES_DB={ident}",
            POSTGRES_IMAGE,
        ],
        heartbeat,
    )
    if not started.ok:
        raise RuntimeError(f"docker run postgres failed: {started.stderr}")
    role_sql = (
        f"CREATE ROLE {ident} LOGIN PASSWORD '{password}'; "
        f"GRANT ALL PRIVILEGES ON DATABASE {ident} TO {ident};"
    )
    role = _run(
        transport,
        ["docker", "exec", container, "psql", "-U", "postgres", "-d", ident, "-c", role_sql],
        heartbeat,
    )
    if not role.ok:
        raise RuntimeError(f"CREATE ROLE failed: {role.stderr}")
    url = f"postgres://{ident}:{password}@{container}:5432/{ident}".encode()
    Secret.objects.filter(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
    ).delete()
    service.put(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
        plaintext=url,
    )
    return {"status": "created", "container": container}


def _container_present(transport, name):
    return transport.probe(["docker", "inspect", name]).ok


def _ident(slug):
    ident = re.sub(r"[^a-zA-Z0-9_]", "_", slug).lower() or "site"
    if ident[0].isdigit():
        ident = f"db_{ident}"
    return ident


def _run(transport, argv, heartbeat=None, timeout=3600):
    if heartbeat is not None:
        heartbeat()
    return transport.run(argv, timeout=timeout)

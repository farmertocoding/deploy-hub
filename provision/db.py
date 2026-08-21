"""Ensure a per-site Postgres container + role; vault DATABASE_URL (not build context)."""
import re
import secrets
import time

from core.hubfs import ensure_hub_dir, hub_join, ssh_user_from
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
    user = ssh_user_from(desired)
    ensure_hub_dir(transport, user, heartbeat)
    env_path = hub_join(f"{container}.env", ssh_user=user)
    sql_path = hub_join(f"{container}.sql", ssh_user=user)
    transport.put(
        f"POSTGRES_PASSWORD={super_password}\nPOSTGRES_DB={ident}\n".encode(),
        env_path,
        mode=0o600,
    )
    transport.put(
        (
            f"CREATE ROLE {ident} LOGIN PASSWORD '{password}'; "
            f"GRANT ALL PRIVILEGES ON DATABASE {ident} TO {ident};\n"
        ).encode(),
        sql_path,
        mode=0o600,
    )
    started = _run(
        transport,
        [
            "docker", "run", "-d", "--name", container,
            "--env-file", env_path,
            POSTGRES_IMAGE,
        ],
        heartbeat,
    )
    if not started.ok:
        raise RuntimeError("docker run postgres failed")
    _wait_pg(transport, container, heartbeat)
    container_sql = "/var/lib/postgresql/hub-role.sql"
    copied = _run(
        transport,
        ["docker", "cp", sql_path, f"{container}:{container_sql}"],
        heartbeat,
    )
    if not copied.ok:
        raise RuntimeError("failed to copy role SQL into postgres")
    role = _run(
        transport,
        [
            "docker", "exec", container, "psql", "-U", "postgres", "-d", ident,
            "-f", container_sql,
        ],
        heartbeat,
    )
    if not role.ok:
        raise RuntimeError("postgres role bootstrap failed")
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


def _wait_pg(transport, container, heartbeat=None, *, attempts=30, sleep=time.sleep):
    for _ in range(attempts):
        if heartbeat is not None:
            heartbeat()
        result = transport.probe([
            "docker", "exec", container, "pg_isready", "-U", "postgres",
        ])
        if result.ok:
            return
        sleep(1)
    raise RuntimeError("postgres did not become ready")


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

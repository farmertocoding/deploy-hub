"""ensure_site_db: Postgres container + role, DATABASE_URL vaulted not built."""
from pathlib import Path

import pytest

from core.transport import CommandResult, FakeTransport

pytestmark = pytest.mark.django_db


class PostgresTransport(FakeTransport):
    """Inspect keyed on full argv. The postgres container exists only after docker run."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.containers = set()

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv[:2] == ["docker", "inspect"] and len(argv) >= 3:
            name = argv[-1]
            if name in self.containers:
                return CommandResult(argv, exit_code=0, stdout=name)
            return CommandResult(argv, exit_code=1, stderr="Error: No such container")
        canned = self.responses.get(argv[0])
        if canned is None:
            return CommandResult(argv)
        return CommandResult(argv, **canned)

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv[:2] == ["docker", "run"] and "--name" in argv:
            name = argv[argv.index("--name") + 1]
            self.containers.add(name)
        return result


def _site(name):
    from core.models import Project, Site

    project = Project.objects.create(name=name, slug=f"p-db-{name}")
    return Site.objects.create(project=project, name=name)


def _put_payloads(transport):
    payloads = []
    for kind, remote in transport.calls:
        if kind != "put":
            continue
        payload = transport.files[remote]
        if isinstance(payload, (bytes, bytearray)):
            payloads.append(bytes(payload))
        else:
            payloads.append(Path(payload).read_bytes())
    return payloads


def _runs(transport):
    return [argv for kind, argv in transport.calls if kind == "run"]


@pytest.mark.req("SEC-69-KEK-NEVER-IN-BACKUPS")
def test_ensures_postgres_role_and_vaults_url():
    """First ensure runs postgres + CREATE ROLE and vaults DATABASE_URL.

    What would make this fail: inspect via run, skipping docker run, no CREATE ROLE,
    or storing the URL as plaintext outside vault.service.put.
    """
    from provision.db import ensure_site_db
    from vault import service
    from vault.models import Secret

    site = _site("shop")
    transport = PostgresTransport()
    ensure_site_db({"transport": transport, "site": site, "site_slug": "shop"})

    inspects = [
        (kind, argv) for kind, argv in transport.calls
        if kind in ("probe", "run") and "inspect" in argv
    ]
    assert inspects
    assert all(kind == "probe" for kind, argv in inspects)

    runs = _runs(transport)
    assert any(
        argv[:2] == ["docker", "run"]
        and any(str(part).startswith("postgres") for part in argv)
        and "site-shop-postgres" in argv
        and "--env-file" in argv
        for argv in runs
    ), f"expected docker run --env-file of site-shop-postgres, got {runs}"
    assert not any("CREATE ROLE" in " ".join(argv) for argv in runs)
    assert any(
        b"CREATE ROLE" in payload for payload in _put_payloads(transport)
    ), "expected CREATE ROLE SQL via put, not argv"

    secret = Secret.objects.get(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
    )
    url = service.get(secret)
    assert url.startswith(b"postgres://")
    assert b"site-shop-postgres" in url


@pytest.mark.req("SEC-69-KEK-NEVER-IN-BACKUPS")
def test_container_miss_replaces_stale_vaulted_url():
    """A missing container with an existing DATABASE_URL vaults the minted password.

    What would make this fail: skipping put because a Secret row exists, so
    vault.service.get keeps the dead URL after CREATE ROLE minted a new one.
    """
    from provision.db import ensure_site_db
    from vault import service
    from vault.models import Secret

    site = _site("rotate")
    stale = b"postgres://rotate:dead-password@site-rotate-postgres:5432/rotate"
    service.put(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
        plaintext=stale,
    )
    transport = PostgresTransport()
    ensure_site_db({"transport": transport, "site": site, "site_slug": "rotate"})

    secret = Secret.objects.get(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
    )
    url = service.get(secret)
    assert url != stale
    assert url.startswith(b"postgres://")
    assert b"dead-password" not in url
    role_sql = next(
        (
            payload.decode() if isinstance(payload, (bytes, bytearray)) else str(payload)
            for payload in _put_payloads(transport)
            if b"CREATE ROLE" in (
                payload if isinstance(payload, (bytes, bytearray)) else payload.encode()
            )
        ),
        "",
    )
    assert role_sql, "expected CREATE ROLE on the miss path"
    minted = role_sql.split("PASSWORD '", 1)[1].split("'", 1)[0].encode()
    assert minted in url
    assert minted not in stale


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_ensure_zero_mutating_calls():
    """A present postgres container is probed then skipped; second call mutates nothing.

    What would make this fail: inspect via run, or docker run/exec/put on the replay.
    """
    from provision.db import ensure_site_db

    site = _site("replay")
    transport = PostgresTransport()
    desired = {"transport": transport, "site": site, "site_slug": "replay"}
    ensure_site_db(desired)
    assert transport.mutating_calls(), "first call must run so the second can skip"

    transport.calls.clear()
    ensure_site_db(desired)
    assert transport.mutating_calls() == []
    probes = [(kind, argv) for kind, argv in transport.calls if kind == "probe"]
    assert probes
    assert all(kind == "probe" for kind, argv in probes)


@pytest.mark.req("SEC-69-KEK-NEVER-IN-BACKUPS")
def test_database_url_not_in_build_context(tmp_path):
    """Vaulted DATABASE_URL bytes never enter a put payload or the build-context tar.

    What would make this fail: putting the URL onto the target as a file, baking it
    into a Dockerfile, or shipping it inside ensure_build's context tar.
    """
    from test_ensure_build import StepTransport

    from deploys.steps import ensure_build
    from provision.db import ensure_site_db
    from vault import service
    from vault.models import Secret

    site = _site("ctx")
    db_transport = PostgresTransport()
    ensure_site_db({"transport": db_transport, "site": site, "site_slug": "ctx"})
    secret = Secret.objects.get(
        kind=Secret.Kind.DATABASE_URL,
        owner_type="site",
        owner_id=str(site.pk),
    )
    url = service.get(secret)
    assert url.startswith(b"postgres://")

    for argv in _runs(db_transport):
        joined = " ".join(str(part) for part in argv).encode()
        assert url not in joined
        assert b"-e" not in joined or b"POSTGRES_PASSWORD=" not in joined

    source = tmp_path / "src"
    source.mkdir()
    (source / "app.js").write_text("console.log('ok');\n")
    (source / "package.json").write_text('{"name": "fixture"}\n')
    build_transport = StepTransport()
    ensure_build({
        "transport": build_transport,
        "source_dir": str(source),
        "git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "manifest_body": {"runtime": "node"},
    })
    payloads = _put_payloads(build_transport)
    assert payloads, "expected ensure_build to put a context tar"
    for payload in payloads:
        assert url not in payload

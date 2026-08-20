"""Operation locks live in Postgres, not Redis (§A5 / REL-A5-POSTGRES-LOCKS).

T1 runs on SQLite: uniqueness + INSERT-conflict refuse is the proof. SELECT FOR
UPDATE is ignored here and is not claimed.
"""
import ast
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db

REQ = pytest.mark.req("REL-A5-POSTGRES-LOCKS")

FORBIDDEN_ROOTS = {"redis", "django_redis"}
FORBIDDEN_MODULES = {"django.core.cache"}


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            if node.module == "django.core" and any(a.name == "cache" for a in node.names):
                found.add("django.core.cache")
    return found


def _redis_or_cache_imports(source: str) -> list[str]:
    offenders = []
    for name in sorted(_imported_modules(source)):
        root = name.split(".")[0]
        if root in FORBIDDEN_ROOTS or name in FORBIDDEN_MODULES:
            offenders.append(name)
        elif name.startswith("django.core.cache."):
            offenders.append(name)
    return offenders


def _simulate_redis_wipe():
    """Drop anything a Redis restart would drop. The lock row must survive."""
    from django.conf import settings
    from django.core.cache import cache

    cache.clear()
    url = getattr(settings, "REDIS_URL", "") or ""
    try:
        import redis
    except ImportError:
        return
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=0.2)
        client.ping()
        client.flushdb()
    except Exception:
        return


@REQ
def test_lock_lives_in_postgres_not_redis():
    """acquire writes an OperationLock row and never imports redis or the cache.

    What would make this fail: storing the lock in Redis/cache, or importing
    redis / django-redis / django.core.cache on the acquire path.
    """
    from core import locks
    from core.models import OperationLock

    source = Path(inspect.getfile(locks)).read_text(encoding="utf-8")
    assert _redis_or_cache_imports(source) == []
    assert _redis_or_cache_imports(inspect.getsource(locks.acquire)) == []

    lock = locks.acquire("site", "7", "deploy", "worker-a")
    assert lock is not None
    row = OperationLock.objects.get(scope="site", object_id="7", kind="deploy")
    assert row.holder == "worker-a"
    assert row.pk == lock.pk


@REQ
def test_second_acquire_on_same_site_deploy_refuses():
    """Unique (scope, object_id, kind) — a second INSERT is refused, not waited.

    What would make this fail: upserting, waiting, or allowing two holders on
    the same site+deploy lock.
    """
    from core import locks

    first = locks.acquire("site", "3", "deploy", "worker-a")
    second = locks.acquire("site", "3", "deploy", "worker-b")
    assert first is not None
    assert second is None


@REQ
def test_redis_flushdb_does_not_release_held_lock():
    """A Redis wipe must not drop a held lock or let a second acquire through.

    What would make this fail: the lock living in Redis/cache so flushdb/clear
    releases it.
    """
    from core import locks
    from core.models import OperationLock

    held = locks.acquire("site", "9", "deploy", "worker-a")
    assert held is not None
    _simulate_redis_wipe()
    assert OperationLock.objects.filter(pk=held.pk).exists()
    assert locks.acquire("site", "9", "deploy", "worker-b") is None

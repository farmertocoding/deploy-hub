"""Worker-entry seam hygiene (2.5 panel I2).

A product entry point must not reach into tests/, and an env var alone must
never repoint a worker's database.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKER_ENTRY = REPO / "deploys" / "worker_entry.py"


def test_worker_entry_does_not_import_from_tests():
    """Every import in worker_entry resolves inside the product tree.

    What would make this fail: re-inserting tests/ onto sys.path and importing
    pipeline_fakes — the product→test-tree reach the import-rule gate cannot
    see, because the module name carries no `tests.` prefix.
    """
    source = WORKER_ENTRY.read_text(encoding="utf-8")
    assert "sys.path" not in source, "worker_entry manipulates sys.path"

    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in sorted(imported):
        top = name.split(".")[0]
        assert top != "tests", f"worker_entry imports {name!r} from tests/"
        assert not (REPO / "tests" / f"{top}.py").exists(), (
            f"worker_entry imports {name!r}, which resolves to tests/{top}.py"
        )


@pytest.mark.django_db
def test_database_rebind_requires_test_mode(monkeypatch, settings, tmp_path):
    """HUB_TEST_DATABASE is honoured only under HUB_TEST_MODE.

    What would make this fail: bind_test_database rebinding on the env var
    alone — a prod worker repointed at an attacker-chosen database file.
    """
    from django.db import connections

    from deploys.worker_entry import bind_test_database

    # Stub close_all: really closing the suite's shared in-memory test database
    # here would drop its schema for every later django_db test. The gate is
    # what is under test, not the reconnect.
    closed = []
    monkeypatch.setattr(connections, "close_all", lambda: closed.append(True))

    original = settings.DATABASES["default"]["NAME"]
    decoy = tmp_path / "decoy.sqlite3"
    monkeypatch.setenv("HUB_TEST_DATABASE", str(decoy))
    try:
        settings.HUB_TEST_MODE = False
        bind_test_database()
        assert settings.DATABASES["default"]["NAME"] == original
        assert not closed

        settings.HUB_TEST_MODE = True
        bind_test_database()
        assert settings.DATABASES["default"]["NAME"] == str(decoy)
        assert closed, "the rebind must drop stale connections"
    finally:
        settings.DATABASES["default"]["NAME"] = original
        connections.databases["default"]["NAME"] = original


def test_prod_settings_pin_test_mode_off(monkeypatch, tmp_path):
    """prod.py is the backstop: stray env vars must not open the rebind gate.

    What would make this fail: prod.py inheriting base.py's env-derived
    HUB_TEST_MODE instead of pinning it False the way it pins DEBUG and
    VAULT_ALLOW_FAKE_KEK — a prod worker with HUB_TEST_MODE +
    HUB_TEST_DATABASE in its environment would have its database repointed.
    """
    import importlib

    from hub.settings import base as base_settings

    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_AUDIT_S3_BUCKET", "hub-audit-test")
    monkeypatch.setenv("HUB_TEST_MODE", "1")
    monkeypatch.setenv("HUB_TEST_DATABASE", str(tmp_path / "repointed.sqlite3"))
    try:
        # Reload base first: `from .base import *` in prod.py reads the module
        # as already loaded, so without this the env vars never reach the
        # derivation and the assertion below would pass vacuously.
        importlib.reload(base_settings)
        assert base_settings.HUB_TEST_MODE is True, "env vars never reached base"
        prod = importlib.reload(importlib.import_module("hub.settings.prod"))
        assert prod.HUB_TEST_MODE is False
    finally:
        monkeypatch.undo()
        importlib.reload(base_settings)


@pytest.fixture
def fake_child_db(tmp_path, django_db_blocker):
    """A migrated file-backed sqlite the parent and a worker child can share."""
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connections

    original = settings.DATABASES["default"]["NAME"]

    def bind(name):
        settings.DATABASES["default"]["NAME"] = str(name)
        connections.databases["default"]["NAME"] = str(name)
        connections.close_all()

    db_path = tmp_path / "hub.sqlite3"
    with django_db_blocker.unblock():
        try:
            bind(db_path)
            call_command("migrate", verbosity=0, interactive=False)
            connections["default"].cursor().execute("PRAGMA journal_mode=WAL;")
            connections.close_all()
            yield db_path
        finally:
            bind(original)


def test_fake_child_still_completes_a_deployment(fake_child_db):
    """`python -m deploys.worker_entry pk --fake` succeeds without tests/ on path.

    What would make this fail: the --fake transport still living in the test
    tree (the child's PYTHONPATH here is the repo root only), or the
    HUB_TEST_MODE gate refusing a legitimately declared test child.
    """
    from django.db import connections
    from pipeline_fakes import queued_deployment

    from deploys.models import Deployment

    _site, deployment = queued_deployment("fake-child")
    # A test-mode child is behind the §B9 wall: the zone must be purpose=test
    # and allowlisted, or execute() refuses it.
    zone = _site.primary_target.zone
    zone.purpose = "test"
    zone.save(update_fields=["purpose"])
    connections.close_all()

    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "hub.settings.dev"
    env["HUB_TEST_MODE"] = "1"
    env["HUB_TEST_ZONE_SLUGS"] = zone.slug
    env["HUB_TEST_DATABASE"] = str(fake_child_db)
    env["CONFORMANCE_RUN_REPORT"] = "off"
    env.pop("HUB_TEST_CRASH_AFTER_STEP", None)
    env.pop("HUB_TEST_CRASH_SIGNAL", None)
    env["PYTHONPATH"] = str(REPO)

    proc = subprocess.run(
        [sys.executable, "-m", "deploys.worker_entry", str(deployment.pk), "--fake"],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    connections.close_all()
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED

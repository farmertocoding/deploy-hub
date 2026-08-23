"""Backup operator surface (UX-E5 / D-063 / C7).

Persist sealed dumps, Beat backup-nightly, P1 hub-db-or-backup-failure,
Sites list + T2 test-now, restore command block. Restore UI stays Phase 7.
"""
import json
import os
import re
import stat
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import get_resolver
from django.utils import timezone

from core.transport import FakeTransport
from vault import backup as vault_backup
from vault import service
from vault.models import Secret

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.req("UX-E5-BACKUP-OPERATOR"),
]

REPO = Path(__file__).resolve().parent.parent
DUMP = (
    b"-- PostgreSQL database dump\nCREATE TABLE t (id int);\nDUMP-PLAINTEXT-MARKER"
)
SITES_JSX = REPO / "frontend" / "src" / "screens" / "Sites.jsx"
KIND = "hub-db-or-backup-failure"
FORBIDDEN_LIST_NEEDLES = (
    "ciphertext",
    "wrapped_dek",
    "backup_key",
    "plaintext",
    "age-stub:",
    "BEGIN ",
    "PRIVATE KEY",
)


def _site(name):
    from core.models import Project, Site

    project = Project.objects.create(name=name, slug=f"p-op-{name}")
    from dns_fixtures import default_dns_zone

    return Site.objects.create(
        project=project, name=name, dns_zone=default_dns_zone(),
    )


def _unit(name, *, kind=None):
    from core.models import BackupUnit

    site = _site(name)
    unit = BackupUnit.objects.create(
        site=site,
        kind=kind or BackupUnit.Kind.POSTGRES,
        schedule="0 2 * * *",
    )
    return site, unit


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    from provision import backup as backup_mod

    store = tmp_path / "backups"
    store.mkdir()
    monkeypatch.setattr(backup_mod, "BACKUP_STORE_DIR", store, raising=False)
    return store


@pytest.fixture
def auth_client(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(
        username="op-bak", password="pw-1234567890",
    )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


def _route_strings(patterns=None, prefix=""):
    if patterns is None:
        patterns = get_resolver().url_patterns
    found = []
    for pattern in patterns:
        inner = pattern.pattern
        piece = getattr(inner, "_route", None)
        if piece is None:
            piece = str(inner)
        route = f"{prefix}{piece}"
        name = getattr(pattern, "name", None) or ""
        found.append(f"{route} {name}".lower())
        nested = getattr(pattern, "url_patterns", None)
        if nested is not None:
            found.extend(_route_strings(nested, route))
    return found


def _blob_text(value):
    return json.dumps(value, default=str)


def test_backup_list_hides_key_material(auth_client, backup_dir, monkeypatch):
    """GET /sites/{id}/backups/ returns metadata only — no ciphertext, no key.

    What would make this fail: listing the sealed blob, the backup key, a DEK,
    or KEK material in the JSON the Sites detail consumes.
    """
    from provision.backup import persist_backup

    site, unit = _unit("list")
    run = persist_backup(unit, plaintext=DUMP)
    sealed = (backup_dir / str(run.pk)).read_bytes()
    key_row = Secret.objects.get(
        kind=Secret.Kind.BACKUP_KEY,
        owner_type="site",
        owner_id=str(site.pk),
    )
    backup_key = service.get(key_row, reason="test-list")

    response = auth_client.get(f"/api/v1/sites/{site.pk}/backups/")
    assert response.status_code == 200, response.content
    body = response.json()
    blob = _blob_text(body)
    for needle in FORBIDDEN_LIST_NEEDLES:
        assert needle not in blob, needle
    assert backup_key.hex() not in blob
    assert sealed.hex() not in blob
    assert "age-stub:" not in blob
    dumps = body["units"][0]["dumps"]
    assert dumps, body
    row = dumps[0]
    assert row["bytes"] == len(sealed)
    assert type(row["bytes"]) is int
    assert row["digest"] == run.results["digest"]
    assert "ciphertext" not in row
    assert "key" not in row


def test_test_backup_now_seals_with_backup_key_not_kek(
    auth_client, backup_dir, monkeypatch,
):
    """POST .../backups/{unit_id}/test/ seals with BACKUP_KEY, never the KEK.

    What would make this fail: writing plaintext, sealing with the KEK, skipping
    the Hub-local 0600 path, or returning key material in the test-now JSON.
    """
    from core.models import CheckRun
    from provision import backup as backup_mod
    from provision.backup import persist_backup  # noqa: F401 — the view must call it

    kek = bytes(range(32))
    site, unit = _unit("now")
    monkeypatch.setattr(
        backup_mod,
        "_collect",
        lambda unit, plaintext=None, transport=None: DUMP,
    )
    url = f"/api/v1/sites/{site.pk}/backups/{unit.pk}/test/"
    response = auth_client.post(url, content_type="application/json")
    assert response.status_code == 201, response.content
    body = response.json()
    blob = _blob_text(body)
    for needle in FORBIDDEN_LIST_NEEDLES:
        assert needle not in blob, needle
    assert set(body) == {
        "schema_version", "unit_id", "site_id", "bytes", "digest", "stored_at",
    }
    assert type(body["bytes"]) is int
    assert body["unit_id"] == unit.pk
    assert body["site_id"] == site.pk

    run = CheckRun.objects.get(kind=CheckRun.Kind.BACKUP)
    path = backup_dir / str(run.pk)
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    sealed = path.read_bytes()
    assert sealed.startswith(b"age-stub:")
    assert DUMP not in sealed
    assert kek not in sealed

    key_row = Secret.objects.get(
        kind=Secret.Kind.BACKUP_KEY,
        owner_type="site",
        owner_id=str(site.pk),
    )
    backup_key = service.get(key_row, reason="test-now")
    assert backup_key != kek
    aad = Secret.build_aad(Secret.Kind.BACKUP_KEY, "site", str(site.pk))
    assert vault_backup.unseal(sealed, backup_key, aad=aad) == DUMP


def test_restore_is_command_block_not_a_post(auth_client, backup_dir):
    """Restore is a §6.6 <pre> command block. No Restore POST / button.

    What would make this fail: a restore endpoint, a restore ActionButton, or
    a list payload that omits the copy-paste command.
    """
    from provision.backup import persist_backup

    site, unit = _unit("cmd")
    run = persist_backup(unit, plaintext=DUMP)
    response = auth_client.get(f"/api/v1/sites/{site.pk}/backups/")
    assert response.status_code == 200, response.content
    command = response.json()["restore_command"]
    assert "/var/lib/deploy-hub/backups/" in command
    assert str(run.pk) in command or "{checkrun_pk}" in command
    assert "pg_restore" in command or "age -d" in command
    assert "KEK" in command or "kek" in command.lower()
    assert "BACKUP_KEY" in command or "backup key" in command.lower()
    assert "POST" not in command

    jsx = SITES_JSX.read_text(encoding="utf-8")
    assert "<pre" in jsx
    assert "restore_command" in jsx
    assert "Test backup now" in jsx
    assert not re.search(r"backups/.+restore", jsx)
    assert "export function AttackState" in jsx


def test_no_restore_route_exists(auth_client):
    """urlpatterns contain no POST .../restore/ for backups.

    What would make this fail: adding a restore view, even session-gated.
    """
    site, unit = _unit("noroute")
    offenders = [
        route for route in _route_strings()
        if "restore" in route and "backup" in route
    ]
    assert offenders == [], offenders
    for path in (
        f"/api/v1/sites/{site.pk}/restore/",
        f"/api/v1/sites/{site.pk}/backups/restore/",
        f"/api/v1/sites/{site.pk}/backups/{unit.pk}/restore/",
    ):
        response = auth_client.post(path, content_type="application/json")
        assert response.status_code == 404, f"{path} returned {response.status_code}"


def test_failed_dump_files_hub_db_or_backup_failure(backup_dir):
    """Collect/seal/store failure files P1 hub-db-or-backup-failure and audits.

    What would make this fail: swallowing pg_dump errors, filing a different
    kind, or auditing without raise_alert so the pager never wakes.
    """
    from core.models import AuditEvent, Finding
    from monitor.alert_rules import classify
    from provision.backup import persist_backup

    assert classify(KIND) == "p1"
    site, unit = _unit("fail")
    transport = FakeTransport(
        responses={"pg_dump": {"exit_code": 1, "stderr": "pg_dump failed"}},
    )
    with pytest.raises(RuntimeError):
        persist_backup(unit, transport=transport)

    finding = Finding.objects.get(fingerprint=f"{KIND}:{unit.pk}")
    assert finding.severity == Finding.Severity.P1
    assert KIND in finding.fingerprint
    event = AuditEvent.objects.get(action="backup-failed")
    assert event.severity == AuditEvent.Severity.WARNING
    assert event.object_id == str(unit.pk)


def test_missing_nightly_files_same_kind(backup_dir):
    """A registered unit with no nightly dump files the same P1 kind.

    What would make this fail: treating absence as skip, a second alert kind,
    or omitting Beat backup-nightly so the check never runs.
    """
    from core.models import AuditEvent, Finding
    from provision import tasks as provision_tasks
    from provision.backup import check_missing_nightly

    site, unit = _unit("miss")
    n = check_missing_nightly(now=timezone.now())
    assert n == 1
    finding = Finding.objects.get(fingerprint=f"{KIND}:{unit.pk}")
    assert finding.severity == Finding.Severity.P1
    assert AuditEvent.objects.filter(action="backup-failed").exists()

    entry = settings.CELERY_BEAT_SCHEDULE["backup-nightly"]
    assert entry["task"] == provision_tasks.run_backup_nightly.name
    assert "kwargs" not in entry


def test_restore_drill_skipped_only_when_siteless(backup_dir):
    """Restore-to-clean-container SKIPPED only when no BackupUnit exists.

    What would make this fail: keeping the Phase 2.5 stub so a registered unit
    is silent-skip, or SKIPPED when a sealed dump can be unsealed off-live.
    """
    from core.models import CheckRun
    from monitor.drills import run_restore_clean_drill
    from provision.backup import persist_backup

    empty = run_restore_clean_drill()
    assert empty.status == CheckRun.Status.SKIPPED
    assert empty.status != CheckRun.Status.SUCCEEDED
    assert empty.results.get("reason") == "siteless"
    assert empty.results.get("stub") is not True

    site, unit = _unit("drill")
    persist_backup(unit, plaintext=DUMP)
    ran = run_restore_clean_drill()
    assert ran.status != CheckRun.Status.SKIPPED
    assert ran.status == CheckRun.Status.SUCCEEDED
    assert ran.kind == CheckRun.Kind.RESTORE_CLEAN
    assert "siteless" not in str(ran.results)
    stored = json.dumps(ran.results, default=str)
    assert "age-stub:" not in stored
    assert DUMP.decode() not in stored

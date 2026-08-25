"""Backup operator surface (UX-E5 / D-063 / C7) plus Phase 7 T1 restore.

Persist sealed dumps, Beat backup-nightly, P1 hub-db-or-backup-failure,
Sites list + T2 test-now, restore command block, T1 clean-container restore.
"""
import inspect
import json
import re
import stat
from pathlib import Path

import pytest
import yaml
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


@pytest.mark.req("BACKUP-RESTORE-COMMAND-REMAINS")
def test_restore_is_command_block_not_a_post(auth_client, backup_dir):
    """GET list still returns restore_command; BackupPanel still renders <pre>.

    What would make this fail: dropping the copy-paste block after the T1
    restore button lands, or a list payload that omits restore_command.
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
    assert "site.backup_restore" in jsx
    assert "Restore into clean container" in jsx or "tierFor(\"site.backup_restore\")" in jsx
    assert "export function AttackState" in jsx


@pytest.mark.req("BACKUP-RESTORE-CLEAN-T1")
def test_restore_route_is_require_recent_touch(auth_client):
    """POST .../backups/{unit}/restore/ is T1 RequireRecentTouch, not anonymous.

    What would make this fail: a session-only restore POST, or no route so
    the operator still has only the command block.
    """
    from django.urls import resolve

    from core.permissions import RequireRecentTouch
    from provision.views import BackupRestoreView

    site, unit = _unit("t1route")
    path = f"/api/v1/sites/{site.pk}/backups/{unit.pk}/restore/"
    match = resolve(path)
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is BackupRestoreView
    assert RequireRecentTouch in view_cls.permission_classes
    response = auth_client.post(path, content_type="application/json")
    assert response.status_code == 403, response.content


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


def _named_volume_at(service, container_path):
    """Return declared named-volume sources mounted at container_path."""
    found = []
    for mount in service.get("volumes") or []:
        if isinstance(mount, str):
            parts = mount.split(":")
            if len(parts) < 2:
                continue
            src, dest = parts[0], parts[1]
            if dest != container_path:
                continue
            if src in {".", ""} or src.startswith(".") or "/" in src:
                continue
            found.append(src)
        elif isinstance(mount, dict):
            dest = mount.get("target") or mount.get("destination")
            if dest != container_path:
                continue
            if (mount.get("type") or "volume") != "volume":
                continue
            src = mount.get("source")
            if not src or "/" in str(src) or str(src).startswith("."):
                continue
            found.append(src)
    return found


def test_compose_mounts_named_backup_volume_on_web_deploys_and_probes():
    """Nightly persist, test-now, and restore-drill share the C7 backup path.

    What would make this fail: leaving /var/lib/deploy-hub/backups on each
    container's writable layer, a bind mount, or three different volume names
    so worker-deploys persist is invisible to worker-probes restore-drill and
    the web command block.
    """
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    declared = compose.get("volumes") or {}
    path = "/var/lib/deploy-hub/backups"
    names = []
    for svc_name in ("web", "worker-deploys", "worker-probes"):
        sources = _named_volume_at(compose["services"][svc_name], path)
        named = [src for src in sources if src in declared]
        assert named, (
            f"{svc_name} has no named volume at {path}; "
            f"mounts={compose['services'][svc_name].get('volumes')!r}"
        )
        names.append(named[0])
    assert len(set(names)) == 1, names


def test_succeeded_checkrun_without_blob_files_missing_nightly_p1(backup_dir):
    """A SUCCEEDED BACKUP row with no file at BACKUP_STORE_DIR/{pk} pages P1.

    What would make this fail: treating CheckRun-only success as a usable
    nightly so a crash between save() and os.replace, a deleted blob, or a
    split-brain store leaves hub-db-or-backup-failure silent.
    """
    from core.models import AuditEvent, CheckRun, Finding
    from provision.backup import check_missing_nightly, persist_backup

    site, unit = _unit("ghost")
    now = timezone.now()
    run = CheckRun.objects.create(
        kind=CheckRun.Kind.BACKUP,
        status=CheckRun.Status.SUCCEEDED,
        started=now,
        finished=now,
        results={
            "schema_version": 1,
            "unit_id": unit.pk,
            "site_id": site.pk,
            "bytes": 32,
            "digest": "b" * 64,
            "stored_at": now.isoformat(),
        },
    )
    assert not (backup_dir / str(run.pk)).exists()
    blob = json.dumps(run.results, default=str)
    for needle in FORBIDDEN_LIST_NEEDLES:
        assert needle not in blob, needle

    n = check_missing_nightly(now=now)
    assert n == 1
    finding = Finding.objects.get(fingerprint=f"{KIND}:{unit.pk}")
    assert finding.severity == Finding.Severity.P1
    event = AuditEvent.objects.get(action="backup-failed")
    assert event.severity == AuditEvent.Severity.WARNING
    assert event.object_id == str(unit.pk)
    assert event.detail.get("missing") is True

    _, ok_unit = _unit("with-blob")
    ok_run = persist_backup(ok_unit, plaintext=DUMP)
    assert (backup_dir / str(ok_run.pk)).is_file()
    check_missing_nightly(now=now)
    assert not Finding.objects.filter(fingerprint=f"{KIND}:{ok_unit.pk}").exists()


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


RESTORE_URL = "/api/v1/sites/{site_id}/backups/{unit_id}/restore/"
INSTANCE_WORD = re.compile(r"\binstance\b")


def _inject_restore(monkeypatch):
    """Wrap the view callee so HTTP never hits live docker."""
    from provision import backup as backup_mod

    seen = []

    def injected(unit, plaintext):
        seen.append(plaintext)
        return True

    real = backup_mod.restore_to_clean

    def wrapped(unit, *, checkrun_pk, restore_to_clean=None):
        return real(
            unit,
            checkrun_pk=checkrun_pk,
            restore_to_clean=restore_to_clean or injected,
        )

    monkeypatch.setattr("provision.views.restore_to_clean", wrapped)
    return seen


def _post_restore(client, site, unit, *, checkrun_pk, confirm_name=None):
    body = {
        "checkrun_pk": checkrun_pk,
        "confirm_name": site.name if confirm_name is None else confirm_name,
    }
    return client.post(
        RESTORE_URL.format(site_id=site.pk, unit_id=unit.pk),
        data=json.dumps(body),
        content_type="application/json",
    )


@pytest.mark.req("BACKUP-RESTORE-CLEAN-T1")
def test_restore_to_clean_unseals_chosen_dump_with_backup_key(backup_dir):
    """restore_to_clean unseals BACKUP_KEY, never KEK; metadata only.

    What would make this fail: using the KEK, writing dump bytes into
    CheckRun, or calling the inject with sealed bytes.
    """
    from core.models import CheckRun, SiteInstance
    from provision.backup import persist_backup, restore_to_clean
    from vault import service
    from vault.models import Secret

    site, unit = _unit("clean")
    run = persist_backup(unit, plaintext=DUMP)
    key_row = Secret.objects.get(
        kind=Secret.Kind.BACKUP_KEY, owner_type="site", owner_id=str(site.pk),
    )
    backup_key = service.get(key_row, reason="restore-proof")

    seen = []

    def injected(called_unit, plaintext):
        seen.append((called_unit.pk, plaintext))
        return True

    before = SiteInstance.objects.count()
    restore_run = restore_to_clean(
        unit, checkrun_pk=run.pk, restore_to_clean=injected,
    )
    assert restore_run.kind == CheckRun.Kind.RESTORE_CLEAN
    assert restore_run.status == CheckRun.Status.SUCCEEDED
    assert restore_run.results == {
        "schema_version": 1,
        "unit_id": unit.pk,
        "site_id": site.pk,
        "checkrun_pk": run.pk,
    }
    blob = json.dumps(restore_run.results, default=str)
    for needle in FORBIDDEN_LIST_NEEDLES:
        assert needle not in blob, needle
    assert DUMP.decode() not in blob
    assert backup_key.hex() not in blob
    assert seen == [(unit.pk, DUMP)]
    assert not any(p.startswith(b"age-stub:") for _, p in seen)
    assert SiteInstance.objects.count() == before
    src = inspect.getsource(restore_to_clean)
    assert "Secret.Kind.KEK" not in src
    assert "docker" not in src


@pytest.mark.req("BACKUP-RESTORE-CLEAN-T1")
def test_restore_http_is_t1_type_the_site_name(client, backup_dir, monkeypatch):
    """T1 POST restore: touch + type-the-site-name; 201; no ciphertext.

    What would make this fail: confirm_name ignored, binding key material
    from the request, or a 201 that returns dump bytes.
    """
    from test_aws_enroll import _t1_user, _touch

    from core.actions import ACTION_TIERS
    from core.models import CheckRun, SiteInstance
    from provision.backup import persist_backup
    from provision.views import BackupRestoreSerializer, BackupRestoreView
    from tests.test_webauthn_t1 import T1_HTTP

    _t1_user(client)
    _touch(client, monkeypatch)
    seen = _inject_restore(monkeypatch)
    site, unit = _unit("http")
    run = persist_backup(unit, plaintext=DUMP)
    before = (
        SiteInstance.objects.count(),
        CheckRun.objects.filter(kind=CheckRun.Kind.RESTORE_CLEAN).count(),
    )
    response = _post_restore(client, site, unit, checkrun_pk=run.pk)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body == {"ok": True, "unit_id": unit.pk, "checkrun_pk": run.pk}
    blob = _blob_text(body)
    for needle in FORBIDDEN_LIST_NEEDLES:
        assert needle not in blob, needle
    assert DUMP.decode() not in blob
    assert seen == [DUMP]
    restore_run = CheckRun.objects.get(kind=CheckRun.Kind.RESTORE_CLEAN)
    assert restore_run.status == CheckRun.Status.SUCCEEDED
    assert restore_run.results["checkrun_pk"] == run.pk
    assert SiteInstance.objects.count() == before[0]
    assert INSTANCE_WORD.search(blob) is None

    row = next(r for r in ACTION_TIERS if r["id"] == "site.backup_restore")
    assert row == {
        "id": "site.backup_restore",
        "tier": "T1",
        "label": "Restore into clean container",
    }
    assert INSTANCE_WORD.search(row["label"]) is None
    assert set(BackupRestoreSerializer().get_fields()) == {
        "checkrun_pk", "confirm_name",
    }
    view_src = inspect.getsource(BackupRestoreView)
    assert "backup_key" not in view_src
    assert "ciphertext" not in view_src
    assert "request.data.get" not in view_src
    assert T1_HTTP["site.backup_restore"] == "/api/v1/sites/{pk}/backups/1/restore/"


@pytest.mark.req("BACKUP-RESTORE-CLEAN-T1")
def test_restore_wrong_confirm_is_4xx(client, backup_dir, monkeypatch):
    """confirm_name != site.name → 4xx; no SUCCEEDED restore CheckRun.

    What would make this fail: confirm_name ignored so any string restores.
    """
    from test_aws_enroll import _t1_user, _touch

    from core.models import CheckRun
    from provision.backup import persist_backup

    _t1_user(client)
    _touch(client, monkeypatch)
    _inject_restore(monkeypatch)
    site, unit = _unit("wrong")
    run = persist_backup(unit, plaintext=DUMP)
    response = _post_restore(
        client, site, unit, checkrun_pk=run.pk, confirm_name="wrong-site",
    )
    assert 400 <= response.status_code < 500, response.content
    blob = response.content.decode()
    for needle in FORBIDDEN_LIST_NEEDLES:
        assert needle not in blob, needle
    assert DUMP.decode() not in blob
    assert not CheckRun.objects.filter(
        kind=CheckRun.Kind.RESTORE_CLEAN, status=CheckRun.Status.SUCCEEDED,
    ).exists()


@pytest.mark.req("BACKUP-RESTORE-CLEAN-T1")
def test_restore_missing_dump_is_4xx(client, backup_dir, monkeypatch):
    """Unknown checkrun_pk → 4xx; no SUCCEEDED restore; no ciphertext.

    What would make this fail: inventing a dump or returning sealed bytes.
    """
    from test_aws_enroll import _t1_user, _touch

    from core.models import AuditEvent, CheckRun

    _t1_user(client)
    _touch(client, monkeypatch)
    _inject_restore(monkeypatch)
    site, unit = _unit("missdump")
    response = _post_restore(client, site, unit, checkrun_pk=999_001)
    assert 400 <= response.status_code < 500, response.content
    blob = response.content.decode()
    for needle in FORBIDDEN_LIST_NEEDLES:
        assert needle not in blob, needle
    assert not CheckRun.objects.filter(
        kind=CheckRun.Kind.RESTORE_CLEAN, status=CheckRun.Status.SUCCEEDED,
    ).exists()
    assert AuditEvent.objects.filter(action="backup-restore-failed").exists()


@pytest.mark.req("BACKUP-RESTORE-CLEAN-T1")
def test_restore_still_requires_recent_touch(client, backup_dir, monkeypatch):
    """Without hardware_touch_at the restore POST is 403.

    Unmarked-adjacent: C3 RequireRecentTouch, not the unseal clause.
    """
    from test_aws_enroll import _t1_user

    from provision.backup import persist_backup

    _t1_user(client)
    _inject_restore(monkeypatch)
    site, unit = _unit("notouch")
    run = persist_backup(unit, plaintext=DUMP)
    response = _post_restore(client, site, unit, checkrun_pk=run.pk)
    assert response.status_code == 403, response.content

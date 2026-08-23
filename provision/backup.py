"""Seal BackupUnit dumps with a vaulted backup key, never the KEK.

Persist the sealed blob at BACKUP_STORE_DIR / {checkrun_pk} (mode 0600).
CheckRun.results hold metadata only. Production live form is `pg_dump | age`
(or sqlite `.backup` / directory sync); T1 seals with AES-GCM so tests need
no `age` binary.
"""
import hashlib
import os
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from vault import backup as vault_backup
from vault import service
from vault.models import Secret

BACKUP_STORE_DIR = Path("/var/lib/deploy-hub/backups")
RESULTS_SCHEMA_VERSION = 1
_NIGHTLY_WINDOW = timedelta(hours=24)


def run_backup(unit, *, plaintext=None, transport=None):
    """Given a BackupUnit, return sealed dump bytes. Failure audits then re-raises."""
    try:
        dump = _collect(unit, plaintext=plaintext, transport=transport)
        key_row = _ensure_backup_key(unit.site)
        key = service.get(key_row, reason="site-backup")
        aad = Secret.build_aad(
            Secret.Kind.BACKUP_KEY, "site", str(unit.site_id),
        )
        return vault_backup.seal(dump, key, aad=aad)
    except Exception:
        from core.audit import audit

        audit("backup-failed", unit, source="system", severity="warning")
        raise


def persist_backup(unit, *, plaintext=None, transport=None):
    """Seal, write CheckRun metadata, store ciphertext at BACKUP_STORE_DIR/{pk}."""
    from core.models import CheckRun

    try:
        sealed = run_backup(unit, plaintext=plaintext, transport=transport)
    except Exception:
        _alert_backup_failure(unit)
        raise

    now = timezone.now()
    results = {
        "schema_version": RESULTS_SCHEMA_VERSION,
        "unit_id": int(unit.pk),
        "site_id": int(unit.site_id),
        "bytes": int(len(sealed)),
        "digest": hashlib.sha256(sealed).hexdigest(),
        "stored_at": now.isoformat(),
    }
    run = CheckRun(
        kind=CheckRun.Kind.BACKUP,
        status=CheckRun.Status.SUCCEEDED,
        started=now,
        finished=now,
        results=results,
    )
    try:
        run.save()
        _store_blob(run.pk, sealed)
    except Exception:
        from core.audit import audit

        if run.pk:
            run.status = CheckRun.Status.FAILED
            run.save(update_fields=["status"])
        audit("backup-failed", unit, source="system", severity="warning")
        _alert_backup_failure(unit)
        raise
    return run


def check_missing_nightly(*, now=None):
    """P1 for every registered unit with no succeeded dump in the last 24 h."""
    from core.audit import audit
    from core.models import BackupUnit

    clock = now or timezone.now()
    cutoff = clock - _NIGHTLY_WINDOW
    n = 0
    for unit in BackupUnit.objects.select_related("site").order_by("pk"):
        if _has_recent_succeeded_dump(unit, cutoff):
            continue
        audit("backup-failed", unit, source="system", severity="warning", missing=True)
        _alert_backup_failure(unit, missing=True)
        n += 1
    return n


def run_nightly(*, now=None, transport_for=None, plaintext_for=None):
    """Beat backup-nightly: persist each unit, then file missing-nightly P1s."""
    from core.models import BackupUnit

    n_ok = n_fail = 0
    for unit in BackupUnit.objects.select_related("site").order_by("pk"):
        plaintext = plaintext_for(unit) if plaintext_for is not None else None
        transport = None
        if plaintext is None:
            if transport_for is not None:
                transport = transport_for(unit)
            else:
                transport = transport_for_site(unit.site)
        try:
            persist_backup(unit, plaintext=plaintext, transport=transport)
            n_ok += 1
        except Exception:
            n_fail += 1
    n_missing = check_missing_nightly(now=now)
    return {"ok": True, "n_ok": n_ok, "n_fail": n_fail, "n_missing": n_missing}


def list_payload(site):
    """Metadata-only list plus the §6.6 restore command block. Never ciphertext."""
    from core.models import BackupUnit

    units = []
    latest_pk = None
    for unit in BackupUnit.objects.filter(site=site).order_by("pk"):
        dumps = []
        for run in _succeeded_runs(unit):
            dumps.append({
                "id": run.pk,
                "bytes": int(run.results["bytes"]),
                "digest": run.results["digest"],
                "stored_at": run.results["stored_at"],
                "status": run.status,
            })
            if latest_pk is None or run.pk > latest_pk:
                latest_pk = run.pk
        units.append({
            "id": unit.pk,
            "kind": unit.kind,
            "schedule": unit.schedule,
            "dumps": dumps,
        })
    return {
        "units": units,
        "restore_command": restore_command_block(site, checkrun_pk=latest_pk),
    }


def restore_command_block(site, *, checkrun_pk=None):
    """Copy-paste restore. No restore API. Never the KEK."""
    pk = checkrun_pk if checkrun_pk is not None else "{checkrun_pk}"
    blob = f"/var/lib/deploy-hub/backups/{pk}"
    return (
        f"# Restore site {site.name} (id {site.pk}) into a clean container.\n"
        "# What: decrypt the sealed dump with Secret.Kind.BACKUP_KEY for this site.\n"
        "# Why it matters: a restore that uses the KEK, or overwrites live, is the\n"
        "# wrong drill. Restore UI stays Phase 7; there is no restore API.\n"
        "# Exact fix: copy-paste. The backup key never appears in this block.\n"
        "\n"
        f"age -d -i /var/lib/deploy-hub/backup-keys/site-{site.pk}.key \\\n"
        f"  {blob} \\\n"
        "  | docker run --rm -i --name hub-restore-clean postgres:16 "
        "pg_restore -d postgres --clean --if-exists\n"
    )


def latest_unsealed_dump(unit):
    """Open the latest succeeded blob with BACKUP_KEY. Never the KEK."""
    runs = _succeeded_runs(unit)
    if not runs:
        raise RuntimeError("no sealed dump")
    run = runs[0]
    sealed = (BACKUP_STORE_DIR / str(run.pk)).read_bytes()
    key_row = Secret.objects.filter(
        kind=Secret.Kind.BACKUP_KEY,
        owner_type="site",
        owner_id=str(unit.site_id),
    ).first()
    if key_row is None:
        raise RuntimeError("no backup key")
    key = service.get(key_row, reason="restore-drill")
    aad = Secret.build_aad(
        Secret.Kind.BACKUP_KEY, "site", str(unit.site_id),
    )
    return vault_backup.unseal(sealed, key, aad=aad)


def transport_for_site(site):
    target = getattr(site, "primary_target", None)
    if target is None:
        return None
    from core.ssh import SshTransport

    return SshTransport(target)


def _collect(unit, *, plaintext, transport):
    if plaintext is not None:
        return plaintext
    if transport is None:
        raise ValueError("plaintext or transport is required to collect a dump")
    result = transport.run(["pg_dump", "-Fc", str(unit.site_id)])
    if not result.ok:
        raise RuntimeError(result.stderr or "pg_dump failed")
    stdout = result.stdout or ""
    return stdout if isinstance(stdout, bytes) else stdout.encode()


def _ensure_backup_key(site):
    existing = Secret.objects.filter(
        kind=Secret.Kind.BACKUP_KEY,
        owner_type="site",
        owner_id=str(site.pk),
    ).first()
    if existing is not None:
        return existing
    return service.put(
        kind=Secret.Kind.BACKUP_KEY,
        owner_type="site",
        owner_id=str(site.pk),
        plaintext=os.urandom(vault_backup.BACKUP_KEY_BYTES),
    )


def _store_blob(run_pk, sealed):
    BACKUP_STORE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(BACKUP_STORE_DIR, 0o700)
    except OSError:
        pass
    final = BACKUP_STORE_DIR / str(run_pk)
    tmp = BACKUP_STORE_DIR / f".tmp-{run_pk}-{os.getpid()}"
    tmp.write_bytes(sealed)
    os.chmod(tmp, 0o600)
    os.replace(tmp, final)
    os.chmod(final, 0o600)
    return final


def _succeeded_runs(unit):
    from core.models import CheckRun

    rows = []
    for run in CheckRun.objects.filter(
        kind=CheckRun.Kind.BACKUP,
        status=CheckRun.Status.SUCCEEDED,
    ).order_by("-pk"):
        if run.results.get("unit_id") == unit.pk:
            rows.append(run)
    return rows


def _has_recent_succeeded_dump(unit, cutoff):
    for run in _succeeded_runs(unit):
        when = run.finished or run.started
        if when is not None and when >= cutoff:
            return True
    return False


def _alert_backup_failure(unit, *, missing=False):
    from monitor.alerts import raise_alert

    title = (
        "Nightly backup missing"
        if missing
        else "Backup collect/seal/store failed"
    )
    raise_alert(
        "hub-db-or-backup-failure",
        str(unit.pk),
        fingerprint=f"hub-db-or-backup-failure:{unit.pk}",
        source_engine="provision.backup",
        title=title,
        body=(
            "A registered BackupUnit has no usable nightly dump, or collect/"
            "seal/store failed. Missing backups mean restore cannot run."
        ),
        fix_action=(
            "Inspect /var/lib/deploy-hub/backups/ and run test backup now. "
            "Restore stays a command block."
        ),
    )

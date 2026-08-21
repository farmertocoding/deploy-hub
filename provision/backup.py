"""Backup Beat stub: seal a BackupUnit dump with a vaulted backup key, never the KEK.

Production live form is `pg_dump | age` (or sqlite `.backup` / directory sync).
T1 encrypts with the backup key via AES-GCM (`vault.backup.seal`) so tests need
no `age` binary. Failure writes an AuditEvent; ntfy is Phase 3.
"""
import os

from vault import backup as vault_backup
from vault import service
from vault.models import Secret


def run_backup(unit, *, plaintext=None, transport=None):
    """Given a BackupUnit, return sealed dump bytes. Failure audits then re-raises."""
    try:
        dump = _collect(unit, plaintext=plaintext, transport=transport)
        key_row = _ensure_backup_key(unit.site)
        key = service.get(key_row, reason="site-backup")
        return vault_backup.seal(dump, key)
    except Exception:
        from core.audit import audit

        audit("backup-failed", unit, source="system", severity="warning")
        raise


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

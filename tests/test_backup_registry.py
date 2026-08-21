"""BackupUnit registry + Beat stub: dumps are sealed, KEK never in dump bytes."""
import os
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.utils import IntegrityError
from django.test import override_settings

from vault import service
from vault.models import Secret

pytestmark = pytest.mark.django_db

DUMP_PLAINTEXT_MARKER = (
    b"-- PostgreSQL database dump\nCREATE TABLE t (id int);\nDUMP-PLAINTEXT-MARKER"
)


def _site(name):
    from core.models import Project, Site

    project = Project.objects.create(name=name, slug=f"p-bak-{name}")
    return Site.objects.create(project=project, name=name)


def _keyfile(tmp_path):
    path = tmp_path / "vault.key"
    material = os.urandom(32)
    path.write_bytes(material)
    path.chmod(0o400)
    return path, material


def _simulated_hub_dump():
    """Bytes a Hub DB dump would carry: dumpdata JSON, sqlite file, raw Secret columns."""
    chunks = []
    buf = StringIO()
    call_command("dumpdata", stdout=buf)
    chunks.append(buf.getvalue().encode())
    for secret in Secret.objects.all():
        chunks.append(bytes(secret.ciphertext))
        chunks.append(bytes(secret.wrapped_dek))
        chunks.append(bytes(secret.nonce))
        chunks.append(secret.kek_id.encode())
        chunks.append(secret.fingerprint.encode())
        chunks.append(secret.kind.encode())
    name = connection.settings_dict.get("NAME")
    path = Path(str(name)) if name else None
    if path is not None and path.is_file():
        chunks.append(path.read_bytes())
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names():
            quoted = table.replace('"', "")
            cursor.execute(f'SELECT * FROM "{quoted}"')
            for row in cursor.fetchall():
                for col in row:
                    if isinstance(col, (bytes, bytearray, memoryview)):
                        chunks.append(bytes(col))
                    elif col is not None:
                        chunks.append(str(col).encode("utf-8", errors="replace"))
    return b"\0".join(chunks)


def test_backup_unit_kinds():
    """kind ∈ {postgres, sqlite_file, directory_sync}, unique per site+kind.

    What would make this fail: dropping a kind, inventing a fourth, or allowing two
    postgres units on one site.
    """
    from core.models import BackupUnit

    assert set(BackupUnit.Kind.values) == {
        "postgres",
        "sqlite_file",
        "directory_sync",
    }
    site = _site("kinds")
    other = _site("kinds-b")
    BackupUnit.objects.create(
        site=site, kind=BackupUnit.Kind.POSTGRES, schedule="0 2 * * *",
    )
    BackupUnit.objects.create(
        site=site, kind=BackupUnit.Kind.SQLITE_FILE, schedule="0 3 * * *",
    )
    BackupUnit.objects.create(
        site=other, kind=BackupUnit.Kind.POSTGRES, schedule="0 2 * * *",
    )
    with pytest.raises(IntegrityError):
        BackupUnit.objects.create(
            site=site, kind=BackupUnit.Kind.POSTGRES, schedule="0 4 * * *",
        )


@pytest.mark.req("SEC-69-KEK-NEVER-IN-BACKUPS")
def test_dump_is_age_encrypted_not_plaintext():
    """Backup output is sealed (age-stub prefix) and does not contain the SQL dump.

    What would make this fail: returning pg_dump stdout as plaintext, or a prefix
    glued onto still-visible SQL. Live form is `| age`; T1 does not require the binary.
    """
    from core.models import BackupUnit
    from provision.backup import run_backup

    site = _site("enc")
    unit = BackupUnit.objects.create(
        site=site, kind=BackupUnit.Kind.POSTGRES, schedule="0 2 * * *",
    )
    sealed = run_backup(unit, plaintext=DUMP_PLAINTEXT_MARKER)
    assert sealed.startswith(b"age-stub:")
    assert DUMP_PLAINTEXT_MARKER not in sealed
    assert b"DUMP-PLAINTEXT-MARKER" not in sealed
    assert b"CREATE TABLE t" not in sealed


@pytest.mark.req("SEC-69-KEK-NEVER-IN-BACKUPS")
def test_kek_absent_from_hub_db_dump(tmp_path):
    """A simulated Hub dump must not contain the keyfile KEK material.

    What would make this fail: storing the KEK in a Secret row, settings, or any
    table the dump serializes. The KEK lives in a keyfile outside the DB.
    """
    keyfile, kek = _keyfile(tmp_path)
    with override_settings(
        VAULT_KEK_BACKEND="local",
        VAULT_KEYFILE=str(keyfile),
        VAULT_KEYFILE_REQUIRE_MODE=True,
    ):
        site = _site("hubdump")
        service.put(
            kind=Secret.Kind.DATABASE_URL,
            owner_type="site",
            owner_id=str(site.pk),
            plaintext=b"postgres://hub:marker-url@db/hub",
        )
        dump = _simulated_hub_dump()
    assert kek not in dump
    assert keyfile.read_bytes() not in dump


@pytest.mark.req("SEC-69-KEK-NEVER-IN-BACKUPS")
def test_kek_absent_from_site_backup_bytes(tmp_path):
    """Site backup ciphertext does not contain KEK bytes or DATABASE_URL plaintext.

    What would make this fail: sealing with the KEK, concatenating the URL, or
    leaving dump plaintext in the artifact.
    """
    from core.models import BackupUnit
    from provision.backup import run_backup

    keyfile, kek = _keyfile(tmp_path)
    url = b"postgres://bak:s3cret-db-url@site-bak-postgres:5432/bak"
    with override_settings(
        VAULT_KEK_BACKEND="local",
        VAULT_KEYFILE=str(keyfile),
        VAULT_KEYFILE_REQUIRE_MODE=True,
    ):
        site = _site("bak")
        service.put(
            kind=Secret.Kind.DATABASE_URL,
            owner_type="site",
            owner_id=str(site.pk),
            plaintext=url,
        )
        unit = BackupUnit.objects.create(
            site=site, kind=BackupUnit.Kind.POSTGRES, schedule="0 2 * * *",
        )
        sealed = run_backup(unit, plaintext=DUMP_PLAINTEXT_MARKER)
        backup_row = Secret.objects.get(
            kind=Secret.Kind.BACKUP_KEY,
            owner_type="site",
            owner_id=str(site.pk),
        )
        backup_key = service.get(backup_row)

    assert backup_key != kek
    assert kek not in sealed
    assert url not in sealed
    assert DUMP_PLAINTEXT_MARKER not in sealed


def test_backup_aad_is_site_bound_swap_fails_closed():
    """Sealed dump AAD is the site's identity; another site's key/AAD cannot open it.

    What would make this fail: sealing with static b"backup-dump" so site A's
    key opens the blob under a foreign AAD, or accepting a swapped ciphertext
    under site B's backup key.
    """
    from cryptography.exceptions import InvalidTag

    from core.models import BackupUnit
    from provision.backup import run_backup
    from vault import backup as vault_backup

    site_a = _site("aad-a")
    site_b = _site("aad-b")
    unit_a = BackupUnit.objects.create(
        site=site_a, kind=BackupUnit.Kind.POSTGRES, schedule="0 2 * * *",
    )
    unit_b = BackupUnit.objects.create(
        site=site_b, kind=BackupUnit.Kind.POSTGRES, schedule="0 2 * * *",
    )
    sealed_a = run_backup(unit_a, plaintext=DUMP_PLAINTEXT_MARKER)
    run_backup(unit_b, plaintext=b"other-site-dump")
    key_a = service.get(Secret.objects.get(
        kind=Secret.Kind.BACKUP_KEY, owner_type="site", owner_id=str(site_a.pk),
    ))
    key_b = service.get(Secret.objects.get(
        kind=Secret.Kind.BACKUP_KEY, owner_type="site", owner_id=str(site_b.pk),
    ))
    aad_a = Secret.build_aad(Secret.Kind.BACKUP_KEY, "site", str(site_a.pk))
    aad_b = Secret.build_aad(Secret.Kind.BACKUP_KEY, "site", str(site_b.pk))

    assert vault_backup.unseal(sealed_a, key_a, aad=aad_a) == DUMP_PLAINTEXT_MARKER
    with pytest.raises(InvalidTag):
        vault_backup.unseal(sealed_a, key_a, aad=aad_b)
    with pytest.raises(InvalidTag):
        vault_backup.unseal(sealed_a, key_b, aad=aad_b)
    with pytest.raises(InvalidTag):
        vault_backup.unseal(sealed_a, key_b, aad=aad_a)

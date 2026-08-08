"""Generate the rung-① KEK keyfile (§6.9). Refuses to overwrite an existing key —
overwriting makes every stored ciphertext permanently unreadable."""
import os
import pathlib

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the vault KEK keyfile (32 random bytes, mode 0400)."

    def handle(self, *args, **options):
        path = pathlib.Path(getattr(settings, "VAULT_KEYFILE", "") or "")
        if not path:
            raise CommandError("VAULT_KEYFILE is not set")
        if path.exists():
            raise CommandError(
                f"{path} already exists — refusing to overwrite. Every secret in the "
                f"vault is unrecoverable without this exact file."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "wb") as fh:
            fh.write(os.urandom(32))
        self.stdout.write(self.style.SUCCESS(f"wrote {path} (mode 400)"))
        self.stdout.write(
            "Back this up OFFLINE and separately from DB backups. The KEK must never "
            "appear in any backup that also contains the database (§6.9)."
        )

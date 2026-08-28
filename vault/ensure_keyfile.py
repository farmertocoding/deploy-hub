"""Mint the local vault keyfile before Django boots.

vault.apps.ready() checks the keyfile, so this module cannot import
django.conf. The Hub image uses this as ENTRYPOINT.
"""
from __future__ import annotations

import os
import pathlib
import stat
import sys

DEFAULT_PATH = "/etc/deploy-hub/vault.key"


def ensure(path=None):
    target = pathlib.Path(
        path or os.environ.get("HUB_VAULT_KEYFILE") or DEFAULT_PATH
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        size = target.stat().st_size
        if size != 32:
            raise SystemExit(
                f"vault keyfile {target} is {size} bytes, expected exactly 32"
            )
        mode = stat.S_IMODE(target.stat().st_mode)
        if mode != 0o400:
            target.chmod(0o400)
        return target
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, "wb") as fh:
        fh.write(os.urandom(32))
    return target


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    ensure()
    if not argv:
        return 0
    os.execvp(argv[0], argv)  # nosec B606 — image CMD, not caller-supplied input
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

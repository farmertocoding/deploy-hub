"""Delete only hub-t3-* Multipass instances (plus tmp `.t3-lease` names)."""
from __future__ import annotations

from pathlib import Path

from tests.harness.multipass import NAME_PREFIX, delete_purge, list_names

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_LEASE_ROOT = REPO / "tmp"


def _lease_names(root):
    root = Path(root)
    if not root.is_dir():
        return []
    names = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name != ".t3-lease" and not path.name.endswith(".t3-lease"):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                names.append(name)
    return names


def reap_test_plane(*, list_fn=None, delete_fn=None, lease_root=None):
    """List, then delete+purge every `hub-t3-*`. Never touch other names.

    `list_fn` / `delete_fn` are injectable so T1 can use a Fake listing.
    """
    listed = list(list_fn() if list_fn is not None else list_names())
    leased = _lease_names(DEFAULT_LEASE_ROOT if lease_root is None else lease_root)
    delete = delete_fn if delete_fn is not None else delete_purge
    seen = set()
    for name in [*listed, *leased]:
        if not name.startswith(NAME_PREFIX) or name in seen:
            continue
        seen.add(name)
        delete(name)

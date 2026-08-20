"""Apply a catalog entry through Transport; same-version re-apply is a no-op."""
from catalog.models import AppliedCatalogEntry


def argv_steps(field):
    """A flat argv (first element a str) is one command; a list of lists is a sequence."""
    if not field:
        raise ValueError("argv field must be a non-empty list")
    if isinstance(field[0], (list, tuple)):
        return [list(step) for step in field]
    return [list(field)]


def apply_entry(target, entry, transport):
    """Run `entry.fix` and write AppliedCatalogEntry.

    If this (target, entry.id) already has this version as the latest row,
    probe `entry.check` and skip — zero mutating Transport calls.

    A failed step stops the sequence; no AppliedCatalogEntry is written, so a
    failed `sshd -t` does not install and does not count as applied.
    """
    latest = (
        AppliedCatalogEntry.objects.filter(target=target, entry_id=entry.id)
        .order_by("-applied_at", "-pk")
        .first()
    )
    if latest is not None and latest.version == entry.version:
        for step in argv_steps(entry.check):
            transport.probe(step)
        return latest

    results = []
    for step in argv_steps(entry.fix):
        result = transport.run(step)
        results.append(result)
        if not result.ok:
            return None

    last = results[-1]
    return AppliedCatalogEntry.objects.create(
        target=target,
        entry_id=entry.id,
        version=entry.version,
        mode="apply",
        result={"ok": last.ok, "exit_code": last.exit_code},
    )

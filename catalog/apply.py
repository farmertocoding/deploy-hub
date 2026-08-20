"""Apply a catalog entry through Transport; same-version re-apply is a no-op."""
from catalog.models import AppliedCatalogEntry


def apply_entry(target, entry, transport):
    """Run `entry.fix` and write AppliedCatalogEntry.

    If this (target, entry.id) already has this version as the latest row,
    probe `entry.check` and skip — zero mutating Transport calls.
    """
    latest = (
        AppliedCatalogEntry.objects.filter(target=target, entry_id=entry.id)
        .order_by("-applied_at", "-pk")
        .first()
    )
    if latest is not None and latest.version == entry.version:
        transport.probe(list(entry.check))
        return latest

    result = transport.run(list(entry.fix))
    return AppliedCatalogEntry.objects.create(
        target=target,
        entry_id=entry.id,
        version=entry.version,
        mode="apply",
        result={"ok": result.ok, "exit_code": result.exit_code},
    )

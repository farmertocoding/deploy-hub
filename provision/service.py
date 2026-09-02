"""Fresh-host provisioner (§E6): refuse occupied 80/443 or site containers.

Inspect via Transport.probe (argv lists). Pre-hardened empty hosts are allowed:
catalog versions are imported into AppliedCatalogEntry without running fix.
When a Hub Beat job matching a script cron is live, that cron is deleted.
"""
import re
from dataclasses import dataclass

from catalog.apply import argv_steps
from catalog.entries import CATALOG, SERVER_WATCH_CRON_D
from catalog.models import AppliedCatalogEntry
from core.hubfs import ensure_hub_dir, hub_join, ssh_user_from
from core.models import require_workspace
from core.test_mode import assert_test_zone

LISTENERS_ARGV = ["ss", "-ltnH"]
CONTAINERS_ARGV = ["docker", "ps", "-a", "--format", "{{.Names}}"]
CRONTAB_LIST_ARGV = ["crontab", "-l"]

# :80 / :443, but not :8080 / :4430.
_HTTP_PORT = re.compile(r":(80|443)(?!\d)")

UFW_BY_PROFILE = {
    "hub": "ufw-posture-hub",
    "target": "ufw-posture-target",
    "intake": "ufw-posture-intake",
}
UFW_IDS = frozenset(UFW_BY_PROFILE.values())
HANDOFF_IDS = frozenset({"server-watch-handoff"})
SERVER_WATCH_SCRIPT = "server-watch.sh"


@dataclass(frozen=True)
class ProvisionResult:
    allowed: bool
    explanation: str = ""


def provision_host(target, transport, *, live_beat_jobs=(), profile="target"):
    """Guard, then import pre-hardened catalog versions. Never a shell string."""
    assert_test_zone(target.zone)
    listeners = transport.probe(LISTENERS_ARGV)
    if not listeners.ok:
        return ProvisionResult(
            allowed=False,
            explanation=_refuse(target, "could not inspect listening ports (ss probe failed)"),
        )
    occupied = {int(m.group(1)) for m in _HTTP_PORT.finditer(listeners.stdout or "")}
    if 80 in occupied:
        return ProvisionResult(
            allowed=False,
            explanation=_refuse(target, "port 80 is occupied"),
        )
    if 443 in occupied:
        return ProvisionResult(
            allowed=False,
            explanation=_refuse(target, "port 443 is occupied"),
        )

    listed = transport.probe(CONTAINERS_ARGV)
    if not listed.ok:
        return ProvisionResult(
            allowed=False,
            explanation=_refuse(target, "could not inspect site containers (docker probe failed)"),
        )
    names = [name for name in (listed.stdout or "").split() if name]
    if names:
        return ProvisionResult(
            allowed=False,
            explanation=_refuse(
                target,
                f"site container(s) present ({', '.join(names)})",
            ),
        )

    _import_catalog_versions(target, transport, profile=profile)
    _delete_script_crons(transport, live_beat_jobs, target=target)
    _issue_target_publisher(target)
    return ProvisionResult(allowed=True)


def handoff_hub_probing(target, transport):
    """Hub-side probing is live: drop server-watch.sh and revoke its token."""
    _delete_script_crons(transport, (SERVER_WATCH_SCRIPT,), target=target)
    _remove_server_watch_cron_d(transport)
    _revoke_target_publisher(target)
    from catalog.entries import ENTRIES
    from catalog.models import AppliedCatalogEntry

    entry = ENTRIES["server-watch-handoff"]
    AppliedCatalogEntry.objects.create(
        target=target,
        entry_id=entry.id,
        version=entry.version,
        mode="handoff",
        result={"ok": True, "script": SERVER_WATCH_SCRIPT},
    )


def _refuse(target, reason):
    return (
        f"Refusing to provision {target.host}: {reason}. "
        "Adopt-existing-site is Phase 3b; use adoption_plan / the adopt flow. "
        "This host is not a fresh target."
    )


def _import_catalog_versions(target, transport, *, profile):
    """Record catalog versions only when verify and that entry's check both succeeded."""
    verify = transport.probe(
        ["env", f"PROFILE={profile}", "/usr/local/sbin/verify-hardening.sh"],
    )
    if not verify.ok:
        return
    wanted_ufw = UFW_BY_PROFILE.get(profile)
    for entry in CATALOG:
        if entry.id in UFW_IDS and entry.id != wanted_ufw:
            continue
        if entry.id in HANDOFF_IDS:
            continue
        if not _checks_ok(transport, entry):
            continue
        AppliedCatalogEntry.objects.create(
            target=target,
            entry_id=entry.id,
            version=entry.version,
            mode="import",
            result={"ok": True, "source": "verify-hardening.sh"},
        )


def _checks_ok(transport, entry):
    """True only if every check step's probe returned ok. A red step is not imported."""
    for step in argv_steps(entry.check):
        if not transport.probe(step).ok:
            return False
    return True


def _delete_script_crons(transport, live_beat_jobs, *, target=None):
    """Drop crontab lines for scripts whose matching Hub Beat job is live."""
    live = tuple(live_beat_jobs or ())
    if not live:
        return
    listed = transport.probe(CRONTAB_LIST_ARGV)
    lines = (listed.stdout or "").splitlines()
    kept = [line for line in lines if not any(script in line for script in live)]
    if kept == lines:
        return
    body = ("\n".join(kept) + "\n") if kept else ""
    user = ssh_user_from(target)
    path = hub_join("crontab", ssh_user=user)
    ensure_hub_dir(transport, user)
    transport.put(body.encode(), path, mode=0o600)
    transport.run(["crontab", path])


def _remove_server_watch_cron_d(transport):
    """Same path the catalog entry checks/fixes — a cron.d host must not keep paging."""
    transport.run(["rm", "-f", SERVER_WATCH_CRON_D])


def _issue_target_publisher(target):
    import secrets

    from providers.ntfy import TokenRevoked, issue_publisher_token

    try:
        # Text token: vault get() returns bytes and ntfy decodes UTF-8.
        issue_publisher_token(f"target:{target.pk}", secrets.token_urlsafe(24))
    except TokenRevoked:
        return


def _revoke_target_publisher(target):
    from monitor.alerts import raise_alert
    from providers.ntfy import mark_revoked, revoke_via_account_api

    identity = f"target:{target.pk}"
    via_api = False
    try:
        via_api = revoke_via_account_api(identity)
    except Exception:
        via_api = False
    mark_revoked(identity)
    if via_api:
        return
    raise_alert(
        "ntfy-token-revoke-pending",
        f"host:{target.host}",
        workspace=require_workspace(target),
        fingerprint=f"ntfy-revoke:{target.pk}",
        source_engine="provision.handoff",
        title=f"Revoke ntfy publish token for {target.host}",
        body=(
            f"Hub probing is live on {target.host}; server-watch.sh is gone. "
            "The vault ref is marked revoked. Delete the token in the ntfy "
            "account UI (account API was not configured)."
        ),
        fix_action="Delete the target's ntfy publish token in the ntfy account.",
    )

"""server-watch.sh handoff when Hub-side probing goes live (D-036).

Remove the host cron, revoke (or mark) the per-target publish token, bump
the catalog entry — never a silent mutation of a released version.
"""
from __future__ import annotations

import pytest

from core.transport import FakeTransport

pytestmark = [pytest.mark.django_db, pytest.mark.req("ALERT-M3-PAGER-AUTH")]


def _target(host="10.0.0.8"):
    from core.models import NetworkZone, Target

    slug = "lan-watch-" + host.replace(".", "-")
    zone = NetworkZone.objects.create(name="lan-watch", slug=slug)
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=host,
        ssh_user="deploy",
        ssh_key_ref="vault-owner-watch",
        host_key_fingerprint="SHA256:watch",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def _cron_transport():
    crontab = (
        "*/5 * * * * /usr/local/sbin/server-watch.sh >> /var/log/watch.log 2>&1\n"
        "17 4 * * 1 /usr/local/sbin/update-cloudflare-ufw.sh >> /var/log/cf-ufw.log 2>&1\n"
    )
    return FakeTransport(responses={"crontab": {"stdout": crontab}})


def test_cron_entry_removed_when_hub_probing_goes_live():
    """What would make this fail: leaving server-watch.sh on the host crontab
    after Hub-side probing is live."""
    from provision.service import handoff_hub_probing

    target = _target("watch-cron.example")
    transport = _cron_transport()
    handoff_hub_probing(target, transport)
    written = ""
    for path, body in transport.files.items():
        if "crontab" in path:
            written = body.decode() if isinstance(body, (bytes, bytearray)) else body
    assert "server-watch.sh" not in written
    assert "update-cloudflare-ufw.sh" in written
    runs = [payload for kind, payload in transport.calls if kind == "run"]
    assert any(payload[:1] == ["crontab"] for payload in runs)


def test_target_publish_token_is_revoked_or_marked_with_a_finding():
    """What would make this fail: a still-issuable target publish token and
    no P2 Finding carrying the manual revoke step."""
    from core.models import Finding
    from providers.ntfy import TokenRevoked, issue_publisher_token, publisher_ref
    from provision.service import handoff_hub_probing
    from vault.models import Secret

    target = _target("watch-token.example")
    identity = f"target:{target.pk}"
    issue_publisher_token(identity, b"target-publisher-token-XXXX-9999")
    assert Secret.objects.filter(
        owner_type="ntfy", owner_id=publisher_ref(identity),
    ).exists()

    handoff_hub_probing(target, _cron_transport())

    with pytest.raises(TokenRevoked):
        issue_publisher_token(identity, b"replacement-must-be-refused")

    # Unconfigured ntfy account API must file the manual-step Finding.
    assert Finding.objects.filter(
        fingerprint=f"ntfy-revoke:{target.pk}",
    ).exists()
    row = Finding.objects.get(fingerprint=f"ntfy-revoke:{target.pk}")
    assert row.severity == Finding.Severity.P2
    assert "ntfy" in (row.title + row.body + row.fix_action).lower()


def test_catalog_entry_version_bumped_not_mutated():
    """What would make this fail: rewriting an AppliedCatalogEntry in place,
    or changing check/fix/rollback on the released version without a bump."""
    from test_catalog import RELEASED

    from catalog.entries import ENTRIES
    from catalog.models import AppliedCatalogEntry
    from provision.service import handoff_hub_probing

    entry = ENTRIES["server-watch-handoff"]
    pin = RELEASED["server-watch-handoff"]
    assert entry.version == pin["version"]
    assert entry.check == pin["check"]
    assert entry.fix == pin["fix"]
    assert entry.rollback == pin["rollback"]

    target = _target("watch-catalog.example")
    handoff_hub_probing(target, _cron_transport())
    first = AppliedCatalogEntry.objects.get(
        target=target, entry_id="server-watch-handoff",
    )
    version, result, mode = first.version, first.result, first.mode
    assert first.version == entry.version

    handoff_hub_probing(target, _cron_transport())
    first.refresh_from_db()
    assert first.version == version
    assert first.result == result
    assert first.mode == mode
    assert (
        AppliedCatalogEntry.objects.filter(
            target=target, entry_id="server-watch-handoff",
        ).count()
        == 2
    )

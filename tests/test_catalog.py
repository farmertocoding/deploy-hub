"""Catalog dataclasses + apply_entry (HARD-R1, §D8, D-018 probe-then-skip)."""
import pytest

from core.transport import FakeTransport

# D8 pin: (id, version) owns these argv lists. Change check/fix/rollback ⇒ bump
# version in catalog/entries.py *and* here. Do not edit a released version in place.
RELEASED = {
    "ntp-chrony": {
        "version": 1,
        "check": ["systemctl", "is-active", "chrony"],
        "fix": ["apt-get", "install", "-y", "chrony"],
        "rollback": ["systemctl", "disable", "--now", "chrony"],
    },
    "log-rotation": {
        "version": 2,
        "check": ["test", "-f", "/etc/logrotate.d/caddy"],
        "fix": [
            "install", "-m", "0644",
            "/usr/local/share/hub-catalog/logrotate-caddy",
            "/etc/logrotate.d/caddy",
        ],
        "rollback": ["rm", "-f", "/etc/logrotate.d/caddy"],
    },
    "docker-daemon-json": {
        "version": 2,
        "check": ["test", "-f", "/etc/docker/daemon.json"],
        "fix": [
            "install", "-m", "0644",
            "/usr/local/share/hub-catalog/docker-daemon.json",
            "/etc/docker/daemon.json",
        ],
        "rollback": ["rm", "-f", "/etc/docker/daemon.json"],
    },
    "sshd-dropin": {
        "version": 2,
        "check": ["test", "-f", "/etc/ssh/sshd_config.d/99-hub-hardening.conf"],
        "fix": [
            "install", "-m", "0644",
            "/usr/local/share/hub-catalog/99-hub-hardening.conf",
            "/etc/ssh/sshd_config.d/99-hub-hardening.conf",
        ],
        "rollback": ["rm", "-f", "/etc/ssh/sshd_config.d/99-hub-hardening.conf"],
    },
    "ufw-posture-hub": {
        "version": 1,
        "check": ["ufw", "status", "verbose"],
        "fix": ["ufw", "allow", "in", "on", "tailscale0"],
        "rollback": ["ufw", "delete", "allow", "in", "on", "tailscale0"],
    },
    "ufw-posture-target": {
        "version": 1,
        "check": ["ufw", "status", "verbose"],
        "fix": [
            "ufw", "allow", "proto", "tcp", "from", "173.245.48.0/20",
            "to", "any", "port", "80", "443", "comment", "cloudflare-edge",
        ],
        "rollback": [
            "ufw", "delete", "allow", "proto", "tcp", "from", "173.245.48.0/20",
            "to", "any", "port", "80", "443",
        ],
    },
    "ufw-posture-intake": {
        "version": 1,
        "check": ["systemctl", "is-active", "cloudflared"],
        "fix": ["ufw", "allow", "in", "on", "tailscale0"],
        "rollback": ["ufw", "delete", "allow", "in", "on", "tailscale0"],
    },
    "fail2ban-ignoreip": {
        "version": 2,
        "check": ["fail2ban-client", "get", "sshd", "ignoreip"],
        "fix": ["systemctl", "enable", "--now", "fail2ban"],
        "rollback": ["systemctl", "disable", "--now", "fail2ban"],
    },
    "caddy": {
        "version": 1,
        "check": ["systemctl", "is-active", "caddy"],
        "fix": ["apt-get", "install", "-y", "caddy"],
        "rollback": ["systemctl", "disable", "--now", "caddy"],
    },
}

PUBLIC_PORTS = {"80", "443", "80/tcp", "443/tcp", "80,443"}


def _target():
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name="lan", slug="lan-catalog")
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref="vault-owner-1",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def test_entry_version_bump_is_required_for_semantics():
    """D8: live (id, version) argv must match the released pin.

    What would make this fail: changing check/fix/rollback on an entry
    without bumping version (silent semantics mutation).
    """
    from catalog.entries import CATALOG

    by_id = {e.id: e for e in CATALOG}
    assert set(by_id) == set(RELEASED)
    keys = [(e.id, e.version) for e in CATALOG]
    assert len(keys) == len(set(keys))
    for eid, pin in RELEASED.items():
        entry = by_id[eid]
        assert isinstance(entry.version, int)
        assert entry.version == pin["version"]
        assert entry.check == pin["check"]
        assert entry.fix == pin["fix"]
        assert entry.rollback == pin["rollback"]
        assert entry.os_variant == "ubuntu"


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.django_db
def test_apply_twice_zero_mutating_calls():
    """Same-version re-apply probes then skips; mutating_calls stay empty.

    What would make this fail: second apply calling run/put, or inspect via run.
    """
    from catalog.apply import apply_entry
    from catalog.entries import ENTRIES
    from catalog.models import AppliedCatalogEntry

    target = _target()
    entry = ENTRIES["ntp-chrony"]
    transport = FakeTransport()

    apply_entry(target, entry, transport)
    assert transport.mutating_calls() == [("run", list(entry.fix))]
    assert AppliedCatalogEntry.objects.filter(
        target=target, entry_id=entry.id, version=entry.version,
    ).count() == 1

    transport.calls.clear()
    apply_entry(target, entry, transport)
    assert transport.mutating_calls() == []
    assert transport.calls == [("probe", list(entry.check))]
    assert AppliedCatalogEntry.objects.filter(
        target=target, entry_id=entry.id,
    ).count() == 1


@pytest.mark.req("HARD-R1-TWO-POSTURES")
def test_hub_posture_has_no_public_80_443():
    """Hub argv never opens 80/443; mesh only.

    What would make this fail: hub fix/check allowing 80 or 443 to the public.
    """
    from catalog.entries import ENTRIES

    hub = ENTRIES["ufw-posture-hub"]
    tokens = hub.check + hub.fix + hub.rollback
    assert PUBLIC_PORTS.isdisjoint(tokens)
    assert "tailscale0" in hub.fix
    assert hub.fix != ENTRIES["ufw-posture-target"].fix
    assert hub.check != ENTRIES["ufw-posture-intake"].check


@pytest.mark.req("HARD-R1-TWO-POSTURES")
def test_target_posture_allows_80_443_from_cf_ranges_only():
    """Target 80/443 come from a Cloudflare range, never anywhere.

    What would make this fail: allow 80/443 without `from` + a CF CIDR, or
    opening those ports to 0.0.0.0/0 / anywhere.
    """
    from catalog.entries import ENTRIES

    target = ENTRIES["ufw-posture-target"]
    assert "80" in target.fix
    assert "443" in target.fix
    assert "from" in target.fix
    assert "173.245.48.0/20" in target.fix
    assert any("cloudflare" in t for t in target.fix)
    assert "anywhere" not in target.fix
    assert "0.0.0.0/0" not in target.fix
    assert "100.64.0.0/10" not in target.fix


@pytest.mark.req("HARD-R1-TWO-POSTURES")
def test_intake_posture_is_tunnel_no_public_inbound():
    """Intake is tunnel-published with no public inbound ports.

    What would make this fail: intake opening 80/443, or omitting the tunnel.
    """
    from catalog.entries import ENTRIES

    intake = ENTRIES["ufw-posture-intake"]
    tokens = intake.check + intake.fix + intake.rollback
    assert PUBLIC_PORTS.isdisjoint(tokens)
    assert "cloudflared" in tokens or any("tunnel" in t for t in tokens)
    assert "tailscale0" in intake.fix
    hub = ENTRIES["ufw-posture-hub"]
    target = ENTRIES["ufw-posture-target"]
    assert (intake.check, intake.fix) != (hub.check, hub.fix)
    assert (intake.check, intake.fix) != (target.check, target.fix)


def test_fix_and_check_are_argv_lists():
    """check/fix/rollback are argv lists, never interpolated shell strings.

    What would make this fail: a string command, or a one-element list whose
    only item is a spaced shell string.
    """
    from catalog.entries import CATALOG

    for entry in CATALOG:
        for field in (entry.check, entry.fix, entry.rollback):
            assert isinstance(field, list)
            assert field
            assert all(isinstance(part, str) for part in field)
            assert not (len(field) == 1 and " " in field[0])

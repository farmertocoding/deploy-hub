"""Provisioner fresh-host guard (PROV-E6). Occupied 80/443 or site containers refuse."""
import pytest

from core.transport import FakeTransport

pytestmark = pytest.mark.django_db


def _target():
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name="lan", slug="lan-prov")
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


def _ss(stdout):
    return FakeTransport(responses={"ss": {"stdout": stdout}})


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_occupied_80_refuses_with_explanation():
    """Port 80 occupied must refuse with an operator-readable explanation.

    What would make this fail: proceeding anyway, or a refusal with no mention of 80.
    """
    from provision.service import provision_host

    transport = _ss("LISTEN 0 4096 0.0.0.0:80 0.0.0.0:*\n")
    result = provision_host(_target(), transport)
    assert result.allowed is False
    assert "80" in result.explanation
    assert "occupied" in result.explanation.lower()


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_occupied_443_refuses():
    """Port 443 occupied must refuse. :4430 / :8080 are not 443 / 80.

    What would make this fail: treating 443 as free, or matching 8080 as 80.
    """
    from provision.service import provision_host

    transport = _ss(
        "LISTEN 0 4096 0.0.0.0:443 0.0.0.0:*\n"
        "LISTEN 0 4096 127.0.0.1:8080 0.0.0.0:*\n"
    )
    result = provision_host(_target(), transport)
    assert result.allowed is False
    assert "443" in result.explanation
    assert "80" not in result.explanation.replace("443", "")


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_site_container_present_refuses():
    """A site container on an otherwise empty-port host is non-fresh and refuses.

    What would make this fail: ignoring docker ps names, or treating them as allowed.
    """
    from provision.service import provision_host

    transport = FakeTransport(responses={"docker": {"stdout": "takko-web\n"}})
    result = provision_host(_target(), transport)
    assert result.allowed is False
    assert "takko-web" in result.explanation
    assert "container" in result.explanation.lower()


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_pre_hardened_empty_host_is_allowed_and_imports_catalog_versions():
    """Scripts already applied, ports free, no site containers: import catalog versions.

    What would make this fail: refusing the empty host, skipping AppliedCatalogEntry,
    running catalog fix, or leaving a live-Beat script cron in place.
    """
    from catalog.models import AppliedCatalogEntry
    from provision.service import provision_host

    crontab = "17 4 * * 1 /usr/local/sbin/update-cloudflare-ufw.sh >> /var/log/cf-ufw.log 2>&1\n"
    transport = FakeTransport(responses={"crontab": {"stdout": crontab}})
    target = _target()
    result = provision_host(
        target,
        transport,
        live_beat_jobs=["update-cloudflare-ufw.sh"],
    )
    assert result.allowed is True
    rows = {
        row.entry_id: row.version
        for row in AppliedCatalogEntry.objects.filter(target=target)
    }
    assert rows == {
        "ntp-chrony": 1,
        "log-rotation": 2,
        "docker-daemon-json": 2,
        "sshd-dropin": 4,
        "ufw-posture-target": 1,
        "fail2ban-ignoreip": 5,
        "caddy": 1,
        "caddy-log-roll": 1,
    }
    assert "ufw-posture-hub" not in rows
    assert "ufw-posture-intake" not in rows
    assert all(row.mode == "import" for row in AppliedCatalogEntry.objects.all())
    runs = [payload for kind, payload in transport.calls if kind == "run"]
    assert ["crontab", "/home/deploy/.hub/crontab"] in runs
    assert not any(payload[:1] == ["apt-get"] for payload in runs)


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_does_not_proceed_on_refuse():
    """Refuse is the last act: no run/put and no AppliedCatalogEntry after occupied 80.

    What would make this fail: a mutating Transport call, or writing catalog history,
    after the guard has already decided to refuse.
    """
    from catalog.models import AppliedCatalogEntry
    from provision.service import provision_host

    transport = _ss("LISTEN 0 4096 [::]:80 [::]:*\n")
    result = provision_host(_target(), transport)
    assert result.allowed is False
    assert transport.mutating_calls() == []
    assert AppliedCatalogEntry.objects.count() == 0
    assert all(kind == "probe" for kind, _ in transport.calls)


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_failed_ss_probe_refuses():
    """A red ss probe is not “ports free”; refuse and do not mutate.

    What would make this fail: treating exit_code != 0 + empty stdout as vacant 80/443.
    """
    from catalog.models import AppliedCatalogEntry
    from provision.service import provision_host

    transport = FakeTransport(responses={"ss": {"exit_code": 1, "stderr": "ss: not found"}})
    result = provision_host(_target(), transport)
    assert result.allowed is False
    assert "ss" in result.explanation.lower() or "port" in result.explanation.lower()
    assert transport.mutating_calls() == []
    assert AppliedCatalogEntry.objects.count() == 0


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_failed_docker_probe_refuses():
    """A red docker probe is not “no site containers”; refuse and do not mutate.

    What would make this fail: proceeding to import after docker ps fails.
    """
    from catalog.models import AppliedCatalogEntry
    from provision.service import provision_host

    transport = FakeTransport(responses={"docker": {"exit_code": 1, "stderr": "cannot connect"}})
    result = provision_host(_target(), transport)
    assert result.allowed is False
    assert "container" in result.explanation.lower() or "docker" in result.explanation.lower()
    assert transport.mutating_calls() == []
    assert AppliedCatalogEntry.objects.count() == 0


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_failed_verify_imports_nothing():
    """verify-hardening.sh not ok must not stamp the host as fully applied.

    What would make this fail: writing AppliedCatalogEntry after a red verify probe.
    """
    from catalog.models import AppliedCatalogEntry
    from provision.service import provision_host

    target = _target()
    transport = FakeTransport(responses={"env": {"exit_code": 1}})
    result = provision_host(target, transport)
    assert result.allowed is True
    assert AppliedCatalogEntry.objects.filter(target=target).count() == 0


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_failed_check_is_not_imported():
    """A red catalog check must not write that id (and never as ok: True).

    grep is unique to fail2ban-ignoreip. What would make this fail: importing it
    anyway, or writing result.ok True for the failed probe.
    """
    from catalog.models import AppliedCatalogEntry
    from provision.service import provision_host

    target = _target()
    transport = FakeTransport(responses={"grep": {"exit_code": 1}})
    result = provision_host(target, transport)
    assert result.allowed is True
    rows = list(AppliedCatalogEntry.objects.filter(target=target))
    ids = {row.entry_id for row in rows}
    assert "fail2ban-ignoreip" not in ids
    assert "ntp-chrony" in ids
    assert all(row.result.get("ok") is True for row in rows)


@pytest.mark.req("PROV-E6-FRESH-HOST-GUARD")
def test_hub_profile_imports_only_hub_ufw():
    """Only this host’s ufw posture id is imported.

    What would make this fail: writing target/intake ufw rows on a hub profile.
    """
    from catalog.models import AppliedCatalogEntry
    from provision.service import provision_host

    target = _target()
    result = provision_host(target, FakeTransport(), profile="hub")
    assert result.allowed is True
    ids = set(
        AppliedCatalogEntry.objects.filter(target=target).values_list("entry_id", flat=True)
    )
    assert "ufw-posture-hub" in ids
    assert "ufw-posture-target" not in ids
    assert "ufw-posture-intake" not in ids

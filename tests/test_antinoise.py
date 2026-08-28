"""Anti-noise engine (D-038): hysteresis, flap, suppression, grouping, storm.

Named tests from Task 6. Delivery (ntfy) is Task 7 — these assert the
engine's decisions (open/close, suppress, group, storm, recovery, ack).
"""
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from core.models import AlertState, Finding

pytestmark = pytest.mark.django_db

COPY = dict(
    title="alert title",
    body="why this matters to the operator",
    fix_action="do the named fix",
)


def _copy(**overrides):
    from core.models import default_workspace

    fields = dict(COPY)
    fields.setdefault("workspace", default_workspace())
    fields.update(overrides)
    return fields


def _fail_until_open(fingerprint, n=3):
    from monitor.antinoise import observe

    row = None
    for _ in range(n):
        row = observe(fingerprint, False)
    return row


def _shared_host_sites():
    from dns_fixtures import default_dns_zone

    from core.models import NetworkZone, Project, Site, Target

    project, _ = Project.objects.get_or_create(
        slug="antinoise-proj",
        defaults={"name": "antinoise", "git_url": "https://example.com/repo.git"},
    )
    zone, _ = NetworkZone.objects.get_or_create(
        slug="antinoise-net", defaults={"name": "antinoise-net"},
    )
    target = Target.objects.create(
        zone=zone, host="box.antinoise.example", status=Target.Status.READY,
    )
    dns = default_dns_zone()
    sites = [
        Site.objects.create(
            project=project,
            name=name,
            domain=f"{name}.antinoise.example",
            primary_target=target,
            dns_zone=dns,
        )
        for name in ("alpha", "beta")
    ]
    return target, sites


def _zone_with_hosts():
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name="antinoise-zone", slug="antinoise-zone")
    hosts = [
        Target.objects.create(
            zone=zone, host=host, status=Target.Status.READY,
        )
        for host in ("h1.antinoise.example", "h2.antinoise.example")
    ]
    return zone, hosts


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_two_failures_do_not_open():
    """What would make this fail: alerting on the first or second failed probe."""
    from monitor.antinoise import observe

    fp = "site-down:two-fail"
    assert observe(fp, False) is None
    assert observe(fp, False) is None
    state = AlertState.objects.get(fingerprint=fp)
    assert state.opened_at is None
    assert not Finding.objects.filter(fingerprint=fp).exists()


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_third_consecutive_failure_opens():
    """What would make this fail: needing a fourth fail, or opening without a Finding."""
    from monitor.antinoise import observe

    fp = "site-down:three-fail"
    assert observe(fp, False) is None
    assert observe(fp, False) is None
    row = observe(fp, False)
    assert row is not None
    assert row.fingerprint == fp
    assert row.state == Finding.State.OPEN
    state = AlertState.objects.get(fingerprint=fp)
    assert state.opened_at is not None
    assert state.consecutive_fail == 3


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_one_success_does_not_close():
    """What would make this fail: closing (or resolving) on a single success."""
    from monitor.antinoise import observe

    fp = "site-down:one-ok"
    _fail_until_open(fp)
    observe(fp, True)
    state = AlertState.objects.get(fingerprint=fp)
    assert state.opened_at is not None
    assert state.closed_at is None
    assert Finding.objects.get(fingerprint=fp).state == Finding.State.OPEN


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
@pytest.mark.req("ALERT-RECOVERY-NOTICE")
def test_two_consecutive_successes_close_and_send_recovery():
    """What would make this fail: closing without the UP-after notice, or
    leaving the Finding open after two successes."""
    from monitor.antinoise import observe

    fp = "site-down:recover"
    _fail_until_open(fp)
    observe(fp, True)
    notice = observe(fp, True)
    assert notice["title"].startswith("UP after")
    state = AlertState.objects.get(fingerprint=fp)
    assert state.closed_at is not None
    assert Finding.objects.get(fingerprint=fp).state == Finding.State.RESOLVED


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_three_cycles_in_thirty_minutes_collapse_to_one_flapping_p2():
    """What would make this fail: emitting a fourth individual open, or no
    FLAPPING P2 after three open/close cycles."""
    from monitor.antinoise import observe

    fp = "site-down:flappy"

    def cycle():
        _fail_until_open(fp)
        observe(fp, True)
        observe(fp, True)

    cycle()
    cycle()
    cycle()
    flaps = list(Finding.objects.filter(title="FLAPPING"))
    assert len(flaps) == 1
    assert flaps[0].severity == "p2"

    _fail_until_open(fp)
    site = Finding.objects.get(fingerprint=fp)
    assert site.state == Finding.State.RESOLVED


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_host_down_suppresses_its_sites_and_names_them():
    """What would make this fail: a site-down Finding beside the host, or a
    host alert that does not name the suppressed sites."""
    from monitor.antinoise import observe, suppressed_by

    target, sites = _shared_host_sites()
    fp = f"host-down:{target.host}"
    row = _fail_until_open(fp)
    assert row is not None
    for site in sites:
        assert f"site:{site.name}" in row.body
        assert suppressed_by(f"site:{site.name}") == f"host:{target.host}"

    observe("site-down:alpha", False)
    observe("site-down:alpha", False)
    observe("site-down:alpha", False)
    assert not Finding.objects.filter(fingerprint="site-down:alpha").exists()


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_zone_down_suppresses_its_hosts():
    """What would make this fail: a host-down Finding beside the zone, or a
    zone alert that does not name the suppressed hosts."""
    from monitor.antinoise import observe, suppressed_by

    zone, hosts = _zone_with_hosts()
    fp = f"zone-down:{zone.slug}"
    row = _fail_until_open(fp)
    assert row is not None
    for host in hosts:
        assert f"host:{host.host}" in row.body
        assert suppressed_by(f"host:{host.host}") == f"zone:{zone.slug}"

    host_fp = f"host-down:{hosts[0].host}"
    observe(host_fp, False)
    observe(host_fp, False)
    observe(host_fp, False)
    assert not Finding.objects.filter(fingerprint=host_fp).exists()


def test_two_p2_within_ten_minutes_become_one_grouped_push():
    """What would make this fail: two separate P2 pushes, or dropping one."""
    from monitor.alerts import raise_alert
    from monitor.antinoise import group_p2

    raise_alert("feed-data-stale", "feed:a", fingerprint="stale:a", **_copy())
    raise_alert("feed-data-stale", "feed:b", fingerprint="stale:b", **_copy())
    pushes = group_p2(window=600)
    assert len(pushes) == 1
    assert pushes[0]["grouped"] is True
    fps = {finding.fingerprint for finding in pushes[0]["findings"]}
    assert fps == {"stale:a", "stale:b"}


def test_a_single_p2_is_not_delayed_by_grouping():
    """What would make this fail: holding a lone P2 for the 10-minute window."""
    from monitor.alerts import raise_alert
    from monitor.antinoise import group_p2

    raise_alert("feed-data-stale", "feed:solo", fingerprint="stale:solo", **_copy())
    pushes = group_p2(window=600)
    assert len(pushes) == 1
    assert pushes[0]["grouped"] is False
    assert [finding.fingerprint for finding in pushes[0]["findings"]] == ["stale:solo"]


@pytest.mark.req("ALERT-RECOVERY-NOTICE")
def test_ack_stops_repeats_but_keeps_the_finding_open():
    """What would make this fail: ack resolving the Finding, or a repeat push."""
    from core.findings import ack
    from monitor.antinoise import after_raise

    fp = "site-down:acked"
    row = _fail_until_open(fp)
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    assert row.state != Finding.State.RESOLVED

    state = AlertState.objects.get(fingerprint=fp)
    pushed_at = state.last_push_at
    again = after_raise(row)
    assert again.state == Finding.State.ACKED
    assert again.will_push is False
    state.refresh_from_db()
    assert state.last_push_at == pushed_at


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_eleventh_push_in_ten_minutes_becomes_one_storm_alert():
    """What would make this fail: an 11th individual push, or no ALERT STORM P1."""
    from monitor.alerts import raise_alert

    for i in range(11):
        raise_alert(
            "disk-critical",
            f"host:storm-{i}",
            fingerprint=f"disk-storm:{i}",
            **_copy(),
        )
    storm = Finding.objects.get(fingerprint="alert-storm")
    assert storm.severity == "p1"
    assert "ALERT STORM" in storm.title
    assert "11" in storm.title


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_storm_mode_exits_when_the_rate_drops():
    """What would make this fail: staying in storm after the 10-minute rate drops."""
    from monitor.alerts import raise_alert
    from monitor.antinoise import storm_breaker

    for i in range(11):
        raise_alert(
            "disk-critical",
            f"host:storm-exit-{i}",
            fingerprint=f"disk-storm-exit:{i}",
            **_copy(),
        )
    state = AlertState.objects.get(fingerprint="__storm__")
    assert state.opened_at is not None
    assert state.closed_at is None

    storm_breaker(timezone.now() + timedelta(minutes=11))
    state.refresh_from_db()
    assert state.closed_at is not None


def test_p1_ignores_quiet_hours():
    """What would make this fail: a P1 that respects quiet hours or uses
    default (OS night-mode) priority."""
    from monitor.alerts import raise_alert

    row = raise_alert(
        "prod-site-hard-down",
        "site:night",
        fingerprint="site-down:night",
        **_copy(),
    )
    assert row.respects_quiet_hours is False
    assert row.push_priority == "max"


def _recovery_for(fingerprint):
    log = AlertState.objects.filter(fingerprint="__pushes__").first()
    if log is None:
        return []
    return [
        event.get("title", "")
        for event in (log.transitions or [])
        if event.get("fingerprint") == fingerprint
        and str(event.get("title", "")).startswith("UP after")
    ]


def _age_push_log(minutes=11):
    log = AlertState.objects.get(fingerprint="__pushes__")
    past = (timezone.now() - timedelta(minutes=minutes)).isoformat()
    for event in log.transitions or []:
        event["at"] = past
    log.save(update_fields=["transitions"])


def _age_n_recent_pushes(n, minutes=11):
    """Age the oldest n still-in-window pushes out of the storm window."""
    from monitor.antinoise import STORM_WINDOW

    log = AlertState.objects.get(fingerprint="__pushes__")
    now = timezone.now()
    past = (now - timedelta(minutes=minutes)).isoformat()
    aged = 0
    for event in log.transitions or []:
        if aged >= n:
            break
        if event.get("counts_for_storm") is False:
            continue
        at = datetime.fromisoformat(event["at"])
        if timezone.is_naive(at):
            at = timezone.make_aware(at, timezone.get_current_timezone())
        if now - at <= STORM_WINDOW:
            event["at"] = past
            aged += 1
    log.save(update_fields=["transitions"])


def _non_prod_site():
    from dns_fixtures import default_dns_zone

    from core.models import NetworkZone, Project, Site, Target

    project, _ = Project.objects.get_or_create(
        slug="antinoise-staging",
        defaults={"name": "antinoise-staging", "git_url": "https://example.com/s.git"},
    )
    zone, _ = NetworkZone.objects.get_or_create(
        slug="antinoise-test-net",
        defaults={"name": "antinoise-test-net", "purpose": NetworkZone.Purpose.TEST},
    )
    if zone.purpose != NetworkZone.Purpose.TEST:
        zone.purpose = NetworkZone.Purpose.TEST
        zone.save(update_fields=["purpose"])
    target = Target.objects.create(
        zone=zone, host="box.staging.antinoise.example", status=Target.Status.READY,
    )
    site = Site.objects.create(
        project=project,
        name="staging-web",
        domain="staging-web.antinoise.example",
        primary_target=target,
        dns_zone=default_dns_zone(name="staging.antinoise.example", purpose="test"),
    )
    return site


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_later_p1_after_storm_window_will_push():
    """What would make this fail: an open __storm__ latch still muting a
    real P1 after the 10-minute rate has dropped."""
    from monitor.alerts import raise_alert

    for i in range(11):
        raise_alert(
            "disk-critical",
            f"host:storm-later-{i}",
            fingerprint=f"disk-storm-later:{i}",
            **_copy(),
        )
    storm = Finding.objects.get(fingerprint="alert-storm")
    assert storm.state == Finding.State.OPEN

    _age_push_log(11)
    later = raise_alert(
        "ssh-host-key-mismatch",
        "host:real",
        fingerprint="ssh-host-key-mismatch:host:real",
        **_copy(),
    )
    assert later.will_push is True
    storm.refresh_from_db()
    assert storm.state == Finding.State.RESOLVED
    assert _recovery_for("alert-storm")


@pytest.mark.req("ALERT-RECOVERY-NOTICE")
def test_storm_finding_resolves_with_recovery_when_rate_drops():
    """What would make this fail: closing __storm__ while alert-storm stays
    OPEN and never sending UP after."""
    from monitor.alerts import raise_alert
    from monitor.antinoise import storm_breaker

    for i in range(11):
        raise_alert(
            "disk-critical",
            f"host:storm-recover-{i}",
            fingerprint=f"disk-storm-recover:{i}",
            **_copy(),
        )
    storm_breaker(timezone.now() + timedelta(minutes=11))
    storm = Finding.objects.get(fingerprint="alert-storm")
    assert storm.state == Finding.State.RESOLVED
    assert _recovery_for("alert-storm")


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
@pytest.mark.req("ALERT-RECOVERY-NOTICE")
def test_flapping_finding_resolves_with_recovery_when_stable():
    """What would make this fail: FLAPPING staying OPEN after 30 minutes
    stable, or closing it without the recovery notice."""
    from monitor.antinoise import observe

    fp = "site-down:flappy-resolve"

    def cycle():
        _fail_until_open(fp)
        observe(fp, True)
        observe(fp, True)

    cycle()
    cycle()
    cycle()
    flap = Finding.objects.get(title="FLAPPING")
    assert flap.state == Finding.State.OPEN

    later = timezone.now() + timedelta(minutes=31)
    observe(fp, True, now=later)
    flap.refresh_from_db()
    assert flap.state == Finding.State.RESOLVED
    assert _recovery_for(flap.fingerprint)


def test_non_prod_site_down_does_not_file_prod_site_hard_down():
    """What would make this fail: a test-zone / staging site opening as the
    prod-site-hard-down P1 row."""
    from unittest.mock import patch

    import monitor.antinoise as antinoise

    site = _non_prod_site()
    with patch.object(
        antinoise, "raise_alert", wraps=antinoise.raise_alert,
    ) as spy:
        row = _fail_until_open(f"site-down:{site.name}")
    kinds = [call.args[0] for call in spy.call_args_list if call.args]
    assert row is not None
    assert row.severity == Finding.Severity.P2
    assert "prod-site-hard-down" not in kinds
    assert "staging-or-flapping" in kinds


@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
@pytest.mark.req("ALERT-RECOVERY-NOTICE")
def test_storm_exit_at_exactly_ten_does_not_reopen_on_recovery():
    """What would make this fail: rate 11→10 closing the storm, then the
    recovery notice counting as the 11th push, reopening alert-storm, and
    muting a later real P1."""
    from monitor.alerts import raise_alert
    from monitor.antinoise import storm_breaker

    for i in range(11):
        raise_alert(
            "disk-critical",
            f"host:storm-edge-{i}",
            fingerprint=f"disk-storm-edge:{i}",
            **_copy(),
        )
    storm = Finding.objects.get(fingerprint="alert-storm")
    assert storm.state == Finding.State.OPEN

    _age_n_recent_pushes(1)
    storm_breaker(timezone.now())
    storm.refresh_from_db()
    assert storm.state == Finding.State.RESOLVED
    assert _recovery_for("alert-storm")
    state = AlertState.objects.get(fingerprint="__storm__")
    assert state.closed_at is not None

    # Keep the later P1 from being the 11th page in the window. Recovery
    # already left the rate at 10; one more original push ages out.
    _age_n_recent_pushes(1)
    later = raise_alert(
        "ssh-host-key-mismatch",
        "host:real-edge",
        fingerprint="ssh-host-key-mismatch:host:real-edge",
        **_copy(),
    )
    assert later.will_push is True
    storm.refresh_from_db()
    assert storm.state == Finding.State.RESOLVED

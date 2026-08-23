"""CheckRun writers, missed-drill query, and Beat drill job bodies."""
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from core.models import BackupUnit, CheckRun, Site, Target
from monitor.uptime import http_probe, probe_url

RESULTS_SCHEMA_VERSION = 1
_MAX_HUB_DOWN_S = 86400
_TERMINAL = (CheckRun.Status.SUCCEEDED, CheckRun.Status.FAILED)
_RESTORE_SITELESS = "siteless"
_NO_ELIGIBLE_SITE = "no eligible site"
_HUB_NOT_STOPPED = "hub-not-stopped"
_DEFAULT_PROBER = object()

DRILL_PERIODS = {
    CheckRun.Kind.HUB_DOWN: 30 * 86400,
    CheckRun.Kind.REAPER: 7 * 86400,
    CheckRun.Kind.RESTORE_CLEAN: 30 * 86400,
    CheckRun.Kind.PAGER: 30 * 86400,
}


class DrillConfigurationError(RuntimeError):
    """A live site exists but no site_prober was configured."""


def record_run(kind, status, results=None, *, due_at=None):
    """Persist one CheckRun. ``results is None`` becomes a versioned empty payload."""
    now = timezone.now()
    if results is None:
        results = {"schema_version": RESULTS_SCHEMA_VERSION}
    started = None
    finished = None
    if status in (
        CheckRun.Status.RUNNING,
        CheckRun.Status.SUCCEEDED,
        CheckRun.Status.FAILED,
        CheckRun.Status.SKIPPED,
    ):
        started = now
    if status in _TERMINAL + (CheckRun.Status.SKIPPED,):
        finished = now
    return CheckRun.objects.create(
        kind=kind,
        status=status,
        results=results,
        due_at=due_at,
        started=started,
        finished=finished,
    )


def find_missed(now):
    """Kinds whose latest due_at is past and have no succeeded/failed row after it."""
    missed = []
    for kind in CheckRun.Kind.values:
        latest = (
            CheckRun.objects.filter(kind=kind, due_at__isnull=False)
            .order_by("-due_at", "-pk")
            .first()
        )
        if latest is None or latest.due_at >= now:
            continue
        if latest.status in _TERMINAL:
            continue
        covered = CheckRun.objects.filter(kind=kind, status__in=_TERMINAL).filter(
            Q(finished__gte=latest.due_at) | Q(started__gte=latest.due_at)
        ).exists()
        if not covered:
            missed.append(kind)
    return missed


def seed_due_at(kind, *, period_s, now=None):
    """Write or refresh the scheduled CheckRun so find_missed has a due_at."""
    clock = now or timezone.now()
    due = clock + timedelta(seconds=period_s)
    existing = (
        CheckRun.objects.filter(kind=kind, status=CheckRun.Status.SCHEDULED)
        .order_by("-due_at", "-pk")
        .first()
    )
    if existing is None:
        return record_run(kind, CheckRun.Status.SCHEDULED, due_at=due)
    existing.due_at = due
    existing.save(update_fields=["due_at"])
    return existing


def nightly_exit_code(run):
    """SKIPPED (no live site) and SUCCEEDED are nightly-green."""
    if run.status in (CheckRun.Status.SKIPPED, CheckRun.Status.SUCCEEDED):
        return 0
    return 1


def _eligible_site():
    return (
        Site.objects.filter(primary_target__status=Target.Status.READY)
        .select_related("primary_target")
        .order_by("pk")
        .first()
    )


def _build_default_site_prober():
    """External HTTP GET of a live Site + target — not a Hub-internal call."""
    site = _eligible_site()
    if site is None:
        return None
    url, host = probe_url(site)

    def _probe():
        status = http_probe(url, host=host)
        return status is not None and 200 <= int(status) < 400

    return _probe


def _skip_no_eligible_site(duration_s):
    from monitor.alerts import raise_alert

    raise_alert(
        "drill-missed",
        "check:hub_down",
        fingerprint="drill-missed:hub_down:no-eligible-site",
        source_engine="monitor.drills",
        title="Hub-down drill skipped: no eligible site",
        body=(
            "No Site with a READY primary target exists. The hub-down "
            "drill cannot issue an external GET; this is the ordinary "
            "state between T3 sessions, not a crash and not a fake green."
        ),
        fix_action="Provision a live site or wait for the next T3 session.",
    )
    return record_run(
        CheckRun.Kind.HUB_DOWN,
        CheckRun.Status.SKIPPED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "duration_s": duration_s,
            "reason": _NO_ELIGIBLE_SITE,
        },
    )


def _noop_hub():
    """Default stop/start: no-op. Identity is how we detect an unstopped Hub."""
    return None


def _is_default_hub_stopper(stop_hub):
    return stop_hub is None or stop_hub is _noop_hub


def _fail_hub_not_stopped(duration_s):
    from monitor.alerts import raise_alert

    raise_alert(
        "drill-missed",
        "check:hub_down",
        fingerprint="drill-missed:hub_down:hub-not-stopped",
        source_engine="monitor.drills",
        title="Hub-down drill did not stop Hub workers",
        body=(
            "Default stop_hub is a no-op. SUCCEEDED would mean the site "
            "answered while Hub-side workers were down; a no-op stop is "
            "not that."
        ),
        fix_action=(
            "Inject a real stop_hub/start_hub that takes Hub-side workers "
            "down for the probe window."
        ),
    )
    return record_run(
        CheckRun.Kind.HUB_DOWN,
        CheckRun.Status.FAILED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "duration_s": duration_s,
            "reason": _HUB_NOT_STOPPED,
        },
    )


def run_hub_down_drill(
    *,
    duration_s=60,
    site_prober=_DEFAULT_PROBER,
    stop_hub=None,
    start_hub=None,
):
    """Stop Hub-side workers, probe the site, write kind=hub_down. Never claims 24h."""
    if duration_s >= _MAX_HUB_DOWN_S:
        raise ValueError("hub_down duration_s must be < 86400; 24h stays waived")
    if site_prober is _DEFAULT_PROBER:
        site_prober = _build_default_site_prober()
        if site_prober is None:
            return _skip_no_eligible_site(duration_s)
    elif site_prober is None:
        if _eligible_site() is not None:
            raise DrillConfigurationError(
                "site_prober is required when a live site exists"
            )
        return _skip_no_eligible_site(duration_s)
    stop = stop_hub if stop_hub is not None else _noop_hub
    start = start_hub if start_hub is not None else _noop_hub
    stop()
    try:
        serving = bool(site_prober())
    except Exception:
        serving = False
    finally:
        start()
    if _is_default_hub_stopper(stop_hub):
        return _fail_hub_not_stopped(duration_s)
    return record_run(
        CheckRun.Kind.HUB_DOWN,
        CheckRun.Status.SUCCEEDED if serving else CheckRun.Status.FAILED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "duration_s": duration_s,
        },
    )


def run_reaper_drill(*, list_fn=None, delete_fn=None, planted_name="hub-t3-orphan-weekly"):
    """Call reap_test_plane against a planted hub-t3-orphan-* name."""
    from monitor.reaper import (
        ReaperUnavailable,
        delete_purge,
        list_names,
        multipass_available,
        reap_test_plane,
    )

    injected = list_fn is not None and delete_fn is not None
    if not injected:
        if not getattr(settings, "HUB_TEST_MODE", False) or not multipass_available():
            return record_run(
                CheckRun.Kind.REAPER,
                CheckRun.Status.SKIPPED,
                {
                    "schema_version": RESULTS_SCHEMA_VERSION,
                    "stub": True,
                    "reason": "not a test plane or multipass absent",
                },
            )
        list_fn = list_fn or list_names
        delete_fn = delete_fn or delete_purge

    names = list(list_fn())
    if planted_name not in names:
        names.append(planted_name)
    deleted = []

    def _delete(name):
        deleted.append(name)
        delete_fn(name)

    try:
        reap_test_plane(list_fn=lambda: names, delete_fn=_delete)
    except ReaperUnavailable:
        return record_run(
            CheckRun.Kind.REAPER,
            CheckRun.Status.SKIPPED,
            {
                "schema_version": RESULTS_SCHEMA_VERSION,
                "stub": True,
                "reason": "not a test plane or multipass absent",
            },
        )
    removed = planted_name in deleted
    return record_run(
        CheckRun.Kind.REAPER,
        CheckRun.Status.SUCCEEDED if removed else CheckRun.Status.FAILED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "planted_name": planted_name,
            "deleted": deleted,
        },
    )


def run_partner_reaper_drill(*, transport=None):
    """Plant a Fake orphaned partner site, reap, assert gone, persist PARTNER_REAPER.

    Do not fold this into drill-reaper-weekly / DRILL_PERIODS[REAPER].
    """
    from core.transport import FakeTransport
    from monitor.partner_reaper import plant_orphan, reap_orphans

    fake = transport or FakeTransport()
    planted = plant_orphan(transport=fake, reason="partner-gone")
    reap_orphans(transport=fake)
    name = planted["container"]
    gone = any(
        call[0] == "run" and call[1][:3] == ["docker", "stop", name]
        for call in fake.calls
    )
    return record_run(
        CheckRun.Kind.PARTNER_REAPER,
        CheckRun.Status.SUCCEEDED if gone else CheckRun.Status.FAILED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "planted_container": name,
            "gone": gone,
        },
    )


def run_aws_reaper_drill(
    *,
    provider=None,
    account_id="123456789012",
    region_name="us-east-1",
):
    """Plant a Fake purpose=test instance, reap, assert gone, persist AWS_REAPER."""
    from monitor.cloud_reaper import reap_cloud_test_plane
    from providers.fakes import FakeCloudProvider

    fake = provider or FakeCloudProvider()
    planted = fake.create_instance(
        {
            "name": "hub-aws-orphan-weekly",
            "tags": {"purpose": "test", "Name": "hub-aws-orphan-weekly"},
        }
    )
    planted_id = planted["id"]
    run = reap_cloud_test_plane(
        fake, account_id=account_id, region_name=region_name,
    )
    gone = fake.get_instance(planted_id) is None
    results = dict(run.results or {})
    results["schema_version"] = RESULTS_SCHEMA_VERSION
    results["planted_id"] = planted_id
    results["gone"] = gone
    run.results = results
    run.status = (
        CheckRun.Status.SUCCEEDED if gone else CheckRun.Status.FAILED
    )
    run.save(update_fields=["status", "results"])
    return run


def run_restore_clean_drill(*, restore_to_clean=None):
    """Unseal the latest dump into a clean file. SKIPPED only when siteless."""
    unit = BackupUnit.objects.select_related("site").order_by("pk").first()
    if unit is None:
        return record_run(
            CheckRun.Kind.RESTORE_CLEAN,
            CheckRun.Status.SKIPPED,
            {
                "schema_version": RESULTS_SCHEMA_VERSION,
                "reason": _RESTORE_SITELESS,
            },
        )
    from provision.backup import latest_unsealed_dump

    restore = restore_to_clean or _restore_to_clean_container
    try:
        plaintext = latest_unsealed_dump(unit)
        ok = bool(restore(unit, plaintext))
    except Exception as exc:
        return record_run(
            CheckRun.Kind.RESTORE_CLEAN,
            CheckRun.Status.FAILED,
            {
                "schema_version": RESULTS_SCHEMA_VERSION,
                "unit_id": unit.pk,
                "error": type(exc).__name__,
            },
        )
    return record_run(
        CheckRun.Kind.RESTORE_CLEAN,
        CheckRun.Status.SUCCEEDED if ok else CheckRun.Status.FAILED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "unit_id": unit.pk,
        },
    )


def _restore_to_clean_container(unit, plaintext):
    """Materialize the unsealed dump off-live. Never the KEK, never a live volume."""
    import tempfile

    with tempfile.NamedTemporaryFile(prefix="hub-restore-clean-", delete=True) as dest:
        dest.write(plaintext)
        dest.flush()
        return len(plaintext) > 0


def run_pager_drill(*, now=None):
    """Synthetic P1 through deliver(). SUCCEEDED only when this run's real backend sent."""
    from core.models import AlertDelivery, Finding
    from monitor.alerts import raise_alert

    clock = now or timezone.now()
    drill_start = timezone.now()
    backend = getattr(settings, "HUB_PAGER_BACKEND", "fake")
    period = timezone.localtime(clock).strftime("%Y-%m")
    fingerprint = f"pager-drill:{period}"
    raise_alert(
        "pager-drill",
        "check:pager",
        fingerprint=fingerprint,
        source_engine="monitor.drills",
        title="TEST — ack me",
        body=(
            "Monthly pager drill: a synthetic P1 to verify the whole "
            "path phone-deep. Ack this finding."
        ),
        fix_action="Ack this test finding in the Findings inbox.",
    )
    results = {"schema_version": RESULTS_SCHEMA_VERSION, "backend": backend}
    if backend == "fake":
        return record_run(CheckRun.Kind.PAGER, CheckRun.Status.SKIPPED, results)
    finding = Finding.objects.get(fingerprint=fingerprint)
    latest = (
        AlertDelivery.objects.filter(
            finding=finding,
            channel=AlertDelivery.Channel.NTFY,
            sent_at__gte=drill_start,
            backend=backend,
        )
        .order_by("-sent_at", "-pk")
        .first()
    )
    delivered = (
        backend != "fake"
        and latest is not None
        and latest.ok
        and latest.backend == backend
    )
    status = CheckRun.Status.SUCCEEDED if delivered else CheckRun.Status.FAILED
    return record_run(CheckRun.Kind.PAGER, status, results)


def alert_missed_drill(kind):
    """A missed drill is a Finding, not a silence. Pager missed is P1."""
    from monitor.alerts import raise_alert

    raise_alert(
        "drill-missed",
        f"check:{kind}",
        drill_kind=kind,
        fingerprint=f"drill-missed:{kind}",
        source_engine="monitor.drills",
        title=f"Scheduled {kind} drill did not run",
        body=(
            f"The {kind} drill is past due_at with no succeeded/failed "
            "CheckRun. A missed drill is a finding, not a silence."
        ),
        fix_action="Run the drill and inspect Beat / the probes worker.",
    )

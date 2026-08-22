"""CheckRun writers, missed-drill query, and Beat drill job bodies."""
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from core.models import CheckRun, Site, Target
from monitor.uptime import http_probe, probe_url

RESULTS_SCHEMA_VERSION = 1
_MAX_HUB_DOWN_S = 86400
_TERMINAL = (CheckRun.Status.SUCCEEDED, CheckRun.Status.FAILED)
_RESTORE_STUB_REASON = "Phase 2.5 body deferred"
_NO_ELIGIBLE_SITE = "no eligible site"
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
    stop = stop_hub or (lambda: None)
    start = start_hub or (lambda: None)
    stop()
    try:
        serving = bool(site_prober())
    except Exception:
        serving = False
    finally:
        start()
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


def run_restore_clean_drill():
    """Honest stub: record that the restore body is deferred. Do not fake success."""
    return record_run(
        CheckRun.Kind.RESTORE_CLEAN,
        CheckRun.Status.SKIPPED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "stub": True,
            "reason": _RESTORE_STUB_REASON,
        },
    )


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

"""MON-C7-RETENTION: the pinned §C7 numbers, as one nightly batched delete.

What would make these fail: a horizon that is not the addendum's number, a
DELETE that also eats rollup or AuditEvent rows, or a janitor that is one
unbounded queryset.delete() and is not safe to run twice.
"""
import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from celery.schedules import crontab
from django.conf import settings

from core.models import AuditEvent, Project, Site, TrafficStat, UptimeEvent
from deploys.models import Deployment, DeploymentStep, Manifest

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)


def _site(slug="retain"):
    from dns_fixtures import default_dns_zone

    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    return Site.objects.create(
        project=project, name=slug, domain=f"{slug}.example.com",
        dns_zone=default_dns_zone(),
    )


def _traffic(site, granularity, age, *, requests=1):
    return TrafficStat.objects.create(
        site=site,
        bucket_start=NOW - age,
        granularity=granularity,
        requests=requests,
    )


def _uptime(entity, kind, age, *, state="up"):
    return UptimeEvent.objects.create(
        entity=entity, kind=kind, state=state, at=NOW - age,
    )


def _step(slug, age, *, log_text="deploy log body\n"):
    site = _site(slug)
    manifest = Manifest.objects.create(site=site, version=1, body={})
    deployment = Deployment.objects.create(manifest=manifest)
    return DeploymentStep.objects.create(
        deployment=deployment,
        seq=1,
        name=DeploymentStep.Name.BUILD,
        status=DeploymentStep.Status.SUCCEEDED,
        finished=NOW - age,
        log_text=log_text,
    )


@pytest.mark.req("MON-C7-RETENTION")
def test_each_table_uses_its_pinned_horizon(tmp_path):
    """Each C7 series is cut at its pinned horizon, and only there.

    What would make this fail: HostMetric raw ≠ 14 d / hourly ≠ 1 y, UptimeEvent
    raw ≠ 90 d, TrafficStat minute ≠ 48 h / hour ≠ 90 d, deploy-log gzip ≠ 30 d,
    or a just-inside-horizon row disappearing with the stale ones.
    """
    from monitor import tasks as monitor_tasks
    from monitor.retention import HORIZONS, sweep

    assert HORIZONS["HostMetric"]["raw"] == timedelta(days=14)
    assert HORIZONS["HostMetric"]["hourly"] == timedelta(days=365)
    assert HORIZONS["UptimeEvent"]["raw"] == timedelta(days=90)
    assert HORIZONS["UptimeEvent"]["daily"] is None
    assert HORIZONS["TrafficStat"]["minute"] == timedelta(hours=48)
    assert HORIZONS["TrafficStat"]["hour"] == timedelta(days=90)
    assert HORIZONS["TrafficStat"]["day"] is None
    assert HORIZONS["AuditEvent"] is None
    assert HORIZONS["deploy_logs"] == timedelta(days=30)

    entry = settings.CELERY_BEAT_SCHEDULE["retention-janitor-nightly"]
    assert entry["task"] == monitor_tasks.run_retention_janitor.name
    assert isinstance(entry["schedule"], crontab)
    assert entry["schedule"].hour == {0}
    assert entry["schedule"].minute == {0}
    assert "kwargs" not in entry

    site = _site("horizons")
    stale_min = _traffic(site, TrafficStat.Granularity.MINUTE, timedelta(hours=48, minutes=1))
    keep_min = _traffic(site, TrafficStat.Granularity.MINUTE, timedelta(hours=47, minutes=59))
    stale_hour = _traffic(site, TrafficStat.Granularity.HOUR, timedelta(days=90, hours=1))
    keep_hour = _traffic(site, TrafficStat.Granularity.HOUR, timedelta(days=89, hours=23))
    keep_day = _traffic(site, TrafficStat.Granularity.DAY, timedelta(days=4000))

    stale_up = _uptime("site:horizons", "http", timedelta(days=90, minutes=1))
    keep_up = _uptime("site:horizons", "http", timedelta(days=89, hours=23))

    stale_step = _step("old-log", timedelta(days=30, minutes=1), log_text="STALE-LOG")
    keep_step = _step("new-log", timedelta(days=29, hours=23), log_text="FRESH-LOG")

    sweep(now=NOW, log_dir=tmp_path)

    remaining = set(TrafficStat.objects.values_list("pk", flat=True))
    assert remaining == {keep_min.pk, keep_hour.pk, keep_day.pk}
    assert not TrafficStat.objects.filter(pk=stale_min.pk).exists()
    assert not TrafficStat.objects.filter(pk=stale_hour.pk).exists()

    assert not UptimeEvent.objects.filter(pk=stale_up.pk).exists()
    assert UptimeEvent.objects.filter(pk=keep_up.pk).exists()

    stale_step.refresh_from_db()
    keep_step.refresh_from_db()
    assert stale_step.log_text == ""
    gz = Path(stale_step.artifacts["log_gzip"])
    assert gz.is_file()
    with gzip.open(gz, "rt", encoding="utf-8") as fh:
        assert fh.read() == "STALE-LOG"
    assert keep_step.log_text == "FRESH-LOG"
    assert "log_gzip" not in (keep_step.artifacts or {})


@pytest.mark.req("MON-C7-RETENTION")
def test_auditevent_is_never_deleted():
    """AuditEvent is small and forever — even a decade-old row stays.

    What would make this fail: AuditEvent appearing in the delete loop, or a
    generic 'old rows' sweep that does not carve it out.
    """
    from monitor.retention import NEVER_DELETE, sweep

    assert "AuditEvent" in NEVER_DELETE
    event = AuditEvent.objects.create(
        action="ancient", source=AuditEvent.Source.SYSTEM,
    )
    AuditEvent.objects.filter(pk=event.pk).update(ts=NOW - timedelta(days=3650))
    sweep(now=NOW)
    assert AuditEvent.objects.filter(pk=event.pk, action="ancient").exists()


@pytest.mark.req("MON-C7-RETENTION")
def test_rollup_rows_survive_raw_deletion():
    """Hour/day TrafficStat and daily UptimeEvent outlive the raw DELETE.

    What would make this fail: a filter on timestamp alone that also drops
    rollup grains, or treating kind=daily as just another raw event.
    """
    from monitor.retention import sweep

    site = _site("rollups")
    raw = _traffic(site, TrafficStat.Granularity.MINUTE, timedelta(days=10))
    hour = _traffic(site, TrafficStat.Granularity.HOUR, timedelta(days=10))
    day = _traffic(site, TrafficStat.Granularity.DAY, timedelta(days=10))
    raw_up = _uptime("site:rollups", "http", timedelta(days=120))
    daily = _uptime("site:rollups", "daily", timedelta(days=120), state="up-1d")

    sweep(now=NOW)

    assert not TrafficStat.objects.filter(pk=raw.pk).exists()
    assert TrafficStat.objects.filter(pk=hour.pk).exists()
    assert TrafficStat.objects.filter(pk=day.pk).exists()
    assert not UptimeEvent.objects.filter(pk=raw_up.pk).exists()
    assert UptimeEvent.objects.filter(pk=daily.pk, kind="daily").exists()


@pytest.mark.req("MON-C7-RETENTION")
def test_janitor_is_batched_and_idempotent():
    """Deletes land in batches of N, and a second pass is a no-op.

    What would make this fail: one queryset.delete() of the whole stale set,
    or a second run deleting (or gzipping) again.
    """
    from monitor.retention import sweep

    site = _site("batch")
    for i in range(5):
        _traffic(
            site, TrafficStat.Granularity.MINUTE,
            timedelta(hours=48, minutes=10 + i),
            requests=i + 1,
        )
    first = sweep(now=NOW, batch_size=2)
    assert first["TrafficStat"]["deleted"] == 5
    assert first["TrafficStat"]["batches"] == 3
    assert TrafficStat.objects.filter(granularity=TrafficStat.Granularity.MINUTE).count() == 0

    second = sweep(now=NOW, batch_size=2)
    assert second["TrafficStat"]["deleted"] == 0
    assert second["TrafficStat"]["batches"] == 0

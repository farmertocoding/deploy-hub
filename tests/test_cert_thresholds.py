"""TLS-V9-CERT-THRESHOLDS — uploaded 45/21/7, auto-renewed 7/1, expired is P1."""
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.req("TLS-V9-CERT-THRESHOLDS")]


def _site(slug="thresh"):
    from dns_fixtures import default_dns_zone

    from core.models import Project, Site

    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    return Site.objects.create(
        project=project,
        name=slug,
        domain=f"{slug}.example.test",
        dns_zone=default_dns_zone(f"{slug}.example.test"),
    )


def _cert(site, *, mode, days):
    from core.models import TlsCertificate

    now = timezone.now()
    return TlsCertificate.objects.create(
        site=site,
        mode=mode,
        not_after=now + timedelta(days=days),
        fingerprint=f"fp-{site.name}-{mode}-{days}",
        key_ref=f"tls-{site.pk}",
    )


def _expired(site, *, mode="uploaded"):
    from core.models import TlsCertificate

    return TlsCertificate.objects.create(
        site=site,
        mode=mode,
        not_after=timezone.now() - timedelta(hours=3),
        fingerprint=f"fp-{site.name}-expired",
        key_ref=f"tls-{site.pk}",
    )


def test_uploaded_45_21_7_maps_to_p3_p2_p1():
    """Uploaded certs: 45 d = P3, 21 d = P2, 7 d = P1.

    What would make this fail: using the auto-renewed table for uploaded
    certs, or treating 45 d as silence.
    """
    from core.models import Finding, TlsCertificate
    from monitor.cert_watch import scan_cert_expiry

    site = _site("upl")
    _cert(site, mode=TlsCertificate.Mode.UPLOADED, days=45)
    scan_cert_expiry()
    assert Finding.objects.get().severity == Finding.Severity.P3

    Finding.objects.all().delete()
    TlsCertificate.objects.all().delete()
    _cert(site, mode=TlsCertificate.Mode.UPLOADED, days=21)
    scan_cert_expiry()
    assert Finding.objects.get().severity == Finding.Severity.P2

    Finding.objects.all().delete()
    TlsCertificate.objects.all().delete()
    _cert(site, mode=TlsCertificate.Mode.UPLOADED, days=7)
    scan_cert_expiry()
    assert Finding.objects.get().severity == Finding.Severity.P1


def test_auto_renewed_7_and_1_map_to_p2_and_p1():
    """Auto-renewed (origin_cert/auto): 7 d = P2, 1 d = P1.

    What would make this fail: waiting until 7 d to start Origin renewal
    (that's already 'renewal is broken') or silencing 1 d.
    """
    from core.models import Finding, TlsCertificate
    from monitor.cert_watch import scan_cert_expiry

    site = _site("auto")
    _cert(site, mode=TlsCertificate.Mode.ORIGIN_CERT, days=7)
    scan_cert_expiry()
    assert Finding.objects.get().severity == Finding.Severity.P2

    Finding.objects.all().delete()
    TlsCertificate.objects.all().delete()
    _cert(site, mode=TlsCertificate.Mode.AUTO, days=1)
    scan_cert_expiry()
    assert Finding.objects.get().severity == Finding.Severity.P1


def test_expired_cert_is_p1_not_silence():
    """An expired cert is P1 even if no remaining-days row matches.

    What would make this fail: `days_left < 0` falling through to None
    and the daily scan staying quiet on a dead cert.
    """
    from core.models import Finding, TlsCertificate
    from monitor.cert_watch import scan_cert_expiry

    site = _site("dead")
    _expired(site, mode=TlsCertificate.Mode.UPLOADED)
    scan_cert_expiry()
    row = Finding.objects.get()
    assert row.severity == Finding.Severity.P1

    Finding.objects.all().delete()
    TlsCertificate.objects.all().delete()
    _expired(site, mode=TlsCertificate.Mode.ORIGIN_CERT)
    scan_cert_expiry()
    assert Finding.objects.get().severity == Finding.Severity.P1


def test_threshold_table_matches_alert_protocol_v9():
    """The constants are the V9 table, and Beat owns the daily CheckRun.

    What would make this fail: drifting the numbers back to master-plan §6C,
    or a daily check with no scheduler owner.
    """
    from django.conf import settings

    from core.models import CheckRun, TlsCertificate
    from monitor import tasks as monitor_tasks
    from monitor.cert_watch import (
        AUTO_THRESHOLDS,
        UPLOADED_THRESHOLDS,
        scan_cert_expiry,
    )

    assert UPLOADED_THRESHOLDS == ((45, "p3"), (21, "p2"), (7, "p1"))
    assert AUTO_THRESHOLDS == ((7, "p2"), (1, "p1"))
    assert TlsCertificate.Mode.ORIGIN_CERT in (
        TlsCertificate.Mode.ORIGIN_CERT,
        TlsCertificate.Mode.AUTO,
    )

    entry = settings.CELERY_BEAT_SCHEDULE["cert-expiry-daily"]
    assert entry["task"] == monitor_tasks.scan_cert_expiry.name
    assert float(entry["schedule"]) == 86400.0
    assert "kwargs" not in entry
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "control"

    site = _site("beat")
    _cert(site, mode=TlsCertificate.Mode.UPLOADED, days=45)
    run = scan_cert_expiry()
    assert run.kind == CheckRun.Kind.CERT_EXPIRY
    assert run.results.get("schema_version") == 1
    outcome = monitor_tasks.scan_cert_expiry()
    assert outcome["kind"] == CheckRun.Kind.CERT_EXPIRY
    assert CheckRun.objects.filter(kind=CheckRun.Kind.CERT_EXPIRY).count() >= 2

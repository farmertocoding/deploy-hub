"""Daily V9 cert-expiry scan — Findings at P3/P2/P1 plus a CheckRun.

Uploaded: 45 d = P3, 21 d = P2, 7 d = P1.
Auto-renewed (origin_cert / auto / hub_dns01): 7 d = P2, 1 d = P1.
Expired is always P1, never silence.
"""
from datetime import timedelta

from django.utils import timezone

RESULTS_SCHEMA_VERSION = 1
SOURCE_ENGINE = "cert_watch"

# Most-lenient first; classify walks from the tightest row.
UPLOADED_THRESHOLDS = ((45, "p3"), (21, "p2"), (7, "p1"))
AUTO_THRESHOLDS = ((7, "p2"), (1, "p1"))
AUTO_MODES = frozenset({"origin_cert", "auto", "hub_dns01"})


def classify_expiry(cert, now=None):
    """Return a p1/p2/p3 string, or None if the cert is outside every window."""
    now = now or timezone.now()
    if cert.not_after is None:
        return None
    if cert.not_after <= now:
        return "p1"
    remaining = cert.not_after - now
    table = AUTO_THRESHOLDS if cert.mode in AUTO_MODES else UPLOADED_THRESHOLDS
    for threshold, severity in reversed(table):
        if remaining <= timedelta(days=threshold):
            return severity
    return None


def scan_cert_expiry(*, now=None):
    """Scan every TlsCertificate.not_after; return the CheckRun."""
    from core.findings import finding
    from core.models import CheckRun, TlsCertificate
    from monitor.drills import record_run

    clock = now or timezone.now()
    scanned = []
    for cert in TlsCertificate.objects.select_related("site").order_by("pk"):
        severity = classify_expiry(cert, clock)
        if severity:
            site = cert.site
            finding(
                SOURCE_ENGINE,
                f"cert-expiry:{site.pk}",
                severity=severity,
                entity=f"site:{site.name}",
                title=(
                    f"Certificate for {site.domain or site.name} "
                    f"expires {cert.not_after:%Y-%m-%d}"
                ),
                body=_body(cert, severity, clock),
                fix_action=_fix_action(cert),
            )
        scanned.append({
            "site": cert.site.name,
            "mode": cert.mode,
            "severity": severity,
        })
    return record_run(
        CheckRun.Kind.CERT_EXPIRY,
        CheckRun.Status.SUCCEEDED,
        {"schema_version": RESULTS_SCHEMA_VERSION, "certs": scanned},
    )


def _body(cert, severity, now):
    remaining = cert.not_after - now
    days = max(0, int(remaining.total_seconds() // 86400))
    return (
        f"{cert.mode} certificate on {cert.site.domain or cert.site.name} "
        f"has {days} day(s) remaining ({severity})."
    )


def _fix_action(cert):
    if cert.mode == "uploaded":
        return "Upload a replacement certificate before it expires."
    return (
        "Investigate why auto-renewal did not reissue this certificate; "
        "re-run ensure_site_certificate or wait for the next deploy."
    )

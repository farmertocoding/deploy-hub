"""Hub Beat body: poll the partner intake outbox. Must not import intake.

`intake_client_for` is fail-closed. Tests inject FakeIntakeClient. Empty
INTAKE_URL is a no-op SKIPPED and does not persist a CheckRun per tick.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.conf import settings
from django.utils import timezone

BATCH_CAP = 20
FAIL_N = 3
UNREACHABLE_AFTER = timedelta(minutes=5)
RESULTS_SCHEMA_VERSION = 1


class IntakeClientError(Exception):
    """Fail-closed: no usable intake client."""


class FakeIntakeClient:
    """Hub-side T1 double. Does not import the intake process."""

    def __init__(self, items=None, *, fail=False):
        self.items = list(items or [])
        self.acked = []
        self.fail = fail
        self.fetch_calls = 0

    def fetch(self, limit=BATCH_CAP):
        self.fetch_calls += 1
        if self.fail:
            raise IntakeClientError("intake unreachable")
        return list(self.items[:limit])

    def ack(self, job_id):
        self.acked.append(job_id)
        self.items = [item for item in self.items if item.get("id") != job_id]


class HttpIntakeClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def fetch(self, limit=BATCH_CAP):
        url = f"{self.base_url}/internal/outbox"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
                payload = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise IntakeClientError("fetch failed") from exc
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = payload.get("items") or []
        else:
            items = []
        return list(items)[:limit]

    def ack(self, job_id):
        url = f"{self.base_url}/internal/ack"
        body = json.dumps({"id": job_id}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)  # nosec B310
        except (OSError, urllib.error.URLError) as exc:
            raise IntakeClientError("ack failed") from exc


def intake_client_for(*, url=None, client=None):
    """Construct a client or refuse. Empty / non-http URL is not a silent Fake."""
    if client is not None:
        fetch = getattr(client, "fetch", None)
        if not callable(fetch):
            raise IntakeClientError("injected client cannot fetch")
        return client
    raw = settings.INTAKE_URL if url is None else url
    raw = (raw or "").strip()
    if not raw:
        raise IntakeClientError("INTAKE_URL is empty")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise IntakeClientError("INTAKE_URL is not an http(s) URL")
    return HttpIntakeClient(raw)


def poll(*, client=None, now=None, sleep=None, jitter=None):
    clock = _as_datetime(now)
    configured = (getattr(settings, "INTAKE_URL", "") or "").strip()
    if client is None and not configured:
        return {"ok": True, "status": "skipped", "n": 0}

    delay = 0.0 if jitter is None else float(jitter)
    if delay:
        sleeper = sleep
        if sleeper is None:
            import time

            sleeper = time.sleep
        sleeper(delay)

    try:
        used = client if client is not None else intake_client_for(url=configured)
        items = list(used.fetch(limit=BATCH_CAP))[:BATCH_CAP]
    except Exception:
        return _record_failure(clock)

    n = _process(used, items, clock)
    return _record_success(clock, n)


def _as_datetime(now):
    if now is None:
        return timezone.now()
    if hasattr(now, "year"):
        return now
    return datetime.fromtimestamp(int(now), tz=dt_tz.utc)


def _partner_for(job):
    from core.models import Partner

    pk = job.get("partner_pk") or job.get("partner_id")
    if pk:
        return Partner.objects.filter(pk=pk).first()
    return None


def _process(client, items, now):
    from core.partner_jobs import PartnerNotFound, PartnerRefuse, materialize
    from core.partner_verify import ReplayRejected, SignatureRejected, reverify

    n = 0
    for job in items:
        job_id = job.get("id")
        try:
            partner = _partner_for(job)
            if partner is not None:
                result = reverify(
                    partner,
                    job.get("method") or "POST",
                    job.get("path") or "",
                    job.get("body") or b"",
                    job.get("headers") or {},
                    now=now,
                )
                if result.ok:
                    n += 1
                    job_type = job.get("type") or "partner-job"
                    if job_type == "partner-job":
                        try:
                            materialize(partner, job)
                        except (PartnerRefuse, PartnerNotFound):
                            pass
        except (ReplayRejected, SignatureRejected):
            pass
        if job_id is not None and client is not None:
            ack = getattr(client, "ack", None)
            if callable(ack):
                try:
                    ack(job_id)
                except IntakeClientError:
                    pass
    return n


def _latest_poll():
    from core.models import CheckRun

    return (
        CheckRun.objects.filter(kind=CheckRun.Kind.INTAKE_POLL)
        .order_by("-pk")
        .first()
    )


def _upsert(status, results, now):
    from core.models import CheckRun

    payload = dict(results)
    payload.setdefault("schema_version", RESULTS_SCHEMA_VERSION)
    latest = _latest_poll()
    if latest is None:
        return CheckRun.objects.create(
            kind=CheckRun.Kind.INTAKE_POLL,
            status=status,
            results=payload,
            started=now,
            finished=now,
        )
    latest.status = status
    latest.results = payload
    latest.finished = now
    latest.save(update_fields=["status", "results", "finished"])
    return latest


def _parse_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_tz.utc)
    return parsed


def _iso(now):
    return now.isoformat() if hasattr(now, "isoformat") else str(now)


def _record_failure(now):
    from core.models import CheckRun
    from monitor.alerts import raise_alert

    latest = _latest_poll()
    prev = (latest.results if latest is not None else {}) or {}
    consecutive = int(prev.get("consecutive_failures") or 0) + 1
    last_success_at = prev.get("last_success_at")
    _upsert(
        CheckRun.Status.FAILED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "consecutive_failures": consecutive,
            "last_success_at": last_success_at,
        },
        now,
    )
    if consecutive >= FAIL_N:
        raise_alert(
            "hub-outbox-poll-failing",
            "intake",
            fingerprint="hub-outbox-poll-failing",
            source_engine="monitor.intake_poll",
            title="Hub outbox poll failing",
            body=(
                "The Hub could not fetch the partner intake outbox for "
                f"{consecutive} consecutive cycles."
            ),
            fix_action="Check INTAKE_URL and the intake process.",
        )
    stamp = _parse_iso(last_success_at)
    if stamp is not None and now - stamp >= UNREACHABLE_AFTER:
        raise_alert(
            "partner-intake-unreachable",
            "intake",
            fingerprint="partner-intake-unreachable",
            source_engine="monitor.intake_poll",
            title="Partner intake unreachable",
            body=(
                "No successful Hub poll of the partner intake outbox "
                "for more than 5 minutes."
            ),
            fix_action="Restore the intake process and confirm INTAKE_URL.",
        )
    return {"ok": False, "status": "failed", "n": 0}


def _record_success(now, n):
    from core.models import CheckRun

    _upsert(
        CheckRun.Status.SUCCEEDED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "consecutive_failures": 0,
            "last_success_at": _iso(now),
            "n": n,
        },
        now,
    )
    return {"ok": True, "status": "succeeded", "n": n}

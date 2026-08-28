"""Hub Beat poll of the intake outbox: 10 s, fail-closed client, empty URL skip.

Empty INTAKE_URL is SKIPPED and must not insert a CheckRun every 10 s or file
P1 partner-intake-unreachable. Tests inject FakeIntakeClient. monitor/intake_poll.py
must not import intake.
"""
import ast
import pathlib
import re
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
INTAKE_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+intake\b", re.M)
BANNED_ENV = (
    "HUB_TEST_PARTNER_TOKEN",
    "HUB_WEBHOOK_SECRET",
    "HUB_INTAKE_HMAC",
    "HUB_TEST_CF_TOKEN",
    "HUB_TEST_AWS_TOKEN",
)


@pytest.mark.req("PART-HUB-POLL")
def test_beat_interval_is_10s_on_probes():
    """poll-intake-outbox is 10 s on queue probes; intake_poll is not a drill.

    What would make this fail: a 60 s schedule, routing off probes, adding
    intake_poll to DRILL_PERIODS, or defaulting PARTNER_API_ENABLED on.
    """
    from django.conf import settings

    from core.models import CheckRun
    from monitor import tasks as monitor_tasks
    from monitor.drills import DRILL_PERIODS

    entry = settings.CELERY_BEAT_SCHEDULE["poll-intake-outbox"]
    assert entry["task"] == monitor_tasks.poll_intake_outbox.name
    assert float(entry["schedule"]) == 10.0
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"
    assert CheckRun.Kind.INTAKE_POLL not in DRILL_PERIODS
    assert settings.INTAKE_URL == ""
    assert settings.PARTNER_API_ENABLED is False
    assert int(settings.PARTNER_FLEET_MAX_SITES) == 12
    base = (REPO / "hub" / "settings" / "base.py").read_text(encoding="utf-8")
    assert 'os.environ.get("HUB_INTAKE_URL", "")' in base
    assert "HUB_PARTNER_API_ENABLED" in base
    assert 'os.environ.get("HUB_PARTNER_FLEET_MAX_SITES", "12")' in base
    for banned in BANNED_ENV:
        assert banned not in base
    prod = (REPO / "hub" / "settings" / "prod.py").read_text(encoding="utf-8")
    assert "INTAKE_URL =" not in prod
    assert "PARTNER_API_ENABLED =" not in prod


def test_partner_api_settings_assignment_does_not_leak_setup():
    """PartnerApiFlag.set_on writes django.conf.settings (process-global)."""
    from django.conf import settings

    from core.models import PartnerApiFlag

    PartnerApiFlag.set_on(True)
    assert settings.PARTNER_API_ENABLED is True


def test_partner_api_settings_assignment_does_not_leak_check():
    """A later test must see the default-off flag, not a leaked True.

    mutmut's clean run is a second in-process pytest.main(); without a
    per-test reset, test_beat_interval_is_10s_on_probes asserts True is False.

    What would make this fail: set_on leaking True into the next test.
    """
    from django.conf import settings

    assert settings.PARTNER_API_ENABLED is False


@pytest.mark.req("PART-HUB-POLL")
def test_empty_intake_url_skips_and_does_not_file_p1():
    """Empty INTAKE_URL is SKIPPED: no CheckRun flood, no unreachable P1.

    What would make this fail: inserting a CheckRun every 10 s tick, filing
    partner-intake-unreachable for unconfigured intake, or returning succeeded.
    """
    from core.models import CheckRun, Finding
    from monitor.intake_poll import poll

    with override_settings(INTAKE_URL=""):
        first = poll(jitter=0, sleep=lambda _s: None)
        assert first["status"] == CheckRun.Status.SKIPPED
        assert first["status"] != CheckRun.Status.SUCCEEDED
        for _ in range(4):
            later = poll(jitter=0, sleep=lambda _s: None)
            assert later["status"] == CheckRun.Status.SKIPPED
    assert CheckRun.objects.filter(kind=CheckRun.Kind.INTAKE_POLL).count() == 0
    assert not Finding.objects.filter(fingerprint="partner-intake-unreachable").exists()
    assert not Finding.objects.filter(fingerprint="hub-outbox-poll-failing").exists()


@pytest.mark.req("PART-HUB-POLL")
def test_n3_poll_failures_file_hub_outbox_poll_failing():
    """Three consecutive configured poll failures file the global P2 pin.

    What would make this fail: filing on the first failure, using the default
    {kind}:{entity} fingerprint, or inserting a new CheckRun per tick.
    """
    from core.models import CheckRun, Finding
    from monitor.alert_rules import classify
    from monitor.intake_poll import FakeIntakeClient, poll

    assert classify("hub-outbox-poll-failing") == "p2"
    client = FakeIntakeClient(fail=True)
    now = timezone.now()
    with override_settings(INTAKE_URL="http://intake.test"):
        for _ in range(2):
            poll(client=client, now=now, jitter=0, sleep=lambda _s: None)
            assert not Finding.objects.filter(
                fingerprint="hub-outbox-poll-failing",
            ).exists()
        poll(client=client, now=now, jitter=0, sleep=lambda _s: None)
    row = Finding.objects.get(fingerprint="hub-outbox-poll-failing")
    assert row.severity == "p2"
    assert not Finding.objects.filter(
        fingerprint="hub-outbox-poll-failing:intake",
    ).exists()
    assert CheckRun.objects.filter(kind=CheckRun.Kind.INTAKE_POLL).count() <= 1


@pytest.mark.req("PART-HUB-POLL")
def test_unreachable_over_5_min_files_partner_intake_unreachable():
    """Last successful probe > 5 min ago files the global P1 pin.

    What would make this fail: treating unconfigured as unreachable, using the
    default {kind}:{entity} fingerprint, or waiting for N=3 alone.
    """
    from core.models import Finding
    from monitor.alert_rules import classify
    from monitor.intake_poll import FakeIntakeClient, poll

    assert classify("partner-intake-unreachable") == "p1"
    client = FakeIntakeClient()
    t0 = timezone.now()
    with override_settings(INTAKE_URL="http://intake.test"):
        poll(client=client, now=t0, jitter=0, sleep=lambda _s: None)
        assert not Finding.objects.filter(
            fingerprint="partner-intake-unreachable",
        ).exists()
        client.fail = True
        poll(
            client=client,
            now=t0 + timedelta(minutes=6),
            jitter=0,
            sleep=lambda _s: None,
        )
    row = Finding.objects.get(fingerprint="partner-intake-unreachable")
    assert row.severity == "p1"
    assert not Finding.objects.filter(
        fingerprint="partner-intake-unreachable:intake",
    ).exists()


@pytest.mark.req("PART-HUB-POLL")
def test_configured_never_up_files_p1_after_5_min():
    """Configured INTAKE_URL that never succeeds pages P1 after 5 min.

    What would make this fail: N=3 consecutive_failures filing this P1,
    requiring a prior last_success_at, moving first_failure_at, or paging
    empty INTAKE_URL after five minutes.
    """
    from core.models import CheckRun, Finding
    from monitor.intake_poll import FakeIntakeClient, poll

    t0 = timezone.now()
    with override_settings(INTAKE_URL=""):
        for now in (t0, t0 + timedelta(minutes=5)):
            result = poll(now=now, jitter=0, sleep=lambda _s: None)
            assert result["status"] == CheckRun.Status.SKIPPED
        assert CheckRun.objects.filter(kind=CheckRun.Kind.INTAKE_POLL).count() == 0
        assert not Finding.objects.filter(
            fingerprint="partner-intake-unreachable",
        ).exists()
        assert not Finding.objects.filter(
            fingerprint="hub-outbox-poll-failing",
        ).exists()

    client = FakeIntakeClient(fail=True)
    with override_settings(INTAKE_URL="http://intake.test"):
        for _ in range(3):
            poll(client=client, now=t0, jitter=0, sleep=lambda _s: None)
        assert Finding.objects.filter(
            fingerprint="hub-outbox-poll-failing",
        ).exists()
        assert not Finding.objects.filter(
            fingerprint="partner-intake-unreachable",
        ).exists()
        latest = CheckRun.objects.get(kind=CheckRun.Kind.INTAKE_POLL)
        first = (latest.results or {}).get("first_failure_at")
        assert first
        poll(
            client=client, now=t0 + timedelta(minutes=4),
            jitter=0, sleep=lambda _s: None,
        )
        latest = CheckRun.objects.get(kind=CheckRun.Kind.INTAKE_POLL)
        assert (latest.results or {}).get("first_failure_at") == first
        assert not Finding.objects.filter(
            fingerprint="partner-intake-unreachable",
        ).exists()
        poll(
            client=client, now=t0 + timedelta(minutes=5),
            jitter=0, sleep=lambda _s: None,
        )
    row = Finding.objects.get(fingerprint="partner-intake-unreachable")
    assert row.severity == "p1"
    assert not Finding.objects.filter(
        fingerprint="partner-intake-unreachable:intake",
    ).exists()


@pytest.mark.req("PART-HUB-POLL")
def test_poison_outbox_item_does_not_kill_beat_or_arm_c12():
    """A non-dict outbox row must not raise out of poll or increment fetch failures.

    What would make this fail: job.get on a str, wrapping fetch so Beat
    lives but C12 never arms, or counting the poison as consecutive_failures.
    """
    from core.models import CheckRun, Finding
    from monitor.intake_poll import FakeIntakeClient, poll

    client = FakeIntakeClient(items=["poison", {"id": "later", "type": "partner-job"}])
    now = timezone.now()
    with override_settings(INTAKE_URL="http://intake.test", PARTNER_API_ENABLED=False):
        result = poll(client=client, now=now, jitter=0, sleep=lambda _s: None)
        assert result["ok"] is True
        assert result["status"] == "succeeded"
        latest = CheckRun.objects.get(kind=CheckRun.Kind.INTAKE_POLL)
        assert int((latest.results or {}).get("consecutive_failures") or 0) == 0
        assert not Finding.objects.filter(
            fingerprint="hub-outbox-poll-failing",
        ).exists()
        client.fail = True
        for _ in range(3):
            poll(client=client, now=now, jitter=0, sleep=lambda _s: None)
    p2 = Finding.objects.get(fingerprint="hub-outbox-poll-failing")
    assert p2.severity == "p2"
    assert not Finding.objects.filter(
        fingerprint="hub-outbox-poll-failing:intake",
    ).exists()


@pytest.mark.req("PART-HUB-POLL")
def test_intake_client_for_is_fail_closed():
    """Constructor refuses empty/non-http URLs and never imports intake.

    What would make this fail: defaulting to FakeIntakeClient on empty URL
    (a T1-sibling green), accepting ftp://, or `import intake` in the poller.
    """
    from monitor.intake_poll import (
        FakeIntakeClient,
        IntakeClientError,
        intake_client_for,
    )

    with override_settings(INTAKE_URL=""):
        with pytest.raises(IntakeClientError):
            intake_client_for()
    with override_settings(INTAKE_URL="not-a-url"):
        with pytest.raises(IntakeClientError):
            intake_client_for()
    with override_settings(INTAKE_URL="ftp://intake.test"):
        with pytest.raises(IntakeClientError):
            intake_client_for()
    fake = FakeIntakeClient()
    assert intake_client_for(client=fake) is fake
    with override_settings(INTAKE_URL="https://intake.example.test", INTAKE_SERVICE_TOKEN="t"):
        live = intake_client_for()
        assert live is not None
        assert type(live) is not type(fake)
    src = (REPO / "monitor" / "intake_poll.py").read_text(encoding="utf-8")
    assert INTAKE_IMPORT_RE.search(src) is None
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.split(".")[0] == "intake"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "intake"
    base = (REPO / "hub" / "settings" / "base.py").read_text(encoding="utf-8")
    for banned in BANNED_ENV:
        assert banned not in base
        assert banned not in src


@pytest.mark.req("PART-HUB-POLL")
def test_http_intake_client_refuses_redirect_to_metadata(monkeypatch):
    """A 302 Location to 169.254.169.254 is not followed; fetch/ack fail closed.

    What would make this fail: urllib.request.urlopen following redirects so a
    mis-set INTAKE_URL bounces onto cloud metadata (webhook _NoRedirect class).
    """
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from monitor.intake_poll import HttpIntakeClient, IntakeClientError

    hits = []
    metadata = "http://169.254.169.254/latest/meta-data/"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def _redirect(self):
            hits.append((self.command, self.path))
            self.send_response(302)
            self.send_header("Location", metadata)
            self.end_headers()

        def do_GET(self):
            self._redirect()

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            self._redirect()

    seen = []
    orig = socket.create_connection

    def guarded(address, *args, **kwargs):
        host = address[0]
        if isinstance(host, (bytes, bytearray)):
            host = host.decode()
        seen.append(host)
        if host in {"169.254.169.254", "::ffff:169.254.169.254"}:
            raise OSError("metadata must not be contacted")
        return orig(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        client = HttpIntakeClient(f"http://127.0.0.1:{httpd.server_address[1]}")
        with pytest.raises(IntakeClientError):
            client.fetch()
        with pytest.raises(IntakeClientError):
            client.ack("job-redirect")
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert "169.254.169.254" not in seen
    assert "::ffff:169.254.169.254" not in seen
    assert ("GET", "/internal/outbox") in hits
    assert ("POST", "/internal/ack") in hits

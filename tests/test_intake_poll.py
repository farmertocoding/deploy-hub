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
    with override_settings(INTAKE_URL="https://intake.example.test"):
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

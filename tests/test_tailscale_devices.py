"""T1: Tailscale device-list poll (SEC-B8 / D-058). Skip-unless-configured.

Absent HUB_TAILSCALE_API_TOKEN_REF is a SKIPPED CheckRun plus a dated waiver,
never SUCCEEDED and never a live-tier green. FakeTailscale is the T1 seam.
Do not invent a live token env (C6).
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import uuid

import pytest
from django.test import override_settings

pytestmark = [pytest.mark.django_db, pytest.mark.req("SEC-B8-TAILSCALE-DEVICE-POLL")]

REPO = pathlib.Path(__file__).resolve().parent.parent
REQ_ID = "SEC-B8-TAILSCALE-DEVICE-POLL"
KIND = "tailscale-unknown-device"
REF = "tailscale-api"
# nosec B105 — a planted test constant, not a live credential.
TOKEN = "tskey-api-t9-PLANTED-not-a-credential-x7k2"  # nosec B105


def _target(host):
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(
        name="ts-net", slug=f"ts-{uuid.uuid4().hex[:10]}",
    )
    return Target.objects.create(zone=zone, host=host, status=Target.Status.READY)


def _plant_token(ref, token):
    from vault import service as vault_service
    from vault.models import Secret

    return vault_service.put(
        kind=Secret.Kind.API_TOKEN,
        owner_type="tailscale",
        owner_id=ref,
        plaintext=token.encode(),
    )


def _findings():
    from core.models import Finding

    return Finding.objects.filter(fingerprint__startswith=f"{KIND}:")


def _surfaces(run):
    from core.models import AuditEvent, Finding

    blobs = [run.kind, run.status, run.results]
    for row in Finding.objects.all():
        blobs.extend([
            row.title, row.body, row.fix_action, row.entity,
            row.fingerprint, row.severity, row.source_engine,
        ])
    for event in AuditEvent.objects.all():
        blobs.extend([event.action, event.detail, event.object_type, event.object_id])
    return json.dumps(blobs, default=str)


def test_unknown_device_files_finding():
    """A tailnet device the Hub did not create files P2 tailscale-unknown-device.

    What would make this fail: swallowing the stranger, filing at the wrong
    severity, or skipping classify() so an unregistered kind ships.
    """
    from providers.tailscale import audit_devices

    from core.models import CheckRun, Finding
    from monitor.alert_rules import classify
    from providers.fakes import FakeTailscale

    assert classify(KIND) == "p2"
    _plant_token(REF, TOKEN)
    fake = FakeTailscale(devices=[{
        "id": "nStranger",
        "hostname": "laptop-stranger",
        "name": "laptop-stranger.tailnet.ts.net",
        "addresses": ["100.64.0.99"],
    }])

    with override_settings(HUB_TAILSCALE_API_TOKEN_REF=REF):
        run = audit_devices(client=fake)

    assert run.kind == CheckRun.Kind.TAILSCALE_DEVICES
    assert run.status == CheckRun.Status.SUCCEEDED
    finding = _findings().get()
    assert finding.severity == Finding.Severity.P2
    assert finding.fingerprint == f"{KIND}:nStranger"
    assert "laptop-stranger" in finding.title or "laptop-stranger" in finding.body


def test_hub_created_target_is_silent():
    """A device whose hostname is a Hub Target files nothing.

    What would make this fail: treating every tailnet row as unknown, so the
    fleet the Hub enrolled becomes a standing P2 inbox.
    """
    from providers.tailscale import audit_devices

    from core.models import CheckRun
    from providers.fakes import FakeTailscale

    _target("hub-box")
    _plant_token(REF, TOKEN)
    fake = FakeTailscale(devices=[{
        "id": "nHubBox",
        "hostname": "hub-box",
        "name": "hub-box.tailnet.ts.net",
        "addresses": ["100.64.0.10"],
    }])

    with override_settings(HUB_TAILSCALE_API_TOKEN_REF=REF):
        run = audit_devices(client=fake)

    assert run.kind == CheckRun.Kind.TAILSCALE_DEVICES
    assert run.status == CheckRun.Status.SUCCEEDED
    assert _findings().count() == 0


def test_absent_ref_skips_and_does_not_green_a_live_tier():
    """Empty HUB_TAILSCALE_API_TOKEN_REF is SKIPPED, never SUCCEEDED, not t2/t3.

    What would make this fail: writing succeeded when the vault ref is the
    default empty string (a T1-sibling green of a live poll), inventing a
    HUB_TEST_TAILSCALE token env, marking these proofs t2/t3, omitting the
    Beat owner, or skipping the dated skip-unless-configured waiver (D-043).
    """
    from django.conf import settings
    from providers.tailscale import audit_devices

    from core.models import CheckRun
    from monitor import tasks as monitor_tasks

    assert getattr(settings, "HUB_TAILSCALE_API_TOKEN_REF", None) == ""

    run = audit_devices()
    assert run.kind == CheckRun.Kind.TAILSCALE_DEVICES
    assert run.status == CheckRun.Status.SKIPPED
    assert run.status != CheckRun.Status.SUCCEEDED
    assert _findings().count() == 0

    outcome = monitor_tasks.audit_tailscale_devices()
    assert outcome["kind"] == CheckRun.Kind.TAILSCALE_DEVICES
    assert outcome["status"] == CheckRun.Status.SKIPPED
    assert TOKEN not in json.dumps(outcome)

    entry = settings.CELERY_BEAT_SCHEDULE["tailscale-device-audit-daily"]
    assert entry["task"] == monitor_tasks.audit_tailscale_devices.name
    assert float(entry["schedule"]) == 86400.0
    assert "kwargs" not in entry
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"

    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    live_marks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr in {"t2", "t3"}:
            live_marks.append(node.attr)
    assert live_marks == [], f"T1 skip proof must not carry a live-tier mark: {live_marks}"

    base = (REPO / "hub" / "settings" / "base.py").read_text(encoding="utf-8")
    assert "HUB_TAILSCALE_API_TOKEN_REF" in base
    assert "HUB_TEST_TAILSCALE" not in base
    assert "HUB_TEST_CF_TOKEN" not in base

    waivers = [
        line for line in (REPO / "WAIVERS.md").read_text(encoding="utf-8").splitlines()
        if line.startswith(f"WAIVED: {REQ_ID} ") and "skip-unless-configured" in line
    ]
    assert waivers, (
        f"{REQ_ID} must have a dated skip-unless-configured waiver while the "
        "vault ref is empty — skip is not a green"
    )
    assert re.search(r"\(\d{4}-\d{2}-\d{2}\)$", waivers[0]), waivers[0]


def test_no_token_in_finding_or_checkrun():
    """The planted API token never appears on Finding or CheckRun surfaces.

    What would make this fail: stuffing the vault value into results, title,
    body, fingerprint, or AuditEvent.detail — the exact exhaust the poll
    exists to keep off the inbox.
    """
    from providers.tailscale import audit_devices

    from core.models import CheckRun
    from providers.fakes import FakeTailscale

    _plant_token(REF, TOKEN)
    fake = FakeTailscale(devices=[{
        "id": "nLeakProbe",
        "hostname": "unknown-phone",
        "addresses": ["100.64.0.77"],
    }])

    with override_settings(HUB_TAILSCALE_API_TOKEN_REF=REF):
        run = audit_devices(client=fake)

    assert run.kind == CheckRun.Kind.TAILSCALE_DEVICES
    dump = _surfaces(run)
    assert TOKEN not in dump
    assert TOKEN.encode() not in json.dumps(run.results).encode()
    assert _findings().count() == 1
    assert TOKEN not in _findings().get().body
    assert TOKEN not in _findings().get().title

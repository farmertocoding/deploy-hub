"""T1 Standard Webhooks Hub egress: B10 HTTPS validator, re-resolve, Fake sink.

No live POST. Function-level PART-WEBHOOKS markers only on the named tests.
"""
import base64
import json
import pathlib
import socket

import pytest
from django.core.exceptions import ValidationError

REPO = pathlib.Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.django_db

# nosec B105 — T1 fixture, never a live credential and never logged as plaintext.
_WHSEC = "whsec_" + base64.b64encode(b"t1-partner-webhook-secret-32b!!").decode()

# 140.82.121.4 is the same public fixture test_validators.py uses; TEST-NET-3
# (203.0.113.0/24) is is_private on Python 3.13 and would fail closed as B10.
PUBLIC_A = (2, 1, 6, "", ("140.82.121.4", 0))
METADATA_A = (2, 1, 6, "", ("169.254.169.254", 0))


@pytest.fixture(autouse=True)
def _reset_webhook_delivery_state():
    """In-process (pk, webhook-id) survives DB rollback; SQLite reuses PKs."""
    from core.partner_webhooks import reset_delivery_state

    reset_delivery_state()
    yield
    reset_delivery_state()


def _public_dns(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **kw: [PUBLIC_A],
    )


def _partner(*, slug, url):
    from core.models import Partner
    from vault import service as vault_service
    from vault.models import Secret

    partner = Partner.objects.create(slug=slug, name=slug, webhook_url=url)
    vault_service.put(
        kind=Secret.Kind.WEBHOOK_SECRET,
        owner_type="partner",
        owner_id=str(partner.pk),
        plaintext=_WHSEC.encode(),
    )
    return partner


def _event(eid="msg_t1_webhooks"):
    return {"id": eid, "type": "site.ready", "data": {"ok": True}}


@pytest.mark.req("PART-WEBHOOKS")
def test_http_or_ssh_webhook_url_refuses():
    """HTTPS-only: plaintext http and ssh must not reuse the git allowlist.

    What would make this fail: calling validate_git_url (ssh/22 would pass)
    or treating http as good enough because the host is public.
    """
    from core.validators import validate_git_url, validate_webhook_url

    ssh = "ssh://git@hooks.example.com/o/r.git"
    assert validate_git_url(ssh, resolve=False) == ssh
    for url in (
        "http://hooks.example.com/events",
        ssh,
        "git+ssh://git@hooks.example.com/events",
        "ftp://hooks.example.com/events",
        "https://hooks.example.com:22/events",
        "https://hooks.example.com:8443/events",
    ):
        with pytest.raises(ValidationError) as exc:
            validate_webhook_url(url, resolve=False)
        assert exc.value.code in {"bad_scheme", "bad_port"}, url


@pytest.mark.req("PART-WEBHOOKS")
def test_loopback_linklocal_private_cgnat_webhook_url_refuses():
    """B10 address checks on webhook URLs: loopback / link-local / private / CGNAT.

    What would make this fail: skipping the git B10 table so 169.254.169.254
    or 100.64.0.0/10 became a Hub egress target.
    """
    from core.validators import validate_webhook_url

    rejected = [
        ("https://127.0.0.1/events", "blocked_address"),
        ("https://[::1]/events", "blocked_address"),
        ("https://10.0.0.5/events", "blocked_address"),
        ("https://192.168.1.1/events", "blocked_address"),
        ("https://172.16.0.1/events", "blocked_address"),
        ("https://169.254.169.254/latest/meta-data/", "blocked_address"),
        ("https://169.254.1.1/events", "blocked_address"),
        ("https://100.64.0.1/events", "blocked_address"),
        ("https://[fc00::1]/events", "blocked_address"),
        ("https://0.0.0.0/events", "blocked_address"),
        ("https://224.0.0.1/events", "blocked_address"),
        ("https://localhost/events", "blocked_host"),
        ("https://hooks.local/events", "blocked_host"),
        ("https://hooks.internal/events", "blocked_host"),
    ]
    for url, code in rejected:
        with pytest.raises(ValidationError) as exc:
            validate_webhook_url(url, resolve=False)
        assert exc.value.code == code, url


@pytest.mark.req("PART-WEBHOOKS")
def test_delivery_re_resolves_and_refuses_rebind_to_metadata(monkeypatch):
    """Submit-time public resolve does not pin; delivery re-runs B10.

    What would make this fail: inheriting git's clone-off-Hub TOCTOU
    exception so a name that later points at 169.254.169.254 is POSTed.
    """
    from core.partner_webhooks import (
        FakeWebhookSink,
        deliver_partner_webhook,
        reset_delivery_state,
    )
    from core.validators import validate_webhook_url

    reset_delivery_state()
    url = "https://hooks.partner.example/events"
    _public_dns(monkeypatch)
    assert validate_webhook_url(url) == url

    partner = _partner(slug="wh-rebind", url=url)
    sink = FakeWebhookSink()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **kw: [METADATA_A],
    )
    with pytest.raises(ValidationError) as exc:
        deliver_partner_webhook(partner, _event(), sink=sink)
    assert exc.value.code == "blocked_address"
    assert sink.mutating_calls() == []


@pytest.mark.req("PART-WEBHOOKS")
def test_standard_webhooks_signature_verifies_with_reference_lib(monkeypatch):
    """Hub signer matches Standard Webhooks exact; reference lib verifies.

    What would make this fail: a homemade header set (X-Hub-Signature) or
    HMAC over the body alone, so a partner verifier using the spec rejects us.
    """
    from standardwebhooks.webhooks import Webhook

    from core.partner_webhooks import (
        FakeWebhookSink,
        deliver_partner_webhook,
        reset_delivery_state,
    )

    reset_delivery_state()
    _public_dns(monkeypatch)
    partner = _partner(slug="wh-sign", url="https://hooks.partner.example/events")
    sink = FakeWebhookSink()
    event = _event("msg_t1_sign")
    result = deliver_partner_webhook(partner, event, sink=sink)
    assert result["status"] == "delivered"
    assert sink.deliveries, "Fake sink must record the signed POST"
    delivery = sink.deliveries[0]
    headers = delivery["headers"]
    for name in ("webhook-id", "webhook-timestamp", "webhook-signature"):
        assert name in {k.lower() for k in headers}
    Webhook(_WHSEC).verify(delivery["body"], headers)


@pytest.mark.req("PART-WEBHOOKS")
def test_whsec_not_on_intake_and_not_in_detail(monkeypatch):
    """whsec_ is Hub-vaulted only: never intake, never AuditEvent.detail.

    What would make this fail: putting the signing secret on the intake
    process, or echoing it into an audit/Finding/CheckRun row.
    """
    from core.models import AuditEvent, CheckRun, Finding
    from core.partner_webhooks import (
        FakeWebhookSink,
        deliver_partner_webhook,
        reset_delivery_state,
    )

    reset_delivery_state()
    for py in (REPO / "intake").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "whsec_" not in text, py
        assert "WEBHOOK_SECRET" not in text, py
        assert "partner_webhooks" not in text, py

    _public_dns(monkeypatch)
    partner = _partner(slug="wh-secret", url="https://hooks.partner.example/events")
    sink = FakeWebhookSink()
    deliver_partner_webhook(partner, _event("msg_t1_secret"), sink=sink)

    for row in AuditEvent.objects.all():
        blob = json.dumps(row.detail, default=str)
        assert "whsec_" not in blob
        assert "whsec_" not in json.dumps(row.detail)
    for row in Finding.objects.all():
        assert "whsec_" not in (row.title or "")
        assert "whsec_" not in (row.body or "")
        assert "whsec_" not in (row.fix_action or "")
        assert "whsec_" not in (row.fingerprint or "")
    for row in CheckRun.objects.all():
        assert "whsec_" not in json.dumps(row.results or {}, default=str)


@pytest.mark.req("PART-WEBHOOKS")
def test_sustained_failure_disables_and_files_hub_egress_degraded(monkeypatch):
    """Five failures in 24 h disable delivery and file hub-egress-degraded.

    What would make this fail: retrying forever, or filing a fingerprint
    that is not hub-egress-degraded:partner:{pk}.
    """
    from core.models import Finding
    from core.partner_webhooks import (
        FakeWebhookSink,
        WebhookDeliveryError,
        deliver_partner_webhook,
        reset_delivery_state,
    )

    reset_delivery_state()
    _public_dns(monkeypatch)
    partner = _partner(slug="wh-fail", url="https://hooks.partner.example/events")
    sink = FakeWebhookSink()
    sink.fail = True
    fingerprint = f"hub-egress-degraded:partner:{partner.pk}"
    for i in range(5):
        with pytest.raises(WebhookDeliveryError):
            deliver_partner_webhook(
                partner, _event(f"msg_fail_{i}"), sink=sink,
            )
    row = Finding.objects.get(fingerprint=fingerprint)
    assert row.entity == f"partner:{partner.pk}"
    assert row.severity == Finding.Severity.P2
    assert "whsec_" not in row.body
    posted = len(sink.mutating_calls())
    assert posted == 5
    result = deliver_partner_webhook(partner, _event("msg_fail_after"), sink=sink)
    assert result["status"] == "disabled"
    assert len(sink.mutating_calls()) == posted


@pytest.mark.req("PART-WEBHOOKS")
def test_acked_hub_egress_degraded_stays_disabled(monkeypatch):
    """Ack is not resolve: ACKED hub-egress-degraded still refuses delivery.

    What would make this fail: _is_disabled keying only on OPEN, so ack
    re-arms Hub egress; finding() will not re-OPEN an ACKED row, and
    further failures never disable again.
    """
    from core.findings import ack
    from core.models import Finding
    from core.partner_webhooks import (
        FakeWebhookSink,
        WebhookDeliveryError,
        deliver_partner_webhook,
        reset_delivery_state,
    )

    reset_delivery_state()
    _public_dns(monkeypatch)
    partner = _partner(slug="wh-acked", url="https://hooks.partner.example/events")
    sink = FakeWebhookSink()
    sink.fail = True
    fingerprint = f"hub-egress-degraded:partner:{partner.pk}"
    for i in range(5):
        with pytest.raises(WebhookDeliveryError):
            deliver_partner_webhook(
                partner, _event(f"msg_acked_{i}"), sink=sink,
            )
    row = Finding.objects.get(fingerprint=fingerprint)
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    posted = len(sink.mutating_calls())
    sink.fail = False
    result = deliver_partner_webhook(partner, _event("msg_after_ack"), sink=sink)
    assert result["status"] == "disabled"
    assert len(sink.mutating_calls()) == posted


@pytest.mark.req("PART-WEBHOOKS")
def test_webhook_run_twice_zero_mutating_calls(monkeypatch):
    """Second deliver of the same webhook-id is a skip: zero new POSTs.

    What would make this fail: minting a new id every call so run-twice
    double-fires the partner, or POSTing before the idempotency check.
    """
    from core.partner_webhooks import (
        FakeWebhookSink,
        deliver_partner_webhook,
        reset_delivery_state,
    )

    reset_delivery_state()
    _public_dns(monkeypatch)
    partner = _partner(slug="wh-twice", url="https://hooks.partner.example/events")
    sink = FakeWebhookSink()
    event = _event("msg_t1_twice")
    first = deliver_partner_webhook(partner, event, sink=sink)
    assert first["status"] == "delivered"
    mutating = list(sink.mutating_calls())
    assert mutating, "first delivery must POST so the second can skip"
    second = deliver_partner_webhook(partner, event, sink=sink)
    assert second["status"] == "skipped"
    assert sink.mutating_calls()[len(mutating):] == []

"""MON-DEADMAN-EXTERNAL (D-039): the ping proves a COMPLETED cycle, and the
ping's own failure is a Finding — never silence.

The receiver URL is a vault secret resolved by ref (settings carry only the
ref); a failed or unreachable POST files one deduped Finding with a stable
fingerprint, because the failure mode §5 exists to kill is a misconfigured
URL being permanent silence.
"""
import pytest
from django.conf import settings

from core.models import AuditEvent, Finding

pytestmark = pytest.mark.django_db

RECEIVER_URL = "https://hc-ping.example/0000-1111-2222-3333"


class RecordingGet:
    def __init__(self, status=200, per_url=None):
        self.status = status
        self.per_url = per_url or {}
        self.calls = []

    def __call__(self, url, *, host=None, timeout=None):
        self.calls.append(url)
        outcome = self.per_url.get(url, self.status)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class RecordingPost:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def __call__(self, url, *, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        if isinstance(self.status, Exception):
            raise self.status
        return self.status


def _plant_receiver_url(url=RECEIVER_URL):
    from vault import service as vault_service

    return vault_service.put(
        kind="api_token",
        owner_type="deadman",
        owner_id=settings.HUB_DEADMAN_URL_REF,
        plaintext=url.encode(),
    )


def test_ping_only_after_every_target_completed():
    from uptime_fixtures import make_site

    from monitor.deadman import ping_after_cycle
    from monitor.uptime import probe_cycle

    make_site("blog")
    make_site("scan", exposure="mesh_only")
    _plant_receiver_url()
    post = RecordingPost(status=200)

    cycle = probe_cycle(http_get=RecordingGet(status=200))
    assert cycle["completed"] is True and cycle["n"] == 2

    outcome = ping_after_cycle(cycle, http_post=post)

    assert outcome["pinged"] is True and outcome["ok"] is True
    assert len(post.calls) == 1
    assert post.calls[0]["url"] == RECEIVER_URL, "the URL must come from the vault"
    assert post.calls[0]["timeout"] is not None, "dead-man POST timeout must be bounded"
    # The receiver URL is a secret-bearing capability: it must not appear in
    # the audit trail the ping writes.
    for event in AuditEvent.objects.all():
        assert RECEIVER_URL not in str(event.detail)


def test_partial_cycle_does_not_ping():
    from monitor.deadman import ping_after_cycle

    _plant_receiver_url()
    post = RecordingPost(status=200)

    outcome = ping_after_cycle({"completed": False, "n": 2}, http_post=post)

    assert outcome["pinged"] is False
    assert post.calls == []


def test_exception_mid_cycle_does_not_ping():
    from uptime_fixtures import make_site

    from monitor.deadman import ping_after_cycle
    from monitor.uptime import probe_cycle

    site_a = make_site("blog")
    make_site("scan", exposure="mesh_only")
    _plant_receiver_url()
    post = RecordingPost(status=200)

    # An unreachable site is a DOWN result, not an incomplete cycle — but an
    # unexpected internal error mid-cycle means the pipeline did NOT prove
    # itself end-to-end, so the ping must not fire (§C7).
    boom_url = f"https://{site_a.domain}{site_a.liveness_path}"
    get = RecordingGet(status=200, per_url={boom_url: RuntimeError("boom")})

    cycle = probe_cycle(http_get=get)
    assert cycle["completed"] is False

    outcome = ping_after_cycle(cycle, http_post=post)
    assert outcome["pinged"] is False
    assert post.calls == []


def test_failed_ping_files_its_own_finding():
    from monitor.deadman import DEADMAN_FINDING_FINGERPRINT, ping

    _plant_receiver_url()

    # Non-2xx receiver: one Finding, not silence.
    outcome = ping(http_post=RecordingPost(status=500))
    assert outcome["ok"] is False
    finding = Finding.objects.get(fingerprint=DEADMAN_FINDING_FINGERPRINT)
    assert finding.state == Finding.State.OPEN
    first_seen, last_seen = finding.first_seen, finding.last_seen

    # A minute later it fails again: same fingerprint, same row — deduped,
    # never one Finding per minute.
    ping(http_post=RecordingPost(status=OSError("unreachable")))
    assert Finding.objects.filter(
        fingerprint=DEADMAN_FINDING_FINGERPRINT).count() == 1
    finding.refresh_from_db()
    assert finding.first_seen == first_seen
    assert finding.last_seen >= last_seen

    # The Finding body must not leak the receiver URL either.
    assert RECEIVER_URL not in finding.body
    assert RECEIVER_URL not in finding.title


def test_failed_ping_publishes_on_the_findings_topic(monkeypatch):
    """Dead-man filing is the canonical findings stream, not a silent ORM row.

    What would make this fail: _file_finding creating the row without
    core.findings.finding(), so RT-35 never refreshes the inbox.
    """
    from monitor.deadman import DEADMAN_FINDING_FINGERPRINT, ping

    published = []
    monkeypatch.setattr(
        "core.events.publish",
        lambda topic, event, **_kw: published.append((topic, event)),
    )
    _plant_receiver_url()
    ping(http_post=RecordingPost(status=500))
    topics = [topic for topic, _event in published]
    assert "findings" in topics
    assert any(
        event.get("fingerprint") == DEADMAN_FINDING_FINGERPRINT
        for _topic, event in published
    )


def test_recurrence_reopens_a_resolved_finding():
    from monitor.deadman import DEADMAN_FINDING_FINGERPRINT, ping

    _plant_receiver_url()
    ping(http_post=RecordingPost(status=500))
    finding = Finding.objects.get(fingerprint=DEADMAN_FINDING_FINGERPRINT)

    # Operator resolves it; the POST fails again next minute. A resolved
    # finding staying resolved would be the D-039 permanent-silence hole.
    finding.state = Finding.State.RESOLVED
    finding.save(update_fields=["state"])
    ping(http_post=RecordingPost(status=500))

    finding.refresh_from_db()
    assert finding.state == Finding.State.OPEN
    assert Finding.objects.filter(
        fingerprint=DEADMAN_FINDING_FINGERPRINT).count() == 1


def test_recurrence_leaves_an_acked_finding_acked():
    from monitor.deadman import DEADMAN_FINDING_FINGERPRINT, ping

    _plant_receiver_url()
    ping(http_post=RecordingPost(status=500))
    finding = Finding.objects.get(fingerprint=DEADMAN_FINDING_FINGERPRINT)

    # Ack != resolve (§F2): an acked finding stays acked on recurrence —
    # the operator has already seen it; only last_seen moves.
    finding.state = Finding.State.ACKED
    finding.save(update_fields=["state"])
    last_seen = finding.last_seen
    ping(http_post=RecordingPost(status=500))

    finding.refresh_from_db()
    assert finding.state == Finding.State.ACKED
    assert finding.last_seen >= last_seen


def test_zero_target_cycle_does_not_ping():
    from monitor.deadman import ping_after_cycle
    from monitor.uptime import probe_cycle

    # No sites at all: the cycle "completes" trivially, but the ping asserts
    # "probing works", not "the Hub process is alive" — a receiver vouching
    # for a Hub that monitors nothing is a lie, so the ping is skipped and
    # the reason + fleet size are recorded.
    _plant_receiver_url()
    post = RecordingPost(status=200)

    cycle = probe_cycle(http_get=RecordingGet(status=200))
    assert cycle["completed"] is True and cycle["n"] == 0

    outcome = ping_after_cycle(cycle, http_post=post)

    assert outcome["pinged"] is False
    assert outcome["reason"] == "empty-fleet"
    assert outcome["n"] == 0, "fleet size must be observable in the record"
    assert post.calls == []


def test_deadman_url_is_a_vault_ref_not_a_settings_literal():
    import inspect

    import monitor.deadman as module

    # The setting is a vault owner-id ref, never the receiver URL.
    ref = settings.HUB_DEADMAN_URL_REF
    assert not str(ref).lower().startswith(("http://", "https://"))

    # And the module holds no receiver-URL literal of its own.
    source = inspect.getsource(module)
    assert "hc-ping" not in source and "healthchecks.io" not in source

    # A missing secret is the misconfiguration §5 exists to catch: it files
    # the same Finding rather than silently skipping the POST forever.
    from monitor.deadman import DEADMAN_FINDING_FINGERPRINT, ping

    post = RecordingPost(status=200)
    outcome = ping(http_post=post)
    assert outcome["ok"] is False
    assert post.calls == []
    assert Finding.objects.filter(
        fingerprint=DEADMAN_FINDING_FINGERPRINT).exists()

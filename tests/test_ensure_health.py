"""ensure_health_check: cutover gates on ready, not live; stuck warm fails fast (S4)."""
import json

import pytest

from core.transport import CommandResult, FakeTransport


class CurlHealthTransport(FakeTransport):
    """Production path: scripted probe-curl results, inspect is probe-only."""

    def __init__(self, curl_results):
        super().__init__()
        self._curl_results = list(curl_results)
        self.curl_probes = []

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv and argv[0] == "curl":
            self.curl_probes.append(argv)
            if not self._curl_results:
                raise AssertionError("unexpected extra curl probe")
            return CommandResult(argv, **self._curl_results.pop(0))
        if argv[:2] == ["docker", "inspect"]:
            return CommandResult(argv, stdout="10.0.0.9")
        return CommandResult(argv)


def _payload(*, live=True, ready=False, checks=None):
    return {"live": live, "ready": ready, "checks": checks if checks is not None else {}}


def _sequenced_fetch(payloads):
    remaining = list(payloads)

    def fetch():
        if not remaining:
            raise AssertionError("healthz_fetch called more times than scripted")
        return remaining.pop(0)

    fetch.remaining = remaining
    return fetch


def _desired(transport, *, fetch, sleep=None, now=None, poll_interval_s=0,
             warmup_timeout_s=60, site=None):
    desired = {
        "transport": transport,
        "site_slug": "app",
        "deployment_id": 7,
        "manifest_body": {"warmup_timeout_s": warmup_timeout_s},
        "image_tag": "abc123-deadbeefdeadbeef",
        "healthz_fetch": fetch,
        "sleep": sleep if sleep is not None else (lambda _s: None),
        "poll_interval_s": poll_interval_s,
    }
    if now is not None:
        desired["now"] = now
    if site is not None:
        desired["site"] = site
    return desired


def _caddy_mutating(transport):
    found = []
    for kind, payload in transport.mutating_calls():
        blob = payload if isinstance(payload, str) else " ".join(
            str(p) for p in payload
        )
        if "caddy" in blob.lower():
            found.append((kind, payload))
    return found


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_cutover_waits_for_ready():
    """Live-but-not-ready on the first poll is not success; wait for ready.

    What would make this fail: returning success on the first {live: true,
    ready: false} payload, or PUT-ing a Caddy route before ready.
    """
    from deploys.steps import ensure_health_check

    fetches = []
    payloads = [
        _payload(live=True, ready=False, checks={"backfill_pct": 10}),
        _payload(live=True, ready=True, checks={"backfill_pct": 100}),
    ]

    def fetch():
        payload = payloads[len(fetches)]
        fetches.append(payload)
        return payload

    transport = FakeTransport()
    result = ensure_health_check(_desired(transport, fetch=fetch))
    assert len(fetches) > 1
    assert fetches[0]["live"] is True
    assert fetches[0]["ready"] is False
    assert fetches[-1]["ready"] is True
    assert result.get("status") != "failed"
    assert _caddy_mutating(transport) == []


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_warming_progress_waits():
    """Changing checks while not ready means keep polling until ready.

    What would make this fail: treating the first warming payload as stuck or
    as success, or raising before a later poll reports ready: true.
    """
    from deploys.steps import ensure_health_check

    fetches = []
    payloads = [
        _payload(live=True, ready=False, checks={"backfill_pct": 10, "feed_age_s": 90}),
        _payload(live=True, ready=False, checks={"backfill_pct": 40, "feed_age_s": 40}),
        _payload(live=True, ready=True, checks={"backfill_pct": 100, "feed_age_s": 1}),
    ]

    def fetch():
        payload = payloads[len(fetches)]
        fetches.append(payload)
        return payload

    transport = FakeTransport()
    ensure_health_check(_desired(transport, fetch=fetch, warmup_timeout_s=60))
    assert len(fetches) > 1
    assert fetches[-1]["ready"] is True
    assert _caddy_mutating(transport) == []


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_stuck_warm_fails_before_timeout_if_checks_frozen():
    """Deep-equal checks while not ready fail immediately, not after warmup_timeout_s.

    What would make this fail: looping until the timeout when checks are frozen,
    or treating a stuck warm as still-progressing.
    """
    from deploys.steps import ensure_health_check

    clock = {"t": 0.0}
    sleeps = []

    def now():
        return clock["t"]

    def sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    frozen = {"backfill_pct": 10, "feed_age_s": 90}
    fetch = _sequenced_fetch([
        _payload(live=True, ready=False, checks=dict(frozen)),
        _payload(live=True, ready=False, checks=dict(frozen)),
        _payload(live=True, ready=True, checks={"backfill_pct": 100}),
    ])
    transport = FakeTransport()
    with pytest.raises(RuntimeError):
        ensure_health_check(_desired(
            transport,
            fetch=fetch,
            sleep=sleep,
            now=now,
            poll_interval_s=1,
            warmup_timeout_s=60,
        ))
    assert clock["t"] < 60
    assert fetch.remaining, "must not keep polling through a frozen-checks failure"
    assert _caddy_mutating(transport) == []


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_liveness_is_not_the_cutover_gate():
    """live true with ready false must not pass the health gate.

    What would make this fail: gating cutover (or returning success) on live
    alone, ignoring ready.
    """
    from deploys.steps import ensure_health_check

    fetches = []

    def fetch():
        payload = _payload(live=True, ready=False, checks={"ok": True})
        fetches.append(payload)
        return payload

    transport = FakeTransport()
    with pytest.raises(RuntimeError):
        ensure_health_check(_desired(
            transport,
            fetch=fetch,
            poll_interval_s=0,
            warmup_timeout_s=60,
        ))
    assert fetches
    assert all(p["live"] is True and p["ready"] is False for p in fetches)
    assert _caddy_mutating(transport) == []


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_curl_misses_retry_until_ready():
    """Two probe-curl misses after docker run are a boot, not a frozen warm.

    What would make this fail: synthesizing checks: {} on a failed curl so the
    second miss raises frozen-checks, instead of retrying until ready.
    """
    from deploys.steps import ensure_health_check

    miss = {"exit_code": 1, "stdout": "", "stderr": "connection refused"}
    ready = {
        "exit_code": 0,
        "stdout": json.dumps({
            "live": True, "ready": True, "checks": {"backfill_pct": 100},
        }),
    }
    transport = CurlHealthTransport([miss, miss, ready])
    result = ensure_health_check({
        "transport": transport,
        "site_slug": "app",
        "deployment_id": 7,
        "manifest_body": {"warmup_timeout_s": 60},
        "image_tag": "abc123-deadbeefdeadbeef",
        "sleep": lambda _s: None,
        "poll_interval_s": 0,
    })
    assert result["status"] == "ready"
    assert len(transport.curl_probes) == 3
    curls = [
        (kind, argv) for kind, argv in transport.calls
        if isinstance(argv, list) and argv[:1] == ["curl"]
    ]
    assert curls
    assert all(kind == "probe" for kind, argv in curls)
    assert _caddy_mutating(transport) == []

"""T1: the daily SEC-B5 token-scope audit (Task 2) — defense-in-depth behind
dns_provider_for's wall, never a second spelling of it.

The audit observes every DnsAccount credential through the SAME pinned
verify + zone-set probe the registry uses at construction (D-046), judges the
observation against the account's declared zone rows, and files one P2
Finding per stable fingerprint on drift. urlopen is doubled per token;
nothing here opens a socket, and nothing here mutates Cloudflare.
"""
import json

import pytest
from test_cloudflare_adapter import _Resp

VERIFY_PATH = "/user/tokens/verify"
PROBE_PATH = "/zones?per_page=50"

DNS_TOKEN = "t1-audit-dns-token-not-a-credential"  # nosec B105 — a test constant
EDGE_TOKEN = "t1-audit-edge-token-not-a-credential"  # nosec B105 — a test constant

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_scope_cache():
    import providers.registry as registry

    registry.reset_scope_cache()
    yield
    registry.reset_scope_cache()


class TokenRoutedFake:
    """urlopen double keyed by (token, method, path): the audit drives two
    different credentials (dns + edge) at the same endpoints, so the canned
    answer must depend on WHICH token asked. Records every request."""

    def __init__(self):
        self.routes = {}  # (token, method, path) -> payload dict | Exception
        self.requests = []  # (token, method, path)

    def route(self, token, *, status="active", zones=(), result_info=None):
        self.routes[(token, "GET", VERIFY_PATH)] = {
            "success": True, "result": {"id": "tok", "status": status},
        }
        body = {
            "success": True,
            "result": [{"id": zid, "name": name} for zid, name in zones],
        }
        if result_info is not None:
            body["result_info"] = result_info
        self.routes[(token, "GET", PROBE_PATH)] = body

    def __call__(self, request, timeout=None):
        from providers.cloudflare import API

        assert request.full_url.startswith(API), request.full_url
        path = request.full_url[len(API):]
        method = request.get_method()
        auth = request.get_header("Authorization") or ""
        token = auth.removeprefix("Bearer ")
        self.requests.append((token, method, path))
        outcome = self.routes.get((token, method, path))
        if outcome is None:
            raise AssertionError(f"unrouted Cloudflare call: {method} {path}")
        if isinstance(outcome, Exception):
            raise outcome
        return _Resp(outcome)

    def methods(self):
        return [method for _, method, _ in self.requests]


def _http(monkeypatch):
    import providers.cloudflare as cloudflare

    http = TokenRoutedFake()
    monkeypatch.setattr(cloudflare, "urlopen", http)
    return http


def _account(*, label="audit-acct", dns_token=DNS_TOKEN, edge_token=None,
             zones=(("zid-a", "audit.example"),), origin_ref=""):
    """A DnsAccount with vaulted credentials and declared DnsZone rows."""
    from core.models import DnsAccount, DnsZone
    from vault import service as vault_service

    account = DnsAccount.objects.create(
        provider="cloudflare", label=label, origin_ca_key_ref=origin_ref,
    )
    if dns_token is not None:
        ref = f"dnsacct-{account.pk}-dns"
        vault_service.put(kind="api_token", owner_type="dns_account",
                          owner_id=ref, plaintext=dns_token.encode())
        account.dns_token_ref = ref
    if edge_token is not None:
        ref = f"dnsacct-{account.pk}-edge"
        vault_service.put(kind="api_token", owner_type="dns_account",
                          owner_id=ref, plaintext=edge_token.encode())
        account.edge_token_ref = ref
    account.save()
    for zid, name in zones:
        DnsZone.objects.create(account=account, name=name, provider_zone_id=zid)
    return account


def _findings():
    from core.models import Finding

    return Finding.objects.filter(fingerprint__startswith="cf-token-scope:")


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_exact_minimum_scope_is_clean(monkeypatch):
    """An active token reaching exactly the declared zone set files nothing.

    What would make this fail: the audit treating its own observation as
    drift — a clean daily run that cries wolf trains the operator to ignore
    the one Finding that will matter.
    """
    from core.models import CheckRun
    from monitor.token_audit import audit_cloudflare_credentials

    _account(zones=(("zid-a", "audit.example"),), origin_ref="oca-1")
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(("zid-a", "audit.example"),))

    run = audit_cloudflare_credentials()
    assert run.kind == CheckRun.Kind.CF_TOKEN_SCOPE
    assert run.status == CheckRun.Status.SUCCEEDED
    assert _findings().count() == 0


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_one_row_page_with_total_count_2_files_audit_finding(monkeypatch):
    """The daily audit uses the same set-size fact as the wall (D-046).

    What would make this fail: judging only the visible page rows so a
    one-row page of a two-zone token looks like the declared minimum.
    """
    from core.models import Finding
    from monitor.token_audit import audit_cloudflare_credentials

    account = _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.route(
        DNS_TOKEN,
        zones=(("zid-a", "audit.example"),),
        result_info={"page": 1, "per_page": 50, "total_count": 2},
    )

    audit_cloudflare_credentials()
    finding = _findings().get()
    assert finding.severity == Finding.Severity.P2
    assert finding.state == Finding.State.OPEN
    assert finding.fingerprint == f"cf-token-scope:{account.pk}:dns"
    assert DNS_TOKEN not in finding.body


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_excess_zone_access_files_a_p2_finding(monkeypatch):
    """A token reachable for a zone no DnsZone row names is drift: one P2.

    What would make this fail: only checking that the declared zone is IN
    the probed set — the whole point of SEC-B5 is catching the token that
    quietly grew access to a second zone.
    """
    from core.models import Finding
    from monitor.token_audit import audit_cloudflare_credentials

    account = _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(
        ("zid-a", "audit.example"), ("zid-crept", "crept.example"),
    ))

    audit_cloudflare_credentials()
    finding = _findings().get()
    assert finding.severity == Finding.Severity.P2
    assert finding.state == Finding.State.OPEN
    assert finding.fingerprint == f"cf-token-scope:{account.pk}:dns"
    assert "crept.example" in finding.body
    assert DNS_TOKEN not in finding.body
    assert DNS_TOKEN not in finding.title


def test_drift_finding_publishes_on_the_findings_topic(monkeypatch):
    """Token-audit drift is the canonical findings stream (D-045).

    What would make this fail: _file_drift_finding get_or_create without
    finding(), so the inbox never sees daily SEC-B5 drift.
    """
    from monitor.token_audit import audit_cloudflare_credentials

    published = []
    monkeypatch.setattr(
        "core.events.publish",
        lambda topic, event, **_kw: published.append((topic, event)),
    )
    account = _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(
        ("zid-a", "audit.example"), ("zid-crept", "crept.example"),
    ))
    audit_cloudflare_credentials()
    assert any(topic == "findings" for topic, _event in published)
    assert any(
        event.get("fingerprint") == f"cf-token-scope:{account.pk}:dns"
        for _topic, event in published
    )


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_global_api_key_shape_is_refused_not_warned(monkeypatch):
    """A Global-API-Key credential never reaches the wire AND files a P2.

    What would make this fail: sending the legacy key to verify and letting
    Cloudflare's answer grade it — the shape refusal must happen pre-network
    (the key is omnipotent; even a GET with it is an exposure), and the
    outcome must be a Finding the operator sees, not a log line.
    """
    from monitor.token_audit import audit_cloudflare_credentials

    global_key = json.dumps(
        {"X-Auth-Key": "gk-abc123", "X-Auth-Email": "op@example.com"}
    )
    account = _account(dns_token=global_key)
    http = _http(monkeypatch)

    run = audit_cloudflare_credentials()
    assert http.requests == []  # refused by shape, before any request
    finding = _findings().get()
    assert finding.fingerprint == f"cf-token-scope:{account.pk}:dns"
    assert "gk-abc123" not in finding.body
    assert "gk-abc123" not in json.dumps(run.results)


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_inactive_token_files_a_finding(monkeypatch):
    """verify returning anything but active is drift, not a skip.

    What would make this fail: auditing only the zone set — a disabled token
    probes zero zones, which a naive 'no excess' check reads as clean.
    """
    from monitor.token_audit import audit_cloudflare_credentials

    account = _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, status="disabled")

    audit_cloudflare_credentials()
    finding = _findings().get()
    assert finding.fingerprint == f"cf-token-scope:{account.pk}:dns"
    assert "disabled" in finding.body
    # The shared helper never probes zones with a token verify already failed.
    assert [path for _, _, path in http.requests] == [VERIFY_PATH]


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
@pytest.mark.parametrize("http_status", [401, 403])
def test_revoked_token_is_drift_not_an_observation_error(monkeypatch, http_status):
    """A 401/403 at verify is the token being dead, not Cloudflare being down:
    it files the drift Finding and the run result records the credential as
    drifted, on a SUCCEEDED CheckRun (the audit observed and judged fine).

    What would make this fail: routing every CloudflareApiError into
    {"status": "error"} — a revoked token (the STRONGER form of the inactive
    drift) then hides inside the same FAILED CheckRun as a network blip, and
    no Finding ever reaches the operator.
    """
    from urllib.error import HTTPError

    from core.models import CheckRun
    from monitor.token_audit import audit_cloudflare_credentials

    account = _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.routes[(DNS_TOKEN, "GET", VERIFY_PATH)] = HTTPError(
        "u", http_status, "denied", {}, None,
    )

    run = audit_cloudflare_credentials()
    assert run.status == CheckRun.Status.SUCCEEDED
    finding = _findings().get()
    assert finding.fingerprint == f"cf-token-scope:{account.pk}:dns"
    assert str(http_status) in finding.body
    assert "revoked" in finding.body
    assert DNS_TOKEN not in finding.body
    entry = run.results["accounts"][0]["credentials"]["dns"]
    assert entry["drift"] == "revoked"


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_api_5xx_is_an_observation_error_not_drift(monkeypatch):
    """A 500 from Cloudflare is a failure to observe: FAILED CheckRun, no
    Finding — the audit reports that it could not see, never a guessed drift.

    What would make this fail: treating every HTTP error as drift, so a
    Cloudflare outage would file a false 'scope drift' P2 against every
    account and train the operator to resolve-without-reading.
    """
    from urllib.error import HTTPError

    from core.models import CheckRun
    from monitor.token_audit import audit_cloudflare_credentials

    _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.routes[(DNS_TOKEN, "GET", VERIFY_PATH)] = HTTPError(
        "u", 500, "boom", {}, None,
    )

    run = audit_cloudflare_credentials()
    assert run.status == CheckRun.Status.FAILED
    assert _findings().count() == 0
    entry = run.results["accounts"][0]["credentials"]["dns"]
    assert entry["status"] == "error"


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_observe_token_refuses_the_global_key_shape_itself(monkeypatch):
    """The exported shared helper is safe by construction: handed a
    Global-API-Key credential directly, it refuses before any request.

    What would make this fail: observe_token trusting its caller to have
    shape-checked — a future consumer (Task 3/8) calling it with a raw vault
    value would put the omnipotent key on the wire inside a Bearer header.
    """
    import providers.cloudflare as cloudflare

    http = _http(monkeypatch)
    global_key = json.dumps(
        {"X-Auth-Key": "gk-direct-999", "X-Auth-Email": "op@example.com"}
    )
    with pytest.raises(cloudflare.CloudflareError):
        cloudflare.observe_token(global_key)
    assert http.requests == []


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_edge_token_ref_is_audited_from_its_model_home(monkeypatch):
    """The edge ref on DnsAccount is a real audited credential (panel r2),
    judged against the same declared zones; its Phase-4 minimum is modelled
    in the run results, not invented per caller.

    What would make this fail: the audit reading only dns_token_ref, leaving
    the edge token — the one that can rewrite firewall rules — unwatched
    until the Phase-4 playbook ships.
    """
    from monitor.token_audit import (
        EDGE_TOKEN_MINIMUM,
        audit_cloudflare_credentials,
    )

    account = _account(
        edge_token=EDGE_TOKEN, zones=(("zid-a", "audit.example"),),
    )
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(("zid-a", "audit.example"),))
    http.route(EDGE_TOKEN, zones=(
        ("zid-a", "audit.example"), ("zid-extra", "extra.example"),
    ))

    run = audit_cloudflare_credentials()
    # The edge credential was resolved from ITS ref and driven over the wire.
    assert (EDGE_TOKEN, "GET", VERIFY_PATH) in http.requests
    finding = _findings().get()
    assert finding.fingerprint == f"cf-token-scope:{account.pk}:edge"
    assert EDGE_TOKEN not in finding.body
    # The §6.5 playbook's minimum is modelled now (used in Phase 4).
    assert set(EDGE_TOKEN_MINIMUM) == {
        "Zone:Firewall Services:Edit", "Zone Settings:Edit",
    }
    assert list(EDGE_TOKEN_MINIMUM) == (
        run.results["accounts"][0]["credentials"]["edge"]["modelled_minimum"]
    )


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_audit_writes_a_checkrun_every_run(monkeypatch):
    """Every run persists a CheckRun(kind=cf_token_scope) — drift or clean.

    What would make this fail: writing the row only on drift, so a silently
    broken audit is indistinguishable from a fleet with nothing to report
    (the exact silence find_missed exists to break).
    """
    from core.models import CheckRun
    from monitor.token_audit import audit_cloudflare_credentials

    _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(("zid-a", "audit.example"),))

    audit_cloudflare_credentials()
    http.route(DNS_TOKEN, zones=(
        ("zid-a", "audit.example"), ("zid-crept", "crept.example"),
    ))
    audit_cloudflare_credentials()

    runs = CheckRun.objects.filter(kind=CheckRun.Kind.CF_TOKEN_SCOPE)
    assert runs.count() == 2
    for run in runs:
        assert run.status == CheckRun.Status.SUCCEEDED
        assert run.finished is not None
        assert "schema_version" in run.results


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_audit_makes_no_mutating_api_call(monkeypatch):
    """The audit observes: GETs only, on clean and drifting accounts alike.

    What would make this fail: an audit that 'fixes' what it finds —
    deleting records or rolling tokens is enforcement, and enforcement
    lives at construction (D-034: a finding is not enforcement, and the
    inverse holds too).
    """
    from monitor.token_audit import audit_cloudflare_credentials

    _account(label="clean", zones=(("zid-a", "audit.example"),))
    _account(label="drifty", dns_token=EDGE_TOKEN,
             zones=(("zid-b", "drift.example"),))
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(("zid-a", "audit.example"),))
    http.route(EDGE_TOKEN, zones=(
        ("zid-b", "drift.example"), ("zid-x", "x.example"),
    ))

    audit_cloudflare_credentials()
    assert http.requests != []
    assert set(http.methods()) == {"GET"}


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_audit_and_construction_share_one_verification_helper(monkeypatch):
    """One spelling of the pinned observation: both dns_provider_for and the
    audit route through providers.cloudflare.observe_token.

    What would make this fail: the audit re-implementing verify+probe with
    its own literals — the two spellings then drift, and the audit ends up
    blessing tokens the wall refuses (or vice versa), which is exactly the
    defense-in-depth failure SEC-B5 warns about.
    """
    import pathlib

    import providers.cloudflare as cloudflare
    from monitor.token_audit import audit_cloudflare_credentials
    from providers.registry import dns_provider_for

    calls = []
    real = cloudflare.observe_token

    def spy(token, **kwargs):
        # The audit hands observe_token the RAW vault bytes (the helper is
        # safe by construction and shape-refuses/decodes itself); normalize
        # for comparison against the registry's already-decoded pass.
        calls.append(token.decode() if isinstance(token, bytes) else token)
        return real(token, **kwargs)

    monkeypatch.setattr(cloudflare, "observe_token", spy)

    account = _account(zones=(("zid-a", "audit.example"),))
    zone = account.zones.get()
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(("zid-a", "audit.example"),))

    dns_provider_for(zone)
    assert calls == [DNS_TOKEN], "construction must route through observe_token"

    audit_cloudflare_credentials()
    assert calls == [DNS_TOKEN, DNS_TOKEN], "the audit must reuse the same helper"

    # And neither judge can re-spell the endpoints: only api_request builds a
    # Cloudflare URL, and neither consumer calls it (docstrings may narrate
    # the pinned paths; code may not drive them).
    import ast

    repo = pathlib.Path(__file__).resolve().parent.parent
    for rel in ("providers/registry.py", "monitor/token_audit.py"):
        tree = ast.parse((repo / rel).read_text(encoding="utf-8"))
        callers = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
            == "api_request"
        ]
        assert callers == [], f"{rel} spells its own Cloudflare call: {callers}"


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_beat_entry_runs_the_audit_daily_on_queue_probes(monkeypatch):
    """cf-token-scope-daily exists, names the task, rides queue probes, and
    the task body carries no credential material in args or return value.

    What would make this fail: an audit with no scheduler owner (the exact
    'implied behaviour' the panel banned), or a Beat entry smuggling a token
    through kwargs where Flower and the result backend would log it.
    """
    from django.conf import settings

    from core.models import CheckRun
    from monitor import tasks as monitor_tasks

    entry = settings.CELERY_BEAT_SCHEDULE["cf-token-scope-daily"]
    assert entry["task"] == monitor_tasks.audit_cf_token_scope.name
    assert float(entry["schedule"]) == 86400.0
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "control"
    assert "kwargs" not in entry  # no args at all, so never a token in args

    _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(("zid-a", "audit.example"),))
    outcome = monitor_tasks.audit_cf_token_scope()
    assert outcome["kind"] == CheckRun.Kind.CF_TOKEN_SCOPE
    assert DNS_TOKEN not in json.dumps(outcome)
    assert CheckRun.objects.filter(kind=CheckRun.Kind.CF_TOKEN_SCOPE).exists()


@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_finding_fingerprint_is_stable_across_runs(monkeypatch):
    """The same drift on the same credential is ONE Finding, updated in
    place — and a resolved one re-opens if the drift is still there.

    What would make this fail: a timestamp or the probed zone list leaking
    into the fingerprint, so every daily run files a fresh row and the
    Findings queue becomes a log file.
    """
    from core.models import Finding
    from monitor.token_audit import audit_cloudflare_credentials

    _account(zones=(("zid-a", "audit.example"),))
    http = _http(monkeypatch)
    http.route(DNS_TOKEN, zones=(
        ("zid-a", "audit.example"), ("zid-crept", "crept.example"),
    ))

    audit_cloudflare_credentials()
    first = _findings().get()
    audit_cloudflare_credentials()
    second = _findings().get()
    assert second.pk == first.pk
    assert second.fingerprint == first.fingerprint
    assert second.last_seen >= first.last_seen

    second.state = Finding.State.RESOLVED
    second.save(update_fields=["state"])
    audit_cloudflare_credentials()
    assert _findings().get().state == Finding.State.OPEN
    assert _findings().count() == 1

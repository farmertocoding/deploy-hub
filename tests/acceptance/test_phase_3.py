"""Phase 3 acceptance — each test transcribes one milestone clause
(phase-3-design-note.md §3 / §4 exit demo). `check.py --phase 3` requires the
ids these mark to be green, or an honest WAIVERS.md line.

T1 clauses run in review-round. Live CF/LE stay on their existing t3 files
behind `multipass_available()` + the credential skip; this module never marks
those ids (a T1 sibling must not green a skipped-only tier:t3 req).

Every T1 body here asserts the same properties an existing named proof asserts
(transcription, not fiction); each docstring names its source test.

No `@pytest.mark.req` on the full-text SEC-B2 or UX-F5 ids (SCAN-M4 shape).
"""
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent

WAIVER_24H = "REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven"
FULL_TEXT_SEC_B2 = "SEC-B2-NO-DNS-TOKENS-ON-TARGETS"
FULL_TEXT_UX_F5 = "UX-F5-ACTION-TIERS"
ADOPT_IDS = ("PROV-J7-COMPOSE-AWARE-ADOPT", "PROV-E6-ADOPT-TEMP-SUBDOMAIN")

pytestmark = [pytest.mark.acceptance(phase=3)]


def _waivers():
    return (REPO / "WAIVERS.md").read_text(encoding="utf-8")


def _demo():
    return (REPO / "conformance" / "demos" / "phase-3.md").read_text(encoding="utf-8")


def _registry():
    data = yaml.safe_load(
        (REPO / "conformance" / "requirements.yaml").read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["requirements"]}


def _waiver_lines(fingerprint):
    prefix = f"WAIVED: {fingerprint} "
    return [line for line in _waivers().splitlines() if line.startswith(prefix)]


# ── named clauses ───────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_product_adapter_refuses_an_over_scoped_token_at_construction(monkeypatch):
    """Construction refuses a two-zone token before a client exists (D-034/D-046).

    Transcribes tests/test_dns_zone_wall.py::test_two_zone_probe_result_refuses_construction:
    verify then GET /zones?per_page=50, excess access raises ScopeError, no
    client is returned.
    """
    from test_dns_zone_wall import _http, _routes, _zone

    from providers.registry import ScopeError, dns_provider_for

    zone = _zone()
    http = _http(monkeypatch, _routes(zone, zones=[
        {"id": zone.provider_zone_id, "name": zone.name},
        {"id": "zid-other", "name": "other.example"},
    ]))

    with pytest.raises(ScopeError):
        dns_provider_for(zone)
    assert [req[1] for req in http.requests] == [
        "/user/tokens/verify", "/zones?per_page=50",
    ]


@pytest.mark.django_db
@pytest.mark.req("SEC-B2-NO-TOKEN-ON-TARGET")
def test_no_dns_token_reaches_any_target_bound_surface():
    """Every target-bound surface is scanned; planted DNS/edge/OCA never land.

    Transcribes tests/test_no_token_exfiltration.py::test_no_dns_token_in_put_payloads,
    ::test_no_dns_token_in_run_argv, ::test_no_dns_token_in_env_files_or_env_snapshots,
    ::test_no_dns_token_in_deployment_artifacts_or_manifest,
    ::test_no_dns_token_in_generated_caddy_or_dockerfile_text,
    ::test_recorded_transport_call_log_is_token_free,
    ::test_no_dns_token_in_celery_task_kwargs, and
    ::test_no_acme_dns_challenge_block_is_ever_generated. Does not mark the
    full-text SEC-B2 id.
    """
    from django.conf import settings
    from test_no_token_exfiltration import (
        ACME_MARKERS,
        _artifact_and_generated,
        _assert_clean,
        _blobify,
        _call_log_blob,
        _env_surfaces,
        _put_payloads,
        _run_argv_blobs,
        _simulate_deploy,
    )

    from deploys.tasks import run_deploy

    _site, deployment, transport = _simulate_deploy("p3-exfil")
    assert deployment.status == "succeeded"
    _assert_clean(_put_payloads(transport), where="put payload")
    _assert_clean(_run_argv_blobs(transport), where="run argv")
    _assert_clean(_env_surfaces(deployment, transport), where="env file/snapshot")
    _assert_clean(
        [deployment.manifest.body],
        where="artifact/manifest",
    )
    _assert_clean(_artifact_and_generated(deployment, transport), where="caddy/dockerfile")
    _assert_clean([_call_log_blob(transport)], where="transport call log")
    sig = run_deploy.s(deployment.pk)
    _assert_clean([sig.args, sig.kwargs, sig.options], where="celery signature")
    _assert_clean(
        [settings.CELERY_BEAT_SCHEDULE],
        where="CELERY_BEAT_SCHEDULE",
    )
    for blob in _artifact_and_generated(deployment, transport) + _put_payloads(transport):
        text = _blobify(blob).decode("utf-8", "replace").lower()
        for marker in ACME_MARKERS:
            assert marker not in text, f"ACME/DNS-01 marker {marker!r} was generated"


@pytest.mark.django_db
@pytest.mark.req("SEC-B5-CF-TOKEN-SCOPING")
def test_token_scope_audit_files_a_finding_on_excess(monkeypatch):
    """A token that grew a second zone files one P2, never the token itself.

    Transcribes tests/test_cf_token_audit.py::test_excess_zone_access_files_a_p2_finding.
    """
    from test_cf_token_audit import DNS_TOKEN, _account, _findings, _http

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


@pytest.mark.django_db
def test_origin_cert_key_is_vaulted_pushed_0400_and_matched():
    """T1 origin-cert lifecycle: vault-first, atomic 0400 in 0700, match.

    Transcribes tests/test_origin_certs.py::test_key_is_vaulted_before_the_first_push,
    ::test_key_written_atomically_0400_in_a_0700_root_dir, and
    ::test_key_cert_mismatch_refuses_before_reload. Does NOT mark
    TLS-B2-ORIGIN-CERT-PUSH — that id is tier:t2 and lives on
    tests/test_t2_cert_push.py (D-024: a T1 sibling must not green it).
    """
    from test_origin_certs import (
        MismatchIssuer,
        TlsTransport,
        _desired,
        _has_run,
        _runs,
        _site,
    )

    from deploys.certs import CertKeyMismatch, ensure_site_certificate
    from vault import service as vault_service
    from vault.models import Secret

    order = []
    real_put = vault_service.put

    def vault_spy(**kwargs):
        order.append(("vault", kwargs["kind"]))
        return real_put(**kwargs)

    site = _site(slug="p3-orig")
    transport = TlsTransport()
    desired = _desired(site, transport)
    orig = transport.put

    def put_spy(content, remote_path, *, mode=0o644):
        blob = content if isinstance(content, (bytes, bytearray)) else b""
        if b"PRIVATE KEY" in blob:
            order.append(("put-key", remote_path))
        return orig(content, remote_path, mode=mode)

    transport.put = put_spy
    vault_service.put = vault_spy
    try:
        ensure_site_certificate(desired)
    finally:
        vault_service.put = real_put

    assert ("vault", "tls_private_key") in order
    vault_idx = next(i for i, item in enumerate(order) if item[0] == "vault")
    put_idx = next(i for i, item in enumerate(order) if item[0] == "put-key")
    assert vault_idx < put_idx
    assert Secret.objects.filter(kind=Secret.Kind.TLS_PRIVATE_KEY).exists()

    tls_dir = f"/srv/sites/{site.name}/tls"
    assert _has_run(transport, "mkdir", tls_dir)
    chmod_dir = _has_run(transport, "chmod", tls_dir)
    assert chmod_dir is not None
    assert "0700" in chmod_dir or "700" in chmod_dir
    assert _has_run(transport, "chown", "root:root", tls_dir)
    chmod_key = _has_run(transport, "chmod", "0400") or _has_run(transport, "chmod", "400")
    assert chmod_key is not None
    assert _has_run(transport, "mv")
    key_blob = transport.files.get(f"{tls_dir}/key.pem", b"")
    if isinstance(key_blob, str):
        key_blob = key_blob.encode()
    assert b"PRIVATE KEY" in key_blob

    mismatch = _site(slug="p3-mis")
    bad = TlsTransport()
    with pytest.raises(CertKeyMismatch):
        ensure_site_certificate(_desired(mismatch, bad, cert_issuer=MismatchIssuer()))
    assert bad.reload_count == 0
    assert not any(argv and "caddy" in argv for argv in _runs(bad))

    src = (REPO / "tests" / "test_t2_cert_push.py").read_text(encoding="utf-8")
    assert 'pytest.mark.req("TLS-B2-ORIGIN-CERT-PUSH")' in src
    assert "pytest.mark.t2" in src


@pytest.mark.django_db
@pytest.mark.req("UX-F2-FINDING-MODEL")
def test_unproxied_refusal_is_a_finding_and_a_visible_site_state():
    """Unproxied public sites refuse as a Finding plus a Sites-screen state.

    Transcribes tests/test_origin_certs.py::
    test_unproxied_public_site_refusal_files_a_finding_with_a_fix_action and
    frontend/src/screens/Sites.jsx::CertState (the visible state Task 12/13
    render). Not a marker on the full-text SEC-B2 id.
    """
    from test_origin_certs import TlsTransport, _desired, _site

    from core.models import Finding
    from deploys.certs import UnproxiedCertUnsupported, ensure_site_certificate

    site = _site(slug="p3-bare", proxied=False)
    transport = TlsTransport()
    with pytest.raises(UnproxiedCertUnsupported):
        ensure_site_certificate(_desired(site, transport))

    row = Finding.objects.get()
    assert row.severity == Finding.Severity.P2
    assert "Phase 3b" in row.fix_action
    assert row.title and row.body and row.entity

    sites_src = (REPO / "frontend" / "src" / "screens" / "Sites.jsx").read_text(
        encoding="utf-8")
    assert "export function CertState" in sites_src
    assert "site.cert_refusal" in sites_src
    assert "TLS refused" in sites_src
    assert 'routeHash("findings"' in sites_src


@pytest.mark.req("ALERT-P1-ROWS")
def test_unclassified_alert_kind_cannot_ship():
    """An unregistered kind cannot ship: classify raises (D-037).

    Transcribes tests/test_alert_rules.py::test_unknown_kind_raises_unclassified_alert.
    """
    from monitor.alert_rules import UnclassifiedAlert, classify

    with pytest.raises(UnclassifiedAlert, match="not-a-registered-kind"):
        classify("not-a-registered-kind")


@pytest.mark.django_db
@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
@pytest.mark.req("ALERT-RECOVERY-NOTICE")
def test_three_failures_open_one_p1_and_two_successes_close_it():
    """Open after 3 failures; close after 2 successes with the recovery notice.

    Transcribes tests/test_antinoise.py::test_third_consecutive_failure_opens and
    ::test_two_consecutive_successes_close_and_send_recovery.
    """
    from core.models import AlertState, Finding
    from monitor.antinoise import observe

    fp = "site-down:p3-hysteresis"
    assert observe(fp, False) is None
    assert observe(fp, False) is None
    row = observe(fp, False)
    assert row is not None
    assert row.state == Finding.State.OPEN
    assert AlertState.objects.get(fingerprint=fp).consecutive_fail == 3

    observe(fp, True)
    notice = observe(fp, True)
    assert notice["title"].startswith("UP after")
    assert Finding.objects.get(fingerprint=fp).state == Finding.State.RESOLVED
    assert AlertState.objects.get(fingerprint=fp).closed_at is not None


@pytest.mark.django_db
@pytest.mark.req("ALERT-DELIVERY-BEHAVIORS")
def test_unacked_p1_repeats_on_its_own_beat_entry():
    """Hourly unacked P1 re-push owns Beat alert-repeat-unacked at 300 s.

    Transcribes tests/test_delivery_behaviors.py::
    test_unacked_p1_repeats_hourly_on_its_own_beat_entry and
    ::test_repeat_does_not_depend_on_the_probe_cycle_running.
    """
    from django.conf import settings as dj
    from test_delivery_behaviors import _p1

    from core.models import Finding
    from monitor import tasks as monitor_tasks
    from monitor.alerts import repeat_unacked
    from monitor.pager import get_pager

    entry = dj.CELERY_BEAT_SCHEDULE["alert-repeat-unacked"]
    assert entry["task"] == monitor_tasks.repeat_unacked.name
    assert float(entry["schedule"]) == 300.0
    assert entry["task"] != dj.CELERY_BEAT_SCHEDULE["probe-uptime"]["task"]

    row = _p1(fingerprint="site-down:p3-repeat")
    pager = get_pager()
    first = len(pager.published)
    from datetime import timedelta

    from django.utils import timezone

    now = timezone.now()
    repeat_unacked(now=now + timedelta(minutes=30))
    assert len(pager.published) == first
    repeat_unacked(now=now + timedelta(hours=1))
    assert len(pager.published) == first + 1
    row.refresh_from_db()
    assert row.state == Finding.State.OPEN


@pytest.mark.django_db
@pytest.mark.req("ALERT-DELIVERY-BEHAVIORS")
def test_two_p2_in_ten_minutes_are_one_grouped_push():
    """Two P2s inside ten minutes arrive as one grouped push.

    Transcribes tests/test_antinoise.py::test_two_p2_within_ten_minutes_become_one_grouped_push.
    """
    from test_antinoise import _copy

    from monitor.alerts import raise_alert
    from monitor.antinoise import group_p2

    raise_alert("feed-data-stale", "feed:a", fingerprint="p3-stale:a", **_copy())
    raise_alert("feed-data-stale", "feed:b", fingerprint="p3-stale:b", **_copy())
    pushes = group_p2(window=600)
    assert len(pushes) == 1
    assert pushes[0]["grouped"] is True
    fps = {finding.fingerprint for finding in pushes[0]["findings"]}
    assert fps == {"p3-stale:a", "p3-stale:b"}


@pytest.mark.django_db
@pytest.mark.req("ALERT-ANTINOISE-HYSTERESIS")
def test_host_down_suppression_collapses_site_alerts():
    """Host-down names its sites and swallows their site-down Findings.

    Transcribes tests/test_antinoise.py::test_host_down_suppresses_its_sites_and_names_them.
    """
    from test_antinoise import _fail_until_open, _shared_host_sites

    from core.models import Finding
    from monitor.antinoise import observe, suppressed_by

    target, sites = _shared_host_sites()
    fp = f"host-down:{target.host}"
    row = _fail_until_open(fp)
    assert row is not None
    for site in sites:
        assert f"site:{site.name}" in row.body
        assert suppressed_by(f"site:{site.name}") == f"host:{target.host}"

    observe("site-down:alpha", False)
    observe("site-down:alpha", False)
    observe("site-down:alpha", False)
    assert not Finding.objects.filter(fingerprint="site-down:alpha").exists()


@pytest.mark.django_db
@pytest.mark.req("ALERT-M3-PAGER-AUTH")
def test_push_body_is_minimized_and_scrubbed():
    """Push body has no raw IP, secret, or break-glass command; backend is fake.

    Transcribes tests/test_pager.py::test_push_body_has_no_raw_ip_no_secret_no_break_glass_command
    and ::test_default_backend_in_tests_is_the_fake. HUB_PAGER_BACKEND defaults
    to fake; no test here pages anyone.
    """
    from django.conf import settings
    from test_pager import BREAK_GLASS_CMD, RAW_IP, RAW_SECRET, _file_p1

    from monitor.pager import get_pager, reset_pager
    from providers.fakes import FakePager

    reset_pager()
    try:
        assert settings.HUB_PAGER_BACKEND == "fake"
        assert isinstance(get_pager(), FakePager)

        row = _file_p1(
            entity=f"host:{RAW_IP}",
            fingerprint="site-down:p3-ip-pager",
            title=f"DOWN at {RAW_IP}",
            body=(
                f"Host {RAW_IP} is unreachable. token={RAW_SECRET}. "
                f"Break-glass: {BREAK_GLASS_CMD}"
            ),
        )
        push = get_pager().published[-1]
        blob = f"{push['title']}\n{push['body']}"
        assert RAW_IP not in blob
        assert RAW_SECRET not in blob
        assert "docker restart" not in blob
        assert BREAK_GLASS_CMD not in blob
        assert row.severity in blob
        assert push["click_url"]
    finally:
        reset_pager()


@pytest.mark.django_db
@pytest.mark.req("MON-DEADMAN-EXTERNAL")
def test_deadman_pings_only_after_a_completed_cycle_and_failure_files_a_finding():
    """Dead-man POSTs only after every target completed; a failed POST files.

    Transcribes tests/test_deadman.py::test_ping_only_after_every_target_completed
    and ::test_failed_ping_files_its_own_finding.
    """
    from test_deadman import (
        RECEIVER_URL,
        RecordingGet,
        RecordingPost,
        _plant_receiver_url,
    )
    from uptime_fixtures import make_site

    from core.models import Finding
    from monitor.deadman import DEADMAN_FINDING_FINGERPRINT, ping, ping_after_cycle
    from monitor.uptime import probe_cycle

    make_site("p3-blog")
    make_site("p3-scan", exposure="mesh_only")
    _plant_receiver_url()
    post = RecordingPost(status=200)
    cycle = probe_cycle(http_get=RecordingGet(status=200))
    assert cycle["completed"] is True
    outcome = ping_after_cycle(cycle, http_post=post)
    assert outcome["pinged"] is True and outcome["ok"] is True
    assert post.calls[0]["url"] == RECEIVER_URL

    fail = ping(http_post=RecordingPost(status=500))
    assert fail["ok"] is False
    finding = Finding.objects.get(fingerprint=DEADMAN_FINDING_FINGERPRINT)
    assert finding.state == Finding.State.OPEN
    assert RECEIVER_URL not in finding.body


@pytest.mark.django_db
@pytest.mark.req("MON-C4-LOG-BACKPRESSURE")
def test_log_pull_is_capped_and_degrades_sampled(tmp_path):
    """Over the cap: sampled summary, no raw lines; under the cap raw still travels.

    Transcribes tests/test_log_backpressure.py::test_pull_never_exceeds_the_byte_cap
    and ::test_over_cap_pull_returns_a_sampled_summary.
    """
    from test_log_backpressure import MARKER, _big_log, _line, _run

    import monitor.collect_once as producer

    log = _big_log(tmp_path)
    payload, stdout = _run(log)
    chunk = payload["log_chunk"]
    assert len(chunk.get("bytes", "").encode("utf-8")) <= producer.CHUNK
    assert chunk["sampled"] is True
    assert MARKER not in stdout
    assert chunk["summary"]["requests"] == 900

    small = tmp_path / "p3-small.log"
    small.write_text(_line() + "\n", encoding="utf-8")
    under, _ = _run(small)
    raw = under["log_chunk"]["bytes"]
    assert len(raw.encode("utf-8")) <= producer.CHUNK
    assert MARKER in raw


@pytest.mark.django_db
@pytest.mark.req("UX-F2-FINDING-MODEL")
def test_findings_inbox_requires_a_reason_to_accept_risk():
    """Accept-risk without a one-line reason is refused; findings is canonical.

    Transcribes tests/test_findings.py::test_accept_risk_requires_a_reason and
    tests/test_findings_api.py::test_alerts_alias_delivers_the_same_payload_as_findings
    (D-045: `findings` is the one attention stream).
    """
    from test_findings import _file

    from core.findings import accept_risk
    from core.models import Finding
    from realtime.authorize import DEPRECATED_ALIASES

    row = _file(fingerprint="p3-accept")
    with pytest.raises(ValueError):
        accept_risk(row, "")
    with pytest.raises(ValueError):
        accept_risk(row, "   \t")
    row.refresh_from_db()
    assert row.state == Finding.State.OPEN

    accept_risk(row, "internal-only site; downtime is acceptable")
    row.refresh_from_db()
    assert row.state == Finding.State.ACCEPTED
    assert row.accepted_reason == "internal-only site; downtime is acceptable"

    assert DEPRECATED_ALIASES["alerts"] == "findings"
    auth = (REPO / "realtime" / "authorize.py").read_text(encoding="utf-8")
    assert '"findings"' in auth
    assert "canonical" in auth.lower()


@pytest.mark.req("UX-F5-T2-T3-FRICTION")
def test_rollback_is_one_click_and_never_step_up_gated():
    """T3 rollback/restart/re-run are one click + undo; stepUp is never set.

    Transcribes frontend/tests/actions.test.ts::
    rollback_restart_and_rerun_are_t3_and_never_behind_step_up and
    ::t3_runs_on_one_click_with_an_undo_window. Does not mark the full-text
    UX-F5 id (the T1 hardware clause is unbuilt).
    """
    src = (REPO / "frontend" / "src" / "actions.js").read_text(encoding="utf-8")
    for action_id in ("site.rollback", "site.restart", "check.rerun"):
        assert f'id: "{action_id}", tier: "T3"' in src
    assert (
        'if (row.tier === "T3") return { confirm: false, undo: true, stepUp: "none" }'
        in src
    )
    # T3 click runs immediately: confirm is the T2 path; deferred is T1.
    assert "if (p.confirm)" in src
    assert 'if (p.stepUp === "deferred")' in src
    assert "run(args)" in src
    tests = (REPO / "frontend" / "tests" / "actions.test.ts").read_text(encoding="utf-8")
    assert "rollback_restart_and_rerun_are_t3_and_never_behind_step_up" in tests
    assert "t3_runs_on_one_click_with_an_undo_window" in tests


@pytest.mark.req("RT-35-DEGRADED-POLLING")
def test_ws_unavailable_degrades_to_visible_polling():
    """Unavailable socket → visible 10 s REST polling, never silently stale.

    Transcribes frontend/tests/degraded.test.ts::
    socket_failure_switches_to_ten_second_polling and frontend/src/Chrome.jsx
    StatusPill (the pill names the mode and the interval).
    """
    events = (REPO / "frontend" / "src" / "useEvents.js").read_text(encoding="utf-8")
    chrome = (REPO / "frontend" / "src" / "Chrome.jsx").read_text(encoding="utf-8")
    assert "export const POLL_MS = 10_000" in events
    assert "degraded" in events
    assert "pollMs = POLL_MS" in events
    assert "degraded — polling every" in chrome
    assert "POLL_MS / 1000" in chrome
    assert 'role="status"' in chrome
    tests = (REPO / "frontend" / "tests" / "degraded.test.ts").read_text(encoding="utf-8")
    assert "socket_failure_switches_to_ten_second_polling" in tests


@pytest.mark.django_db
@pytest.mark.req("MAP-96-GRAPH-V1")
def test_map_v1_snapshot_and_list_view():
    """Map v1 is a live snapshot of NetworkZones/hosts/containers + list toggle.

    Transcribes tests/test_map_graph.py::test_graph_is_derived_from_models_not_a_stored_blob
    and ::test_zone_nodes_are_networkzones_not_dnszones, plus
    frontend/tests/map.test.ts::list_view_toggle_shows_the_same_nodes.
    Must never be quietly absent — no MAP-96 slip waiver.
    """
    from test_map_graph import _instance, _project, _site, _target, _zone

    from monitor.map_graph import graph_snapshot

    project = _project()
    zone = _zone("prod-vlan", "p3-map-vlan")
    target = _target(zone, "p3-web-1")
    site = _site(project, "p3-shop", target)
    _instance(site, target, 20000)

    graph = graph_snapshot()
    kinds = {n["kind"] for n in graph["nodes"]}
    assert {"zone", "host", "container", "hub", "edge"} <= kinds
    labels = {n["label"] for n in graph["nodes"]}
    assert "prod-vlan" in labels
    assert "p3-web-1" in labels
    assert not any(
        "dns" in n.get("kind", "") or n.get("kind") == "dnszone"
        for n in graph["nodes"]
    )

    map_src = (REPO / "frontend" / "src" / "Map.jsx").read_text(encoding="utf-8")
    assert "listView" in map_src
    assert "List view" in map_src
    assert "<svg" in map_src or "SvgGraph" in map_src
    tests = (REPO / "frontend" / "tests" / "map.test.ts").read_text(encoding="utf-8")
    assert "list_view_toggle_shows_the_same_nodes" in tests

    assert "MAP-96-GRAPH-V1" not in _waivers() or "RETIRED" in _waivers()
    assert not any(
        line.startswith("WAIVED: MAP-96-GRAPH-V1") for line in _waivers().splitlines()
    )


@pytest.mark.django_db
@pytest.mark.req("SEC-P5-BREAK-GLASS")
def test_breakglass_has_impact_hub_side_dns_and_freshness():
    """Runbook leads with impact, names Hub-side upsert_record, carries freshness.

    Transcribes tests/test_breakglass.py::test_runbook_states_impact_before_commands,
    ::test_dns_section_names_hub_side_commands_only, and
    ::test_runbook_carries_generated_at_deployment_and_schema_version.
    """
    import re

    from test_breakglass import (
        BLUE_GREEN_SERVING,
        GENERATED_AT,
        IMAGE,
        RECREATE_DOWN,
        TOKEN,
        _first_command_index,
        _written,
    )

    from deploys.failure_impact import impact_line

    _, _, down = _written(extra={"step": "health_check", "strategy": "recreate"})
    assert RECREATE_DOWN == impact_line("health_check", "recreate")
    assert RECREATE_DOWN in down
    assert down.index(RECREATE_DOWN) < _first_command_index(down)

    _, _, dns = _written(extra={
        "step": "dns",
        "strategy": "blue_green",
        "dns_values": ["203.0.113.10"],
        "zone": "example.com",
        "dns_token": TOKEN,
    })
    assert "## DNS" in dns
    section = dns.split("## DNS", 1)[1]
    assert "hub-side" in section.lower() or "hub side" in section.lower()
    assert "upsert_record" in section
    assert TOKEN not in dns

    _, _, fresh = _written(extra={"generated_at": GENERATED_AT})
    assert GENERATED_AT in fresh
    assert IMAGE in fresh
    assert re.search(r"schema[_\s-]*version\s*[:=]\s*\d+", fresh, re.I)
    assert BLUE_GREEN_SERVING  # source constant still imported


@pytest.mark.django_db
@pytest.mark.req("REL-P2-DRILL-STUB")
def test_nightly_is_green_on_a_host_with_no_live_site():
    """A siteless hub-down SKIPPED is nightly-green (exit 0) plus a P2 Finding.

    Transcribes tests/test_drills.py::
    test_no_eligible_site_is_skipped_with_a_reason_and_a_p2_finding
    and ::test_nightly_exits_zero_on_a_host_with_no_live_site.
    """
    from core.models import CheckRun, Finding
    from monitor.drills import nightly_exit_code, run_hub_down_drill

    run = run_hub_down_drill(duration_s=60)
    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.status == CheckRun.Status.SKIPPED
    assert stored.status != CheckRun.Status.SUCCEEDED
    assert "eligible" in stored.results["reason"]
    row = Finding.objects.get(fingerprint="drill-missed:hub_down:no-eligible-site")
    assert row.severity == Finding.Severity.P2
    assert nightly_exit_code(run) == 0


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_rel_p2_24h_still_not_claimed():
    """REL-P2 24h stays waived; the phase-3 demo names it as a dated calendar item.

    Transcribes tests/test_drills.py::test_hub_down_still_refuses_to_claim_24h
    (D-042): the fingerprint is still in WAIVERS.md, the registry row is
    untouched (phase 2, verify demo), and the phase-3 demo record quotes the
    waiver as outstanding rather than claiming a 24h run.
    """
    waivers = _waivers()
    assert WAIVER_24H in waivers
    line = next(row for row in waivers.splitlines() if WAIVER_24H in row)
    assert "calendar" in line.lower()
    assert "24h" in line.lower() or "24 h" in line.lower()

    rel_p2 = _registry()["REL-P2-HUB-DOWN-SITES-UP"]
    assert rel_p2["phase"] == 2
    assert rel_p2["verify"] == "demo"

    record = _demo()
    assert WAIVER_24H in record, (
        "the phase-3 demo record must name the 24h waiver as outstanding"
    )
    assert "2026-08-23" in record or "calendar" in record.lower()
    assert "Phase 3b" in record or "phase 3b" in record.lower()
    assert "adopt" in record.lower()


# ── extras the named list does not cover but the gate still needs ───────────


@pytest.mark.req("UX-F1-IA-NAV")
def test_object_centric_nav_lists_six_objects():
    """Object-centric nav is the six entries; advisors are tabs, not pages.

    Transcribes frontend/tests/nav.test.ts::advisors_are_tabs_not_top_level_pages.
    """
    chrome = (REPO / "frontend" / "src" / "Chrome.jsx").read_text(encoding="utf-8")
    settings = (REPO / "frontend" / "src" / "screens" / "Settings.jsx").read_text(
        encoding="utf-8")
    assert '{ id: "home", label: "Home" }' in chrome
    assert '{ id: "sites", label: "Sites" }' in chrome
    assert '{ id: "targets", label: "Targets" }' in chrome
    assert '{ id: "deploys", label: "Deploys" }' in chrome
    assert '{ id: "findings", label: "Findings" }' in chrome
    assert '{ id: "settings", label: "Settings" }' in chrome
    assert "advisor" not in chrome.lower() or "never entries here" in chrome
    assert 'id: "cloudflare"' in settings
    tests = (REPO / "frontend" / "tests" / "nav.test.ts").read_text(encoding="utf-8")
    assert "advisors_are_tabs_not_top_level_pages" in tests


@pytest.mark.django_db
@pytest.mark.req("TLS-V9-CERT-THRESHOLDS")
def test_cert_expiry_thresholds_match_v9():
    """Uploaded 45/21/7 → P3/P2/P1; auto-renewed 7/1 → P2/P1; Beat owns daily.

    Transcribes tests/test_cert_thresholds.py::test_uploaded_45_21_7_maps_to_p3_p2_p1,
    ::test_auto_renewed_7_and_1_map_to_p2_and_p1, and
    ::test_threshold_table_matches_alert_protocol_v9.
    """
    from django.conf import settings
    from test_cert_thresholds import _cert, _site

    from core.models import CheckRun, Finding, TlsCertificate
    from monitor import tasks as monitor_tasks
    from monitor.cert_watch import AUTO_THRESHOLDS, UPLOADED_THRESHOLDS, scan_cert_expiry

    assert UPLOADED_THRESHOLDS == ((45, "p3"), (21, "p2"), (7, "p1"))
    assert AUTO_THRESHOLDS == ((7, "p2"), (1, "p1"))
    entry = settings.CELERY_BEAT_SCHEDULE["cert-expiry-daily"]
    assert entry["task"] == monitor_tasks.scan_cert_expiry.name
    assert float(entry["schedule"]) == 86400.0

    site = _site("p3-v9")
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

    Finding.objects.all().delete()
    TlsCertificate.objects.all().delete()
    _cert(site, mode=TlsCertificate.Mode.ORIGIN_CERT, days=7)
    scan_cert_expiry()
    assert Finding.objects.get().severity == Finding.Severity.P2
    Finding.objects.all().delete()
    TlsCertificate.objects.all().delete()
    _cert(site, mode=TlsCertificate.Mode.AUTO, days=1)
    run = scan_cert_expiry()
    assert Finding.objects.get().severity == Finding.Severity.P1
    assert run.kind == CheckRun.Kind.CERT_EXPIRY


@pytest.mark.req("UX-F4-FAILURE-IMPACT")
def test_failed_deploy_shows_impact_and_at_most_three_actions():
    """Impact line first; at most three named actions; one table, no literals.

    Transcribes tests/test_failure_impact.py::test_every_step_has_an_impact_line
    and ::test_failure_offers_at_most_three_actions.
    """
    from test_failure_impact import STEPS, STRATEGIES

    from deploys import failure_impact as fi

    for step in STEPS:
        for strategy in STRATEGIES:
            line = fi.impact_line(step, strategy)
            assert line and line.strip() == line
            assert (
                "Old version still serving — site unaffected" in line
                or "Site may be unreachable" in line
                or "Site is down" in line
            ), line
            actions = fi.failure_actions(step, strategy)
            assert 1 <= len(actions) <= 3, (step, strategy, actions)
            labels = [a["label"].lower() for a in actions]
            assert all(a["does"] for a in actions)
            assert any("retry" in label for label in labels)
            assert any("roll back" in label for label in labels)
            assert any("abort" in label and "clean" in label for label in labels)

    deploys_jsx = (REPO / "frontend" / "src" / "screens" / "Deploys.jsx").read_text(
        encoding="utf-8")
    assert "deploy.headline || deploy.impact" in deploys_jsx
    leaked = [
        s for s in (fi.OLD_VERSION_SERVING, fi.SITE_UNREACHABLE, fi.SITE_IS_DOWN)
        if s in deploys_jsx
    ]
    assert leaked == [], f"Deploys.jsx literals impact copy: {leaked}"


@pytest.mark.django_db
@pytest.mark.req("MON-UPTIME-EVENTS")
def test_uptime_events_are_transitions_not_samples():
    """Three up-probes write one UptimeEvent; a flip writes exactly one more.

    Transcribes tests/test_uptime_events.py::test_transition_writes_one_event_not_one_per_probe.
    """
    from test_uptime_events import RecordingGet
    from uptime_fixtures import make_site

    from core.models import UptimeEvent
    from monitor.uptime import probe_cycle

    site = make_site("p3-up")
    get = RecordingGet(status=200)
    for _ in range(3):
        assert probe_cycle(http_get=get)["completed"] is True
    entity = f"site:{site.name}"
    assert UptimeEvent.objects.filter(entity=entity).count() == 1
    get.status = 503
    for _ in range(3):
        probe_cycle(http_get=get)
    states = list(
        UptimeEvent.objects.filter(entity=entity).order_by("at", "pk")
        .values_list("state", flat=True)
    )
    assert states == ["up", "down"]


@pytest.mark.django_db
@pytest.mark.req("MON-UPTIME-EVENTS")
def test_canary_fail_degrades_to_one_hub_egress_p2():
    """A failed canary collapses N site-down candidates to one Hub-egress P2.

    Transcribes tests/test_canary.py::test_canary_failure_collapses_n_site_alerts_to_one_p2.
    The phase-3 demo must name this clause honestly: a real T1 artifact, or a
    dated "not recorded" line — never an invented live canary-fail.
    """
    from test_canary import RecordingGet

    from monitor.deadman import declare_mass_outage

    candidates = ["site:blog", "site:scan", "site:shop"]
    alerts = declare_mass_outage(
        candidates, http_get=RecordingGet(status=OSError("egress down")),
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["severity"] == "p2"
    assert alert["kind"] == "hub-egress-degraded"
    assert alert["suppressed"] == candidates

    record = _demo()
    assert "canary" in record.lower(), (
        "design-note §4 and P3-DNS-MONITOR-DEMO name canary-fail → one P2"
    )
    assert "canary-fail" in record.lower() or "canary fail" in record.lower()
    artifact = REPO / "conformance" / "demos" / "phase-3" / "canary-fail.txt"
    assert artifact.is_file() and artifact.stat().st_size > 0, (
        "record a real canary artifact or a dated not-recorded line"
    )
    text = artifact.read_text(encoding="utf-8")
    assert "2026-08-23" in text
    assert (
        "hub-egress-degraded" in text.lower()
        or "hub egress degraded" in text.lower()
        or "not recorded" in text.lower()
    )
    assert "live canary-fail was not run" in text.lower() or "not a live" in text.lower() or (
        "not recorded" in text.lower()
    )


def test_clause_scoped_full_text_ids_are_waived_not_marked():
    """SCAN-M4 shape: full-text ids have no marker; clause-scoped waivers name
    the unbuilt clause and its retirement id. Unmarked — a marker here would
    claim the whole text.
    """
    import check

    markers = check.collect_markers(REPO)
    assert FULL_TEXT_SEC_B2 not in markers
    assert FULL_TEXT_UX_F5 not in markers

    sec = _waiver_lines(FULL_TEXT_SEC_B2)
    assert sec, f"{FULL_TEXT_SEC_B2} must have a clause-scoped WAIVED line"
    assert "Hub-central-DNS-01" in sec[0] or "DNS-01" in sec[0]
    assert "TLS-B2-HUB-DNS01-UNPROXIED" in sec[0]

    ux = _waiver_lines(FULL_TEXT_UX_F5)
    assert ux, f"{FULL_TEXT_UX_F5} must have a clause-scoped WAIVED line"
    assert "hardware" in ux[0].lower() or "T1" in ux[0]
    assert "SEC-F5-T1-HARDWARE-TOUCH" in ux[0]

    for rid in ADOPT_IDS:
        lines = _waiver_lines(rid)
        assert lines, f"{rid} must be waived — Task 15 slipped to Phase 3b"
        assert "3b" in lines[0].lower() or "Phase 3b" in lines[0]

    text = _waivers()
    assert "UX-F8-SIMULATION-STATES" in text
    assert "RETIRED 2026-08-22 (Task 13)" in text
    assert "SEC-P5" in text
    assert "RETIRED 2026-08-22 (Task 16)" in text
    assert not any(line.startswith("WAIVED: MON-C7-RETENTION") for line in text.splitlines())
    assert not any(line.startswith("WAIVED: MAP-96-GRAPH-V1") for line in text.splitlines())

    le = _waiver_lines("HARNESS-T3-LE-STAGING")
    cf = _waiver_lines("DNS-CF-T3-LIVE")
    assert le and "no-test-zone-credentials" in le[0]
    assert cf and "no-test-zone-credentials" in cf[0]

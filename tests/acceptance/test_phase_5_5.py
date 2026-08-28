"""Phase 5.5 acceptance — each test transcribes one design-note §4 clause.

`check.py --phase 5.5 --exclude-tier t2 --exclude-tier t3` is the phase-5.5
gate. Everyday `conformance` / `review-round` stay `--phase 5`. T1 fakes
only: FakeIntake, FakeIntakeClient, FakeHelper, FakeTransport,
FakeWebhookSink, FakeDnsProvider (custom_hostname). Do not require live
intake, live CF-for-SaaS, or a named partner. Do not invent
HUB_TEST_PARTNER_TOKEN / HUB_INTAKE_HMAC / HUB_WEBHOOK_SECRET. Do not add
Playwright. Do not claim HMAC enablement or MCP.

Every T1 body asserts the same properties an existing named proof asserts
(transcription, not fiction); each docstring names its source test.
The demo record must describe those proofs, not a fictional live run.
P55-PARTNER-DEMO is verify: demo of the file — no MUST @pytest.mark.req here.
PART-U1-NAMED-PARTNER stays uncovered (named-partner.md absent).
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "conformance" / "demos" / "phase-5.5.md"
NAMED_PARTNER = REPO / "conformance" / "demos" / "named-partner.md"
HMAC_EVAL = "docs/hmac-bearer-evaluation.md"
NAV_IDS = ["home", "sites", "targets", "deploys", "findings", "settings"]
NAMED = (
    "test_empty_partners_tab_is_create_partner_never_connected",
    "test_partner_create_t1_201_returns_hubk_and_whsec_once",
    "test_get_never_echoes_hubk_or_whsec",
    "test_global_flag_defaults_off",
    "test_enable_is_t1_not_a_toggle",
    "test_signed_create_site_on_intake_not_hub",
    "test_hub_reverify_rejects_replay_even_if_intake_forwards",
    "test_idempotency_match_and_mismatch_422",
    "test_partnersite_isolation_no_site_tier",
    "test_dockerfile_git_source_refuses",
    "test_partner_a_404s_on_b",
    "test_hub_host_and_cohost_refuse",
    "test_custom_hostname_txt_before_serve",
    "test_webhooks_fake_sink_standard_webhooks",
    "test_suspend_t1_stop_detach_revoke",
    "test_takedown_t2_410_on_site_detail",
    "test_destination_rank_own_server_honesty_sentence",
    "test_partner_reaper_vs_multipass_and_aws",
    "test_partner_site_hard_down_p2_not_prod_p1",
    "test_git_push_outbox_on_same_poller",
    "test_quotas_max_sites_5_fleet_12",
    "test_empty_intake_url_skips_without_checkrun_flood",
    "test_nav_stays_six",
    "test_demo_does_not_claim_named_partner_or_live_intake",
)

pytestmark = [pytest.mark.acceptance(phase=5.5)]


def _demo():
    assert DEMO.is_file() and DEMO.stat().st_size > 0, (
        "conformance/demos/phase-5.5.md must exist — P55-PARTNER-DEMO is verify: demo"
    )
    text = DEMO.read_text(encoding="utf-8")
    assert text.strip(), "a whitespace-only demo is not a record"
    return text


def _registry():
    data = yaml.safe_load((REPO / "conformance" / "requirements.yaml").read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["requirements"]}


def _assert_honest_t1_demo():
    """A non-empty filler must not verify P55-PARTNER-DEMO (Task 0)."""
    record = _demo()
    lower = record.lower()
    for name in NAMED:
        assert name in record, f"demo must name the acceptance nodeid {name}"
    assert "FakeIntake" in record
    assert "FakeIntakeClient" in record
    assert "FakeHelper" in record
    assert "FakeTransport" in record
    assert "FakeWebhookSink" in record
    assert "FakeDnsProvider" in record
    assert "t1" in lower
    assert "no live intake" in lower or "not a live intake" in lower
    assert "named-partner.md" in record
    assert "uncovered" in lower
    assert "does not claim" in lower
    assert "hmac" in lower
    assert "evaluation" in lower
    assert "enablement" in lower
    assert HMAC_EVAL in record
    assert "mcp" in lower
    assert "out" in lower
    assert "two consecutive" in lower
    assert "wait" in lower
    assert "playwright" not in lower or "no playwright" in lower
    assert "HUB_TEST_" + "PARTNER_TOKEN" not in record
    assert "HUB_INTAKE_" + "HMAC" not in record
    assert "HUB_WEBHOOK_" + "SECRET" not in record
    assert "todo" not in lower
    assert "conformance-5.5" in lower
    assert "--exclude-tier t2" in record and "--exclude-tier t3" in record
    assert "P55-PARTNER-DEMO" in record
    assert "§4" in record or "section 4" in lower
    assert "phase 5" in lower
    assert not NAMED_PARTNER.exists(), (
        "conformance/demos/named-partner.md must stay absent — a filler "
        "would verify PART-U1-NAMED-PARTNER and invent a partner"
    )
    return record


# ── named clauses ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_empty_partners_tab_is_create_partner_never_connected(client, monkeypatch):
    """Empty Partners tab is Create partner (not Connect); Fake / empty
    INTAKE_URL / post-create never paints Connected.

    Transcribes tests/test_partner_create.py::
    test_settings_is_create_partner_not_connect,
    ::test_settings_unconfigured_is_degraded_not_connected, and
    ::test_settings_post_create_fake_or_empty_intake_never_connected.
    """
    from test_partner_create import (
        CREATE_URL,
        SLUG,
        _blob,
        _post_create,
        _touch,
        test_settings_is_create_partner_not_connect,
        test_settings_unconfigured_is_degraded_not_connected,
    )

    test_settings_is_create_partner_not_connect()
    test_settings_unconfigured_is_degraded_not_connected(client)
    _touch(client, monkeypatch)
    created = _post_create(client)
    assert created.status_code == 201, created.content
    listed = client.get(CREATE_URL)
    assert listed.status_code == 200, listed.content
    body = listed.json()
    dumped = _blob(body)
    assert not re.search(r"\bConnected\b", dumped)
    assert body["intake"]["status"] in {"degraded", "error"}
    assert body["intake"]["mode"] == "fake"
    assert len(body["partners"]) == 1
    assert body["partners"][0]["slug"] == SLUG
    assert "hubk" not in body["partners"][0]
    assert "whsec" not in body["partners"][0]


@pytest.mark.django_db
def test_partner_create_t1_201_returns_hubk_and_whsec_once(client, monkeypatch):
    """T1 partner.create requires touch + type-the-name; 201 returns
    hubk_test_ + whsec_ once; private key is not a Partner column and is
    not vaulted.

    Transcribes tests/test_partner_create.py::test_partner_create_is_t1,
    ::test_create_201_returns_hubk_and_whsec_once, and
    ::test_private_key_is_not_a_partner_column_and_not_vaulted.
    """
    from test_partner_create import (
        test_create_201_returns_hubk_and_whsec_once,
        test_partner_create_is_t1,
    )

    from core.actions import ACTION_TIERS
    from core.models import Partner

    test_partner_create_is_t1()
    row = next(r for r in ACTION_TIERS if r["id"] == "partner.create")
    assert row["tier"] == "T1"
    assert row["label"] == "Create partner"
    names = {f.name for f in Partner._meta.get_fields()}
    assert "private_key" not in names
    assert not any("private" in n for n in names)
    test_create_201_returns_hubk_and_whsec_once(client, monkeypatch)


@pytest.mark.django_db
def test_get_never_echoes_hubk_or_whsec(client, monkeypatch):
    """GET / list never echo hubk_ or whsec_.

    Transcribes tests/test_partner_create.py::test_get_never_echoes_hubk_or_whsec.
    """
    from test_partner_create import test_get_never_echoes_hubk_or_whsec as _get

    _get(client, monkeypatch)


@pytest.mark.django_db
def test_global_flag_defaults_off():
    """Global PARTNER_API_ENABLED defaults False; prod does not default on.

    Transcribes tests/test_partner_kill_switch.py::test_global_flag_defaults_off.
    """
    from test_partner_kill_switch import test_global_flag_defaults_off as _off

    _off()


@pytest.mark.django_db
def test_enable_is_t1_not_a_toggle(client, monkeypatch):
    """Enable partner API is T1 (type partner-api), never a toggle.

    Transcribes tests/test_partner_kill_switch.py::
    test_enable_partner_api_is_t1_not_a_toggle and
    ::test_partner_api_kill_switch_is_t1.
    """
    from test_partner_kill_switch import (
        test_enable_partner_api_is_t1_not_a_toggle,
        test_partner_api_kill_switch_is_t1,
    )

    test_partner_api_kill_switch_is_t1()
    test_enable_partner_api_is_t1_not_a_toggle(client, monkeypatch)


@pytest.mark.django_db
def test_signed_create_site_on_intake_not_hub(client):
    """Signed POST /partner/v1/sites lands on in-process Fake intake, not Hub.

    Transcribes tests/test_intake_process.py::test_post_sites_returns_201_shape,
    ::test_unsigned_post_is_not_201, ::test_hub_urlconf_has_no_api_partner_or_mcp,
    and ::test_hub_candidate_partner_and_mcp_paths_404.
    """
    from test_intake_process import (
        test_hub_candidate_partner_and_mcp_paths_404,
        test_hub_urlconf_has_no_api_partner_or_mcp,
        test_post_sites_returns_201_shape,
        test_unsigned_post_is_not_201,
    )

    test_unsigned_post_is_not_201()
    test_post_sites_returns_201_shape()
    test_hub_urlconf_has_no_api_partner_or_mcp()
    test_hub_candidate_partner_and_mcp_paths_404(client)


@pytest.mark.django_db
def test_hub_reverify_rejects_replay_even_if_intake_forwards():
    """Hub re-verifies Ed25519 and rejects replay even when Fake intake forwards.

    Transcribes tests/test_partner_verify.py::
    test_vectors_replay_rejected_by_hub_even_if_intake_forwards,
    ::test_finding_fingerprint_is_partner_replay_partner_pk, and
    ::test_vectors_valid_passes_both_verifiers.
    """
    from test_partner_verify import (
        test_finding_fingerprint_is_partner_replay_partner_pk,
        test_vectors_replay_rejected_by_hub_even_if_intake_forwards,
        test_vectors_valid_passes_both_verifiers,
    )

    test_vectors_valid_passes_both_verifiers()
    test_vectors_replay_rejected_by_hub_even_if_intake_forwards()
    test_finding_fingerprint_is_partner_replay_partner_pk()


@pytest.mark.django_db
def test_idempotency_match_and_mismatch_422():
    """Idempotency match returns the first response; param mismatch is 422.

    Transcribes tests/test_partner_verify.py::
    test_idempotency_match_returns_first_response and
    ::test_idempotency_mismatch_is_422.
    """
    from test_partner_verify import (
        test_idempotency_match_returns_first_response,
        test_idempotency_mismatch_is_422,
    )

    test_idempotency_match_returns_first_response()
    test_idempotency_mismatch_is_422()


@pytest.mark.django_db
def test_partnersite_isolation_no_site_tier():
    """Isolation is PartnerSite; no Site.tier / Site.partner_id / Target.tier.

    Transcribes tests/test_partner_isolation.py::test_no_site_tier_column and
    ::test_no_site_partner_id_and_no_target_tier.
    """
    from test_partner_isolation import (
        test_no_site_partner_id_and_no_target_tier,
        test_no_site_tier_column,
    )

    test_no_site_tier_column()
    test_no_site_partner_id_and_no_target_tier()


@pytest.mark.django_db
def test_dockerfile_git_source_refuses():
    """Partner Dockerfile / git-source / unconstrained image refuse.

    Transcribes tests/test_partner_isolation.py::
    test_dockerfile_or_git_source_refuses and ::test_unconstrained_image_refuses.
    """
    from test_partner_isolation import (
        test_dockerfile_or_git_source_refuses,
        test_unconstrained_image_refuses,
    )

    test_dockerfile_or_git_source_refuses()
    test_unconstrained_image_refuses()


@pytest.mark.django_db
def test_partner_a_404s_on_b():
    """Partner A 404s on B's ids (not 403).

    Transcribes tests/test_partner_isolation.py::test_partner_a_404s_on_partner_b_ids.
    """
    from test_partner_isolation import test_partner_a_404s_on_partner_b_ids

    test_partner_a_404s_on_partner_b_ids()


@pytest.mark.django_db
def test_hub_host_and_cohost_refuse():
    """Hub host and non-partner co-host refuse partner materialize.

    Transcribes tests/test_partner_isolation.py::test_hub_host_refuses and
    ::test_non_partner_cohost_refuses.
    """
    from test_partner_isolation import test_hub_host_refuses, test_non_partner_cohost_refuses

    test_hub_host_refuses()
    test_non_partner_cohost_refuses()


@pytest.mark.django_db
def test_custom_hostname_txt_before_serve(monkeypatch):
    """Fake CustomHostname is not served until TXT verifies; helpers do not
    construct a Cloudflare client; no new ACME / DNS-01.

    Transcribes tests/test_custom_hostname.py::test_unverified_hostname_is_not_served,
    ::test_txt_before_serve,
    ::test_custom_hostname_is_capability_on_dns_provider_for_object, and
    ::test_no_acme_or_dns01_in_custom_hostname_module.
    """
    from test_custom_hostname import (
        test_custom_hostname_is_capability_on_dns_provider_for_object,
        test_no_acme_or_dns01_in_custom_hostname_module,
        test_txt_before_serve,
        test_unverified_hostname_is_not_served,
    )

    test_unverified_hostname_is_not_served()
    test_txt_before_serve()
    test_custom_hostname_is_capability_on_dns_provider_for_object(monkeypatch)
    test_no_acme_or_dns01_in_custom_hostname_module()


@pytest.mark.django_db
def test_webhooks_fake_sink_standard_webhooks(monkeypatch):
    """Standard Webhooks Hub-egress signs vs a reference verifier against a
    Fake sink; re-resolves at every delivery; whsec_ is vault-only.

    Transcribes tests/test_partner_webhooks.py::
    test_standard_webhooks_signature_verifies_with_reference_lib,
    ::test_whsec_not_on_intake_and_not_in_detail, and
    ::test_delivery_re_resolves_and_refuses_rebind_to_metadata.
    """
    from test_partner_webhooks import (
        test_delivery_re_resolves_and_refuses_rebind_to_metadata,
        test_standard_webhooks_signature_verifies_with_reference_lib,
        test_whsec_not_on_intake_and_not_in_detail,
    )

    test_standard_webhooks_signature_verifies_with_reference_lib(monkeypatch)
    test_whsec_not_on_intake_and_not_in_detail(monkeypatch)
    test_delivery_re_resolves_and_refuses_rebind_to_metadata(monkeypatch)


@pytest.mark.django_db
def test_suspend_t1_stop_detach_revoke(client, monkeypatch):
    """T1 partner.suspend overlay names stop / detach / revoke; Fake Transport
    actually stops containers, detaches routes, and revokes the Hub-side key.

    Transcribes tests/test_partner_kill_switch.py::test_partner_suspend_is_t1,
    ::test_suspend_stops_containers_detaches_revokes, and
    ::test_suspend_overlay_names_stop_detach_revoke.
    """
    from test_partner_kill_switch import (
        test_partner_suspend_is_t1,
        test_suspend_overlay_names_stop_detach_revoke,
        test_suspend_stops_containers_detaches_revokes,
    )

    test_partner_suspend_is_t1()
    test_suspend_overlay_names_stop_detach_revoke()
    test_suspend_stops_containers_detaches_revokes(client, monkeypatch)


@pytest.mark.django_db
def test_takedown_t2_410_on_site_detail(client, monkeypatch):
    """Per-site takedown is T2 on partner site detail; route becomes 410.

    Transcribes tests/test_partner_kill_switch.py::
    test_site_takedown_is_t2_and_returns_410 and
    ::test_takedown_control_is_on_partner_site_detail.
    """
    from test_partner_kill_switch import (
        test_site_takedown_is_t2_and_returns_410,
        test_takedown_control_is_on_partner_site_detail,
    )

    test_takedown_control_is_on_partner_site_detail()
    test_site_takedown_is_t2_and_returns_410(client, monkeypatch)


@pytest.mark.django_db
def test_destination_rank_own_server_honesty_sentence(client):
    """Ranking kind=ssh is T2 with the K5 honesty sentence once.

    Transcribes tests/test_partner_kill_switch.py::
    test_destination_rank_http_pin_and_own_server_honesty_sentence and
    ::test_destination_rank_own_server_is_t2_with_honesty_sentence.
    """
    from test_partner_kill_switch import (
        test_destination_rank_http_pin_and_own_server_honesty_sentence,
        test_destination_rank_own_server_is_t2_with_honesty_sentence,
    )

    test_destination_rank_own_server_is_t2_with_honesty_sentence()
    test_destination_rank_http_pin_and_own_server_honesty_sentence(client)


@pytest.mark.django_db
def test_partner_reaper_vs_multipass_and_aws():
    """Partner reaper plants an orphan and writes PARTNER_REAPER; Multipass
    and AWS purpose=test reapers stay.

    Transcribes tests/test_partner_reaper.py::
    test_partner_reaper_plants_orphan_and_cleans,
    ::test_partner_reaper_writes_checkrun_kind_partner_reaper, and
    ::test_multipass_and_aws_reapers_untouched.
    """
    from test_partner_reaper import (
        test_multipass_and_aws_reapers_untouched,
        test_partner_reaper_plants_orphan_and_cleans,
        test_partner_reaper_writes_checkrun_kind_partner_reaper,
    )

    test_partner_reaper_plants_orphan_and_cleans()
    test_partner_reaper_writes_checkrun_kind_partner_reaper()
    test_multipass_and_aws_reapers_untouched()


@pytest.mark.django_db
def test_partner_site_hard_down_p2_not_prod_p1():
    """Partner-site hard-down is P2 site-down:{name}; prod host-down is not
    partner-aggregate-down.

    Transcribes tests/test_partner_o1.py::
    test_partner_site_hard_down_fingerprint_is_site_down_name,
    ::test_n2_aggregate_fingerprint_is_partner_aggregate_down_partner_pk,
    ::test_partner_tier_host_down_reuses_host_down_fingerprint, and
    ::test_prod_host_down_is_not_partner_aggregate_down.
    """
    from test_partner_o1 import (
        test_n2_aggregate_fingerprint_is_partner_aggregate_down_partner_pk,
        test_partner_site_hard_down_fingerprint_is_site_down_name,
        test_partner_tier_host_down_reuses_host_down_fingerprint,
        test_prod_host_down_is_not_partner_aggregate_down,
    )

    test_partner_site_hard_down_fingerprint_is_site_down_name()
    test_n2_aggregate_fingerprint_is_partner_aggregate_down_partner_pk()
    test_partner_tier_host_down_reuses_host_down_fingerprint()
    test_prod_host_down_is_not_partner_aggregate_down()


@pytest.mark.django_db
def test_git_push_outbox_on_same_poller(monkeypatch):
    """git-webhook outbox type on the same poller is Fake-planted
    {type: git-push} with zero Hub/intake inbound listener.

    Transcribes tests/test_git_webhook_outbox.py::
    test_git_push_outbox_enqueues_deploy,
    ::test_git_push_uses_same_poller_as_partner_job, and
    ::test_git_push_is_fake_planted_not_a_public_route.
    """
    from test_git_webhook_outbox import (
        test_git_push_is_fake_planted_not_a_public_route,
        test_git_push_outbox_enqueues_deploy,
        test_git_push_uses_same_poller_as_partner_job,
    )

    test_git_push_is_fake_planted_not_a_public_route()
    test_git_push_outbox_enqueues_deploy(monkeypatch)
    test_git_push_uses_same_poller_as_partner_job(monkeypatch)


@pytest.mark.django_db
def test_quotas_max_sites_5_fleet_12():
    """Fifth site over max_sites=5 refuses; fleet cap 12 refuses.

    Transcribes tests/test_partner_quotas.py::test_max_sites_default_5,
    ::test_sixth_site_refuses, ::test_fleet_cap_12_refuses, and
    ::test_d084_numbers_match_partner_field_defaults.
    """
    from test_partner_quotas import (
        test_d084_numbers_match_partner_field_defaults,
        test_fleet_cap_12_refuses,
        test_max_sites_default_5,
        test_sixth_site_refuses,
    )

    from core.models import PartnerSite

    test_d084_numbers_match_partner_field_defaults()
    test_max_sites_default_5()
    # Source tests count fleet-wide PartnerSite rows; pytest isolates them
    # when collected as separate nodeids.
    PartnerSite.objects.all().delete()
    test_sixth_site_refuses()
    PartnerSite.objects.all().delete()
    test_fleet_cap_12_refuses()


@pytest.mark.django_db
def test_empty_intake_url_skips_without_checkrun_flood():
    """Empty INTAKE_URL is SKIPPED, not P1, and does not grow CheckRun every 10 s.

    Transcribes tests/test_intake_poll.py::
    test_empty_intake_url_skips_and_does_not_file_p1 and
    ::test_intake_client_for_is_fail_closed.
    """
    from test_intake_poll import (
        test_empty_intake_url_skips_and_does_not_file_p1,
        test_intake_client_for_is_fail_closed,
    )

    test_empty_intake_url_skips_and_does_not_file_p1()
    test_intake_client_for_is_fail_closed()


def test_nav_stays_six():
    """NAV is still six. VALID_TIERS stays {t1, t2, t3}. conformance-5.5
    excludes t2/t3. Everyday conformance stays phase 5. Demo names §4.

    Transcribes tests/test_partner_create.py::test_nav_still_six,
    tests/test_conformance_gate.py::test_valid_tiers_still_t1_t2_t3_only, and
    tests/test_makefile_nightly.py::test_conformance_5_5_is_phase_5_5_minus_live_tiers.
    """
    import check
    import gates
    from test_partner_create import test_nav_still_six as _nav

    _nav()
    src = (REPO / "frontend" / "src" / "Chrome.jsx").read_text(encoding="utf-8")
    start = src.index("export const NAV = [")
    end = src.index("];", start)
    ids = re.findall(r'id:\s*"(\w+)"', src[start:end])
    assert ids == NAV_IDS

    assert check.VALID_TIERS == {"t1", "t2", "t3"}
    assert "t4" not in check.VALID_TIERS

    recipe = gates.recipe(REPO, "conformance-5.5")
    assert recipe, "Makefile has no `conformance-5.5` recipe"
    assert "--phase 5.5" in recipe
    assert "--exclude-tier t2" in recipe
    assert "--exclude-tier t3" in recipe
    everyday = gates.recipe(REPO, "conformance")
    assert "--phase 5" in everyday
    assert "--phase 5.5" not in everyday
    recipe3 = gates.recipe(REPO, "conformance-3")
    assert "--phase 3" in recipe3
    assert "--exclude-tier" not in recipe3

    demo_req = _registry()["P55-PARTNER-DEMO"]
    assert demo_req["verify"] == "demo"
    assert "conformance/demos/phase-5.5.md" in demo_req.get("demo", [])
    u1 = _registry()["PART-U1-NAMED-PARTNER"]
    assert u1["verify"] == "demo"
    assert "conformance/demos/named-partner.md" in u1.get("demo", [])

    record = _assert_honest_t1_demo()
    assert "conformance-3" in record.lower()
    eval_doc = (REPO / HMAC_EVAL).read_text(encoding="utf-8")
    assert "do **not** enable" in eval_doc.lower() or "does not enable" in eval_doc.lower()
    assert HMAC_EVAL in record


def test_demo_does_not_claim_named_partner_or_live_intake():
    """The record is T1 Fake only: no named partner, no live intake, no HMAC
    enablement, no MCP, no two consecutive conformance-5.5 rounds claimed.

    Transcribes the honesty contract of design note §4 / P55-PARTNER-DEMO.
    """
    record = _assert_honest_t1_demo()
    lower = record.lower()
    assert "does not claim a named" in lower or "does not claim named" in lower
    assert "live cf-for-saas" not in lower or "no live" in lower or "not a live" in lower
    assert "did not run" in lower or "this session did not" in lower
    assert not NAMED_PARTNER.exists()

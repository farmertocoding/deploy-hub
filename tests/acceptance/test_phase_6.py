"""Phase 6 acceptance — each test transcribes one design-note §4 clause.

`check.py --phase 6 --exclude-tier t2 --exclude-tier t3` is the phase-6 gate.
Everyday `conformance` / `review-round` stay `--phase 5`. T1 fakes only:
FakeEdgeProtection (attack playbook). HostMetric rows are real Django rows.
Do not require live AWS. Do not invent HUB_TEST_AWS_TOKEN / HUB_TEST_CF_TOKEN
/ HUB_TEST_PARTNER_TOKEN / HUB_INTAKE_HMAC / HUB_WEBHOOK_SECRET. Do not add
Playwright. Do not claim a VM launched, auto mode, AMI, live provision, or
U1. Do not stub named-partner.md. PART-K is untouched.

Every T1 body asserts the same properties an existing named proof asserts
(transcription, not fiction); each docstring names its source test.
The demo record must describe those proofs, not a fictional live run.
P6-SCALER-DEMO is verify: demo of the file — no MUST @pytest.mark.req here.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "conformance" / "demos" / "phase-6.md"
NAMED_PARTNER = REPO / "conformance" / "demos" / "named-partner.md"
NAV_IDS = ["home", "sites", "targets", "deploys", "findings", "settings"]
NAMED = (
    "test_scale_ready_quiet_five_hot_mem_files_p2_proposal",
    "test_four_of_five_does_not_propose",
    "test_one_spike_does_not_propose",
    "test_attack_engaged_does_not_propose",
    "test_partner_site_does_not_propose",
    "test_not_scale_ready_does_not_propose_and_list_paints_single_instance_only",
    "test_nav_stays_six",
    "test_demo_does_not_claim_live_provision_or_auto_or_ami",
)

pytestmark = [pytest.mark.acceptance(phase=6)]


@pytest.fixture
def auth_client(client, django_user_model):
    """Logged-in operator with a confirmed second factor."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(
        username="op", password="pw-1234567890",
    )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _demo():
    assert DEMO.is_file() and DEMO.stat().st_size > 0, (
        "conformance/demos/phase-6.md must exist — P6-SCALER-DEMO is verify: demo"
    )
    text = DEMO.read_text(encoding="utf-8")
    assert text.strip(), "a whitespace-only demo is not a record"
    return text


def _registry():
    data = yaml.safe_load(
        (REPO / "conformance" / "requirements.yaml").read_text(encoding="utf-8"),
    )
    return {r["id"]: r for r in data["requirements"]}


def _assert_honest_t1_demo():
    """A non-empty stub must not verify P6-SCALER-DEMO (Task 0)."""
    record = _demo()
    lower = record.lower()
    for name in NAMED:
        assert name in record, f"demo must name the acceptance nodeid {name}"
    assert "FakeEdgeProtection" in record
    assert "t1" in lower
    assert "no live" in lower or "not a live" in lower
    assert "live aws" not in lower or "no live" in lower or "not a live" in lower
    assert "playwright" not in lower or "no playwright" in lower
    assert "HUB_TEST_" + "AWS_TOKEN" not in record
    assert "HUB_TEST_" + "CF_TOKEN" not in record
    assert "HUB_TEST_" + "PARTNER_TOKEN" not in record
    assert "HUB_TEST_" + "SCALE" not in record
    assert "HUB_INTAKE_" + "HMAC" not in record
    assert "HUB_WEBHOOK_" + "SECRET" not in record
    assert "stub" not in lower
    assert "todo" not in lower
    assert "conformance-6" in lower
    assert "--exclude-tier t2" in record and "--exclude-tier t3" in record
    assert "P6-SCALER-DEMO" in record
    assert "§4" in record or "section 4" in lower
    assert "named-partner.md" in record
    assert "uncovered" in lower
    assert not NAMED_PARTNER.exists(), (
        "conformance/demos/named-partner.md must stay absent — a filler "
        "would verify PART-U1-NAMED-PARTNER and invent a partner"
    )
    return record


# ── named clauses ───────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_scale_ready_quiet_five_hot_mem_files_p2_proposal():
    """A public scale-ready site, quiet attack playbook, not a PartnerSite,
    five HostMetric rows ram=90 one distinct UTC minute apart inside the
    300s window → P2 scale-out-proposal fingerprint scale-out-proposal:{pk},
    body contains 0.0416 / t3.medium / propose-mode does not launch;
    fix_action is the C8 sentence; Target count unchanged; no
    enroll_aws_target. Re-evaluate while OPEN does not add a push-log
    event. Disk-only five hot minutes → no Finding.

    Transcribes tests/test_scale_evaluator.py::
    test_five_hot_mem_minutes_file_proposal_with_cost,
    ::test_five_hot_load_minutes_file_proposal,
    ::test_five_hot_disk_minutes_do_not_propose,
    ::test_re_evaluate_while_open_does_not_record_second_push, and
    ::test_scaling_and_beat_do_not_import_enroll_or_ec2.
    """
    from test_scale_evaluator import (
        test_five_hot_disk_minutes_do_not_propose,
        test_five_hot_load_minutes_file_proposal,
        test_five_hot_mem_minutes_file_proposal_with_cost,
        test_re_evaluate_while_open_does_not_record_second_push,
        test_scaling_and_beat_do_not_import_enroll_or_ec2,
    )

    test_five_hot_mem_minutes_file_proposal_with_cost()
    test_five_hot_load_minutes_file_proposal()
    test_five_hot_disk_minutes_do_not_propose()
    test_re_evaluate_while_open_does_not_record_second_push()
    test_scaling_and_beat_do_not_import_enroll_or_ec2()


@pytest.mark.django_db
def test_four_of_five_does_not_propose():
    """Four of five over + one under → no Finding.

    Transcribes tests/test_scale_evaluator.py::
    test_four_of_five_over_one_under_does_not_propose (not the 1-of-5 spike).
    Unmarked: SCALE-SPIKE-NO-PROPOSE text is 1-of-5 / hole / mixed / stale.
    """
    from test_scale_evaluator import (
        test_four_of_five_over_one_under_does_not_propose,
    )

    test_four_of_five_over_one_under_does_not_propose()


@pytest.mark.django_db
@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_one_spike_does_not_propose():
    """One spike → no Finding. A missing minute, mixed axes, or samples
    older than the window also do not file.

    Transcribes tests/test_scale_evaluator.py::
    test_one_hot_among_five_does_not_propose,
    ::test_missing_minute_breaks_streak,
    ::test_mixed_axes_do_not_propose, and
    ::test_stale_window_does_not_propose.
    """
    from test_scale_evaluator import (
        test_missing_minute_breaks_streak,
        test_mixed_axes_do_not_propose,
        test_one_hot_among_five_does_not_propose,
        test_stale_window_does_not_propose,
    )

    test_one_hot_among_five_does_not_propose()
    test_missing_minute_breaks_streak()
    test_mixed_axes_do_not_propose()
    test_stale_window_does_not_propose()


@pytest.mark.django_db
@pytest.mark.req("SCALE-NEVER-ATTACK")
def test_attack_engaged_does_not_propose():
    """Same pressure while the attack playbook is engaged (FakeEdgeProtection)
    → no scale-out-proposal; an already-OPEN proposal is resolved.

    Transcribes tests/test_scale_evaluator.py::
    test_attack_engaged_does_not_propose,
    ::test_open_proposal_resolves_when_attack_engages, and
    ::test_evaluate_site_source_calls_refuse_if_attack.
    """
    from test_scale_evaluator import (
        test_attack_engaged_does_not_propose as _engaged,
    )
    from test_scale_evaluator import (
        test_evaluate_site_source_calls_refuse_if_attack,
        test_open_proposal_resolves_when_attack_engages,
    )

    _engaged()
    test_open_proposal_resolves_when_attack_engages()
    test_evaluate_site_source_calls_refuse_if_attack()


@pytest.mark.django_db
@pytest.mark.req("SCALE-NEVER-PARTNER")
def test_partner_site_does_not_propose():
    """Same pressure on a PartnerSite → no proposal. Binding PartnerSite
    after file system-resolves an OPEN proposal.

    Transcribes tests/test_scale_evaluator.py::
    test_partner_site_does_not_propose and
    ::test_partner_bind_after_file_resolves_open_proposal.
    """
    from test_scale_evaluator import (
        test_partner_bind_after_file_resolves_open_proposal,
    )
    from test_scale_evaluator import (
        test_partner_site_does_not_propose as _partner,
    )

    _partner()
    test_partner_bind_after_file_resolves_open_proposal()


@pytest.mark.django_db
@pytest.mark.req("SCALE-READY-PREREQ")
@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_not_scale_ready_does_not_propose_and_list_paints_single_instance_only(
        auth_client, tmp_path, db):
    """A site with scale_ready=False and five hot mem samples → no proposal;
    Sites list paints single-instance-only. mesh_only + five hot mem → no
    proposal. core.scale-ready is warning not blocker; missing/warning is
    False even if confirm_warnings.

    Transcribes tests/test_scale_evaluator.py::
    test_scale_ready_false_five_hot_does_not_propose and
    ::test_mesh_only_five_hot_does_not_propose,
    tests/test_scale_ready_scan.py::
    test_sqlite_tree_is_scale_ready_warning_not_blocker,
    ::test_materialize_copies_false_on_warning_even_with_confirm_warnings,
    ::test_missing_check_in_report_is_false, and
    ::test_materialize_copies_true_on_ok,
    tests/test_sites_single_instance.py::
    test_project_row_emits_scale_ready_false_without_aliasing_single_instance,
    ::test_site_observed_source_paints_single_instance_only_iff_scale_ready_false,
    ::test_f8_required_ids_include_single_instance_only_and_scale_out_proposal,
    ::test_scale_out_proposal_markup_has_no_instance_word_or_approve_control, and
    ::test_f8_single_instance_seed_does_not_retint_to_single_instance_only.
    """
    from test_scale_evaluator import (
        test_mesh_only_five_hot_does_not_propose,
        test_scale_ready_false_five_hot_does_not_propose,
    )
    from test_scale_ready_scan import (
        test_materialize_copies_false_on_warning_even_with_confirm_warnings,
        test_materialize_copies_true_on_ok,
        test_missing_check_in_report_is_false,
        test_sqlite_tree_is_scale_ready_warning_not_blocker,
    )
    from test_sites_single_instance import (
        test_f8_required_ids_include_single_instance_only_and_scale_out_proposal,
        test_f8_single_instance_seed_does_not_retint_to_single_instance_only,
        test_project_row_emits_scale_ready_false_without_aliasing_single_instance,
        test_scale_out_proposal_markup_has_no_instance_word_or_approve_control,
        test_site_observed_source_paints_single_instance_only_iff_scale_ready_false,
    )

    from core.models import Project

    test_sqlite_tree_is_scale_ready_warning_not_blocker(tmp_path)
    test_materialize_copies_false_on_warning_even_with_confirm_warnings(db)
    test_missing_check_in_report_is_false(db)
    test_materialize_copies_true_on_ok(db)
    test_scale_ready_false_five_hot_does_not_propose()
    test_mesh_only_five_hot_does_not_propose()
    Project.objects.filter(slug="not-ready").delete()
    test_project_row_emits_scale_ready_false_without_aliasing_single_instance(
        auth_client,
    )
    test_site_observed_source_paints_single_instance_only_iff_scale_ready_false()
    test_f8_required_ids_include_single_instance_only_and_scale_out_proposal()
    test_scale_out_proposal_markup_has_no_instance_word_or_approve_control()
    test_f8_single_instance_seed_does_not_retint_to_single_instance_only()


@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_nav_stays_six():
    """NAV is still six. VALID_TIERS stays {t1, t2, t3}. conformance-6
    excludes t2/t3. Everyday conformance stays phase 5. Demo names §4.

    Transcribes tests/test_sites_single_instance.py::test_nav_stays_six,
    tests/test_conformance_gate.py::test_valid_tiers_still_t1_t2_t3_only, and
    tests/test_makefile_nightly.py::
    test_conformance_6_is_phase_6_minus_live_not_a_review_round_prereq.
    """
    import check
    import gates
    from test_sites_single_instance import test_nav_stays_six as _nav

    _nav()
    src = (REPO / "frontend" / "src" / "Chrome.jsx").read_text(encoding="utf-8")
    start = src.index("export const NAV = [")
    end = src.index("];", start)
    ids = re.findall(r'id:\s*"(\w+)"', src[start:end])
    assert ids == NAV_IDS

    assert check.VALID_TIERS == {"t1", "t2", "t3"}
    assert "t4" not in check.VALID_TIERS

    recipe = gates.recipe(REPO, "conformance-6")
    assert recipe, "Makefile has no `conformance-6` recipe"
    assert "--phase 6" in recipe
    assert "--exclude-tier t2" in recipe
    assert "--exclude-tier t3" in recipe
    everyday = gates.recipe(REPO, "conformance")
    assert "--phase 5" in everyday
    assert "--phase 6" not in everyday
    recipe3 = gates.recipe(REPO, "conformance-3")
    assert "--phase 3" in recipe3
    assert "--exclude-tier" not in recipe3

    demo_req = _registry()["P6-SCALER-DEMO"]
    assert demo_req["verify"] == "demo"
    assert "conformance/demos/phase-6.md" in demo_req.get("demo", [])
    u1 = _registry()["PART-U1-NAMED-PARTNER"]
    assert u1["verify"] == "demo"
    assert "conformance/demos/named-partner.md" in u1.get("demo", [])

    record = _assert_honest_t1_demo()
    assert "conformance-5" in record.lower() or "phase 5" in record.lower()


def test_demo_does_not_claim_live_provision_or_auto_or_ami():
    """The record is T1 Fake only: no VM launched, no auto mode, no AMI,
    no live AWS, no U1, no Playwright, no invented token env.

    Transcribes the honesty contract of design note §4 / P6-SCALER-DEMO.
    """
    record = _assert_honest_t1_demo()
    lower = record.lower()
    assert "vm launched" in lower
    assert "auto mode" in lower
    assert "ami" in lower
    assert "does not claim" in lower or "does **not** claim" in lower
    assert "scalepolicy" in lower.replace(" ", "").replace("-", "") or (
        "scale policy" in lower
    )
    assert "live provision" not in lower or "no live" in lower or "not a live" in lower
    assert "did not run" in lower or "this session did not" in lower
    assert not NAMED_PARTNER.exists()

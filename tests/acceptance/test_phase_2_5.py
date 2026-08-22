"""Phase 2.5 acceptance — each test transcribes one harness milestone clause
(phase-2.5-design-note.md §4 exit demo / §5 MUST list). `check.py --phase 2.5`
requires the ids these mark to be green, or an honest WAIVERS.md line.

T1 clauses run in review-round. The two T3 clauses carry `@pytest.mark.t3` and
skip without Multipass — a skip never verifies a `tier: t3` id (D-024), so on a
host without Multipass those ids stay skipped-only behind the dated
host-without-multipass waivers, and `test_t3_skip_cannot_verify_tier_t3`
refuses those waivers the moment `multipass version` starts succeeding.

Every T1 body here asserts the same properties an existing named proof asserts
(transcription, not fiction); each docstring names its source test.
"""
from datetime import timedelta
from pathlib import Path

import gates
import pytest
import yaml
from test_crash_kill_matrix_sigkill import (
    STALE_AFTER,
    _assert_crashed_mid_pipeline,
    _spawn_worker,
)

from tests.harness.multipass import multipass_available

REPO = Path(__file__).resolve().parent.parent.parent

pytest_plugins = ["tests.harness.t3_deploy"]

pytestmark = [pytest.mark.acceptance(phase="2.5")]

T3_WAIVED_IDS = ("HARNESS-T3-NIGHTLY", "HARNESS-T3-UFW-TRUTH")
WAIVER_24H = "REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven"


@pytest.mark.django_db
@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_hub_test_mode_refuses_prod_zone():
    """§B9 credential wall: HUB_TEST_MODE refuses a prod-purpose zone before
    any mutation.

    Transcribes tests/test_hub_test_mode.py::test_prod_zone_refused_when_test_mode
    and ::test_execute_does_not_mutate_after_refuse: the default purpose is
    prod, an allowlisted slug is not enough, and execute raises with
    mutating_calls still empty.
    """
    from django.test import override_settings
    from pipeline_fakes import PipelineTransport, fixture_body, queued_deployment

    from core.models import NetworkZone
    from core.test_mode import TestModeError, assert_test_zone
    from deploys.pipeline import execute
    from providers.fakes import FakeDnsProvider

    zone = NetworkZone.objects.create(name="a25-prod", slug="hub-test")
    assert zone.purpose == "prod"
    with override_settings(HUB_TEST_MODE=True):
        with pytest.raises(TestModeError):
            assert_test_zone(zone)

    _site, deployment = queued_deployment("a25-b9", body=fixture_body("a25-b9"))
    transport = PipelineTransport()
    with override_settings(HUB_TEST_MODE=True):
        with pytest.raises(TestModeError):
            execute(deployment.pk, transport=transport, dns=FakeDnsProvider())
    assert transport.mutating_calls() == []


@pytest.mark.django_db
@pytest.mark.req("HARNESS-DRILLS-BEAT")
def test_checkrun_missed_drill_audits():
    """A missed drill is an AuditEvent, not a silent gap.

    Transcribes tests/test_checkrun.py::test_missed_drill_writes_audit_event:
    a past-due scheduled CheckRun with no terminal row after that due makes
    detect_missed_drills write a warning AuditEvent naming the kind.
    """
    from django.utils import timezone

    from core.models import AuditEvent
    from monitor.drills import find_missed, record_run
    from monitor.tasks import detect_missed_drills

    now = timezone.now()
    record_run("hub_down", "scheduled", due_at=now - timedelta(days=31))
    assert find_missed(now) == ["hub_down"]

    detect_missed_drills(now=now)

    event = AuditEvent.objects.get(action="drill-missed")
    assert event.severity == AuditEvent.Severity.WARNING
    assert event.detail["kind"] == "hub_down"


def test_core_ssh_py_is_sensitive():
    """core/ssh.py custody (design note §1 item 8) plus the Task 16 harness set.

    Transcribes tests/test_proc_rules.py::test_core_ssh_py_is_on_sensitive_paths
    (exact parsed membership, not Path.match) and extends it with the four
    Phase 2.5 harness custody entries this task maps. Unmarked: the enclosing
    PROC-SENSITIVE-HUMAN-MERGE stays a waived checklist req and a marker would
    claim its whole text.
    """
    paths = yaml.safe_load(
        (REPO / "conformance" / "paths.yaml").read_text(encoding="utf-8"))
    patterns = paths["sensitive"]
    assert "core/ssh.py" in patterns

    for entry in (
        "tests/harness/**",
        "monitor/drills.py",
        "core/test_mode.py",
        "providers/test_dns.py",
    ):
        assert entry in patterns, f"{entry} is not a sensitive-path entry"

    owners_lines = [
        line.strip()
        for line in (REPO / ".github/CODEOWNERS").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "/core/ssh.py @farmertocoding" in owners_lines


@pytest.fixture
def acceptance_sigkill_db(tmp_path, django_db_blocker):
    """A migrated file db the SIGKILLed worker child and this parent share."""
    from django.conf import settings
    from django.db import connections
    from test_crash_kill_matrix_sigkill import _bind_database, _prepare_file_db

    path = tmp_path / "hub.sqlite3"
    original = settings.DATABASES["default"]["NAME"]
    with django_db_blocker.unblock():
        try:
            _prepare_file_db(path)
            yield path
        finally:
            connections.close_all()
            _bind_database(original)


@pytest.mark.req("REL-P3-WORKER-DEATH")
def test_sigkill_child_resumes(acceptance_sigkill_db, monkeypatch):
    """SIGKILL of a live worker child, then the heartbeat sweep resumes it.

    Transcribes tests/test_crash_kill_matrix_sigkill.py::
    test_sigkill_after_step_n_child_dies_parent_survives (seq 1) and
    ::test_heartbeat_sweep_resumes_sigkilled_child: the child dies -SIGKILL,
    pytest survives, the crashed step is not succeeded, and a stale heartbeat
    sweep re-queues the row to succeeded.
    """
    import os
    import signal

    from django.db import connections
    from django.utils import timezone
    from pipeline_fakes import PipelineTransport, queued_deployment

    from deploys import pipeline
    from deploys.models import Deployment, DeploymentStep
    from deploys.tasks import sweep_stale_deployments
    from providers.fakes import FakeDnsProvider

    parent_pid = os.getpid()
    _site, deployment = queued_deployment("a25-sigkill")
    rc = _spawn_worker(deployment.pk, acceptance_sigkill_db, crash_after=1)
    connections.close_all()
    assert os.getpid() == parent_pid
    assert rc == -signal.SIGKILL
    _assert_crashed_mid_pipeline(deployment, 1)

    Deployment.objects.filter(pk=deployment.pk).update(
        last_heartbeat=timezone.now() - STALE_AFTER - timedelta(seconds=1),
    )
    monkeypatch.setattr(pipeline, "_default_transport", lambda site: PipelineTransport())
    monkeypatch.setattr(pipeline, "_default_dns", FakeDnsProvider)

    result = sweep_stale_deployments()
    assert deployment.pk in result["resumed"]
    deployment.refresh_from_db()
    if deployment.status != Deployment.Status.SUCCEEDED:
        pipeline.execute(
            deployment.pk, transport=PipelineTransport(), dns=FakeDnsProvider(),
        )
        deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED
    assert list(
        deployment.steps.order_by("seq").values_list("status", flat=True),
    ) == [DeploymentStep.Status.SUCCEEDED] * 9


@pytest.mark.django_db
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_toxiproxy_or_t1_timeout_resume():
    """A mid-deploy transport timeout is never a succeeded step; resume finishes.

    Transcribes the T1 half of tests/test_toxiproxy_resume.py
    (::test_timeout_on_transport_is_not_a_succeeded_step). The live half —
    toxiproxy on the SSH path, HARNESS-T3-TOXIPROXY — is
    tests/test_toxiproxy_resume.py::test_ssh_timeout_mid_deploy_resumes (t2,
    passing live on docker); this T1 body deliberately does NOT mark that id,
    because a FakeTransport timeout is not toxiproxy on the SSH path.
    """
    from pipeline_fakes import PipelineTransport, queued_deployment

    from deploys.models import Deployment, DeploymentStep
    from deploys.pipeline import execute, resume_step
    from providers.fakes import FakeDnsProvider

    class TimeoutTransport(PipelineTransport):
        def run(self, argv, *, timeout=60):
            if (
                isinstance(argv, (list, tuple))
                and argv
                and argv[0] == "docker"
                and "build" in argv
            ):
                raise TimeoutError("injected ssh timeout")
            return super().run(argv, timeout=timeout)

    _site, deployment = queued_deployment("a25-timeout")
    with pytest.raises(TimeoutError, match="injected ssh timeout"):
        execute(deployment.pk, transport=TimeoutTransport(), dns=FakeDnsProvider())

    deployment.refresh_from_db()
    assert deployment.status != Deployment.Status.SUCCEEDED
    pointer = resume_step(deployment)
    assert pointer is not None
    assert pointer.seq == 1
    assert pointer.name == DeploymentStep.Name.BUILD
    assert pointer.status != DeploymentStep.Status.SUCCEEDED
    for later in deployment.steps.filter(seq__gt=1):
        assert later.status == DeploymentStep.Status.PENDING, later.name

    src = (REPO / "tests" / "test_toxiproxy_resume.py").read_text(encoding="utf-8")
    assert "def test_ssh_timeout_mid_deploy_resumes(" in src
    assert 'pytest.mark.req("HARNESS-T3-TOXIPROXY")' in src


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_docker_run_has_unless_stopped():
    """docker run argv carries --restart unless-stopped before the image (D-026).

    Transcribes tests/test_ensure_start.py::
    test_docker_run_argv_includes_restart_unless_stopped: two literal argv
    tokens, never one =-joined token, never after the image tag.
    """
    from deploys.steps import _docker_run_argv

    argv = _docker_run_argv({
        "image_tag": "site-a25:1",
        "site_slug": "a25",
        "deployment_id": 1,
        "manifest_body": {},
    }, "site-a25-1")
    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    assert argv[-1] == "site-a25:1"
    assert argv[-3:-1] == ["--restart", "unless-stopped"], argv
    assert "--restart=unless-stopped" not in argv


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_t3_skip_cannot_verify_tier_t3(tmp_path):
    """A skipped @pytest.mark.t3 test never verifies a tier:t3 req (D-024).

    Transcribes tests/test_t3_skip_policy.py::
    test_t3_only_req_is_skipped_only_not_verified on the Task 0 throwaway-tree
    helpers, and adds the Task 16 teeth: the moment Multipass is present on
    this host, the host-without-multipass waiver lines in the real WAIVERS.md
    become illegal and this test goes red.
    """
    from test_conformance_gate import (
        T3_MARKED_TEST,
        _req,
        run_check,
        status_of,
        write_repo,
    )

    from tests.harness.multipass import waiver_illegal_if

    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T3-SKIP", tier="t3")],
        tests_src={
            "tests/test_live.py": T3_MARKED_TEST.format(
                rid="FIX-T3-SKIP", name="test_live",
            ),
        },
        outcomes={"tests/test_live.py::test_live": "skipped"},
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"a skipped-only tier:t3 req went green:\n{res.stdout}{res.stderr}"
    )
    assert status_of(root, "FIX-T3-SKIP") == "skipped-only"

    present = multipass_available()
    assert waiver_illegal_if(lambda: present) is present
    if present:
        waivers = (REPO / "WAIVERS.md").read_text(encoding="utf-8")
        offenders = [
            line for line in waivers.splitlines()
            if any(line.startswith(f"WAIVED: {rid} ") for rid in T3_WAIVED_IDS)
            and "host-without-multipass" in line
        ]
        assert offenders == [], (
            "Multipass is present on this host, so the host-without-multipass "
            f"waivers are illegal — run make test-t3 and retire them: {offenders}"
        )


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_review_round_excludes_t3_tier():
    """review-round grades the current phase without tier:t3; the all-tiers
    gate is a separate target that is never a review-round prerequisite.

    Transcribes the D-024 Makefile shape. The phase number moved from 2.5 to 3
    in phase-3 Task 0 (conformance-2.5 deleted, conformance-3 the all-tiers
    gate); the D-024 substance this clause pins — a review round never demands
    Multipass, and skips never verify tier:t3 — is unchanged.
    """
    prereqs = gates.review_round_prerequisites(REPO)
    assert "conformance" in prereqs
    assert "conformance-3" not in prereqs
    assert "conformance-2.5" not in prereqs

    review_shape = gates.recipe(REPO, "conformance")
    assert "--exclude-tier t3" in review_shape

    full_shape = gates.recipe(REPO, "conformance-3")
    assert "--exclude-tier" not in full_shape


def test_sample_site_and_sample_node_site_exist():
    """Both T3 fixture legs exist on this tree (D-030 / Q7 first leg).

    Transcribes tests/test_t3_deploy.py's sample_site_available precondition:
    sample-site/ (Django/ASGI healthz fixture) and sample-node-site/ are real
    directories with their manifest files, so the T3 dual-fixture deploy is
    not fiction. Unmarked: the deploy proof itself is tier:t3.
    """
    sample_site = REPO / "sample-site"
    node_site = REPO / "sample-node-site"
    assert (sample_site / "Dockerfile").is_file()
    assert (sample_site / "manage.py").is_file()
    assert (node_site / "package.json").is_file()
    assert (node_site / "pnpm-workspace.yaml").is_file()


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-NIGHTLY")
def test_t3_both_fixtures_ready_v2_rollback_reaper(t3_ready, settings):
    """Both fixtures deploy + HTTP ready, v2, rollback < 60s, reaper prefix only.

    Composes the tests/test_t3_deploy.py clauses on the shared session VM:
    ::test_deploy_sample_site_http_ready, ::test_deploy_sample_node_site_ready_
    before_cutover, ::test_v2_deploy_then_rollback_under_60s and
    ::test_teardown_finally_reaper_leaves_no_hub_t3_vm.
    """
    import time
    import uuid

    from deploys.models import Deployment
    from deploys.pipeline import execute
    from providers.fakes import FakeDnsProvider
    from tests.harness.multipass import NAME_PREFIX, list_names
    from tests.harness.t3_deploy import (
        execute_deployment,
        http_ready,
        node_site_body,
        queued_site,
        sample_site_available,
        sample_site_body,
        ssh_transport,
    )

    assert sample_site_available(), (
        "sample-site/ must exist on this tree; do not green HARNESS-T3-NIGHTLY "
        "from node-site alone"
    )

    s_slug = f"a25s{uuid.uuid4().hex[:6]}"
    _s, s_target, s_dep = queued_site(
        t3_ready, settings, slug=s_slug, body=sample_site_body(s_slug),
    )
    execute_deployment(s_dep, s_target)
    assert s_dep.status == Deployment.Status.SUCCEEDED
    payload = http_ready(
        s_target, domain=f"{s_slug}.example.test", listen="127.0.0.1:8088",
    )
    assert payload.get("ready") is True, payload

    n_slug = f"a25n{uuid.uuid4().hex[:6]}"
    _n, n_target, first = queued_site(
        t3_ready, settings, slug=n_slug, body=node_site_body(n_slug),
    )
    execute_deployment(first, n_target)
    assert first.status == Deployment.Status.SUCCEEDED
    payload = http_ready(
        n_target, domain=f"{n_slug}.example.test", listen="127.0.0.1:8089",
    )
    assert payload.get("ready") is True, payload

    second = Deployment.objects.create(manifest=first.manifest)
    execute_deployment(second, n_target)
    assert second.status == Deployment.Status.SUCCEEDED

    rollback_pk = Deployment.objects.create(
        manifest=first.manifest, rollback_of=first,
    ).pk
    started = time.monotonic()
    execute(rollback_pk, transport=ssh_transport(n_target), dns=FakeDnsProvider())
    elapsed = time.monotonic() - started
    assert Deployment.objects.get(pk=rollback_pk).status == Deployment.Status.SUCCEEDED
    assert elapsed < 60, f"rollback took {elapsed:.1f}s"

    names = [n for n in list_names() if n.startswith(NAME_PREFIX)]
    assert t3_ready.name in names
    assert all(n.startswith(NAME_PREFIX) for n in names)


@pytest.mark.t3
@pytest.mark.skipif(not multipass_available(), reason="multipass is not available")
@pytest.mark.req("HARNESS-T3-UFW-TRUTH")
def test_t3_ufw_truth(t3_ready):
    """ufw active + fail2ban active on a real Multipass VM, never a container.

    Composes tests/test_t3_ufw_truth.py::test_ufw_active_on_multipass_vm and
    ::test_fail2ban_active_on_multipass_vm on the shared session VM.
    """
    from tests.harness.multipass import exec as mp_exec
    from tests.harness.t3_deploy import assert_not_hub_test_target

    assert_not_hub_test_target(t3_ready)
    ufw = mp_exec(t3_ready.mp(), ["sudo", "ufw", "status"], timeout=60)
    assert "Status: active" in (ufw.stdout or ""), ufw.stdout
    f2b = mp_exec(t3_ready.mp(), ["systemctl", "is-active", "fail2ban"], timeout=60)
    assert (f2b.stdout or "").strip() == "active", f2b.stdout


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_rel_p2_24h_not_claimed():
    """REL-P2 24h stays waived, on phase 2, and the demo record names it open.

    Transcribes tests/test_drills.py::test_hub_down_does_not_claim_24h's
    waiver clause (D-026): the fingerprint is still in WAIVERS.md, the
    registry row is untouched (phase 2, verify demo), and the phase-2.5 demo
    record quotes the waiver as outstanding rather than claiming a 24h run.
    """
    waivers = (REPO / "WAIVERS.md").read_text(encoding="utf-8")
    assert WAIVER_24H in waivers

    registry = yaml.safe_load(
        (REPO / "conformance" / "requirements.yaml").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in registry["requirements"]}
    rel_p2 = by_id["REL-P2-HUB-DOWN-SITES-UP"]
    assert rel_p2["phase"] == 2
    assert rel_p2["verify"] == "demo"

    record = (REPO / "conformance" / "demos" / "phase-2.5.md").read_text(encoding="utf-8")
    assert WAIVER_24H in record, "the demo record must name the 24h waiver as outstanding"

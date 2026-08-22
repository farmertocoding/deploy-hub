"""Phase 1 acceptance — each test is a literal transcription of one milestone clause
(review3 §Q4). check.py --phase 1 requires these green (or a WAIVERS.md line).

The Phase 1 milestone (§I, as amended by the 2026-08-02 scanner addendum §S5):
"point it at one of your real projects and get an honest readiness report" — for BOTH
milestone fixtures, a Django-shaped project and the node-ts `sample-node-site/`. The
real-repo runs themselves are `verify: demo` artifacts recorded under
conformance/demos/phase-1/; these tests transcribe the same clauses against in-repo
fixtures so the gate is executable on every push.
"""
import json
import pathlib

import pytest
from dns_fixtures import default_dns_zone

from core.models import Project, Site
from deploys.models import Manifest
from scanner import core as scanner_core
from vault import service as vault_service
from vault.models import Secret
from wizard import service as wizard_service
from wizard.materialize import materialize

pytestmark = [pytest.mark.acceptance(phase=1)]

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SAMPLE_NODE_SITE = REPO / "sample-node-site"
DJANGO_FIXTURE = REPO / "tests" / "fixtures" / "django" / "uv_asgi"


@pytest.mark.req("SCAN-S1-MODULAR-DISPATCH")
def test_scan_a_django_project_yields_an_honest_tiered_report():
    """Clause: point the scanner at a Django project, get a readiness report with the
    three §5.3 tiers plus honestly-deferred sandbox checks — never executed on the
    Hub (§M1)."""
    report = scanner_core.scan(DJANGO_FIXTURE)
    assert "django" in report["modules"]
    tiers = {c["tier"] for c in report["checks"]}
    assert tiers <= set(scanner_core.TIERS)
    # Honest deferral: executing checks appear as pending_sandbox with their argv,
    # proving they were EMITTED, not run.
    assert report["sandbox_jobs"], "executing checks must be emitted as sandbox specs"
    assert any(c["tier"] == "pending_sandbox" for c in report["checks"])
    # And the report carries the one-manifest draft (§V5), not per-module manifests.
    assert "components" in report["manifest_draft"]


@pytest.mark.req("SCAN-S4-READINESS-PATTERN")
def test_scan_sample_node_site_yields_an_honest_tiered_report():
    """Clause (scanner addendum §S5): the node-ts milestone fixture scans to a
    readiness report with the §N-series checks applied."""
    report = scanner_core.scan(SAMPLE_NODE_SITE)
    assert "node-ts" in report["modules"]
    ids = {c["id"] for c in report["checks"]}
    # The §N4/§N1 invariants must have been evaluated (whatever their verdict).
    assert any("upstream" in i or "exclusive" in i for i in ids)
    assert report["manifest_draft"]["deploy_strategy"] == "recreate"


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
@pytest.mark.django_db
def test_wizard_answers_materialize_one_frozen_manifest():
    """Clause (§V5/§V6): scan -> wizard answers -> exactly ONE versioned, frozen
    manifest per Site, containing the module outputs the deploy pipeline will read."""
    report = scanner_core.scan(DJANGO_FIXTURE)
    project = Project.objects.create(
        name="accept", slug="accept", git_url="https://github.com/o/r.git",
        scan_report=json.loads(json.dumps(report)),  # exactly what storage would hold
    )
    site = Site.objects.create(project=project, name="accept-prod",
                               dns_zone=default_dns_zone())
    wizard_service.set_answers(site, {"site.domain": "accept.example.com"})

    manifest = materialize(site, confirm_warnings=True)
    assert manifest.version == 1
    assert Manifest.objects.filter(site=site).count() == 1
    # Module outputs are IN the manifest — deploys/ reads only this row (§V6).
    assert manifest.body["components"]["service"]["kind"] == "django"
    assert manifest.body["domain"] == "accept.example.com"
    # Frozen means frozen: in-place edits are refused by the model itself.
    manifest.body["domain"] = "tampered.example.com"
    with pytest.raises(ValueError):
        manifest.save()


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
@pytest.mark.django_db
def test_secret_answers_never_leave_the_vault():
    """Clause (§6.9/§7.4): a secret entered in the wizard exists afterwards ONLY as
    vault ciphertext — not in the answers table, not in the manifest, not in any
    audit row."""
    from core.models import AuditEvent

    report = scanner_core.scan(DJANGO_FIXTURE)
    project = Project.objects.create(
        name="accept2", slug="accept2", git_url="https://github.com/o/r.git",
        scan_report=json.loads(json.dumps(report)),
    )
    site = Site.objects.create(project=project, name="accept2-prod",
                               dns_zone=default_dns_zone())

    marker = "ACCEPTANCE-SECRET-MARKER-9c1f"
    secret_qid = next(q["id"] for q in report["wizard_questions"]
                      if q["kind"] == "secret")
    wizard_service.set_answers(site, {"site.domain": "a2.example.com",
                                      secret_qid: marker})
    manifest = materialize(site, confirm_warnings=True)

    # Not in the answers table.
    for answer in site.answers.all():
        assert marker not in json.dumps(answer.value) if answer.value else True
        assert answer.is_secret is (answer.secret_ref_id is not None)
    # Not in the manifest body.
    assert marker not in json.dumps(manifest.body)
    # Not in any audit row.
    for event in AuditEvent.objects.all():
        assert marker not in json.dumps(event.detail)
    # But recoverable — through the audited vault path only — from the frozen bundle.
    bundle = Secret.objects.get(pk=manifest.body["env_bundle_ref"])
    assert marker in vault_service.get(bundle).decode()


@pytest.mark.req("SCAN-S1-MODULAR-DISPATCH")
def test_cli_parity_scan_runs_django_free():
    """Clause (§5 CLI parity): `python -m hub scan` works without Django settings —
    usable as a CI gate in any repo immediately.

    Transcribed as the literal thing: a subprocess running the CLI with
    DJANGO_SETTINGS_MODULE stripped from the environment. (A first draft tried to
    assert import-cleanliness in-process, but pytest's conftest has already loaded
    Django, so that measured the test runner, not the CLI — round-2 note.)"""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    result = subprocess.run(
        [sys.executable, "-m", "hub", "scan", str(DJANGO_FIXTURE), "--json"],
        capture_output=True, text=True, cwd=REPO, env=env, timeout=60,
    )
    assert result.returncode in (0, 1), result.stderr  # 1 = blockers found, still a scan
    report = json.loads(result.stdout)
    assert "django" in report["modules"]

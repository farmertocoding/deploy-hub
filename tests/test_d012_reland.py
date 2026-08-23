"""D-012 re-land — live-path E2E (Phase 4 Task 3 / D-055 / C1).

Parser-only tests in tests/test_scanner_declarations.py keep running unmarked
(SCAN-M4). This file is the live path: scan() loads the parked parser once,
heuristic findings are labelled and still block, and wizard acceptance is the
grant. Each of the five attacks goes through wizard.materialize.preflight /
materialize against a real DB, not confirm_question_id() alone.
"""
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest
from dns_fixtures import default_dns_zone

from core.models import Project, Site
from scanner import core as scanner_core
from scanner import declarations
from wizard import service
from wizard.materialize import MaterializeRefused, materialize, preflight
from wizard.questions import missing_required, question_set

pytestmark = pytest.mark.django_db

FAKE_HIGH_ENTROPY = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P"
# Axis-1 published format, split so this file is not itself a finding.
GHP_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
DRILL_REASON = "red-team / QA drill scripts; deliberate fake credentials"
DRILL_PATH = "frontend/scripts/drill"
DRILL_CONFIRM = declarations.confirm_question_id(DRILL_PATH, DRILL_REASON)
SLOT_STYLE_ID = "scanner.test_material.1.frontend-scripts-drill"


def _declaration(path, reason=DRILL_REASON):
    return ("scanner:\n"
            "  test_material:\n"
            f"    - path: {path}\n"
            f"      reason: {reason}\n")


def _tree(tmp_path, files, name="proj"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _drill_files():
    """SATURDAYS_site shape: declared drill tree is the only blocking evidence."""
    return {
        "Dockerfile": 'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n',
        "frontend/scripts/drill/qa/03_regressions.mjs":
            f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "frontend/scripts/drill/redteam/01_rbac_money.mjs":
            f'const admin_password = "{FAKE_HIGH_ENTROPY}";\n',
        "src/app.py": "print('hello')\n",
        "deployhub.yaml": _declaration(DRILL_PATH),
    }


def _site(tmp_path, files, name="proj"):
    report = scanner_core.scan(_tree(tmp_path, files, name=name))
    project = Project.objects.create(
        name=name, slug=name.replace("_", "-"), source_kind=Project.Source.GIT,
        git_url="https://github.com/org/repo.git",
        scan_report=json.loads(json.dumps(report)),
    )
    return Site.objects.create(project=project, name=f"{name}-prod",
                               dns_zone=default_dns_zone())


def _answer_domain(site):
    service.set_answers(site, {"site.domain": "app.example.com"})


def _codes(problems):
    return [p["code"] for p in problems]


def _problem(problems, code):
    return next(p for p in problems if p["code"] == code)


def _secret(site):
    return next(c for c in site.project.scan_report["checks"]
                if c["id"] == "core.secret-scan")


def _confirm_ids(site):
    return [q.id for q in question_set(site.project)
            if q.id.startswith(declarations.CONFIRM_ID_PREFIX)]


def _rescan(site, tmp_path, files, name="proj"):
    site.project.scan_report = json.loads(json.dumps(
        scanner_core.scan(_tree(tmp_path, files, name=name))))
    site.project.save(update_fields=["scan_report"])


# ── named Task 3 tests ────────────────────────────────────────────────────────


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_declared_heuristic_still_blocks_until_wizard_accept(tmp_path):
    """Repo self-downgrade (attack 1). The file may request a labelled third
    bucket; it may not grant it. Scan-time tier stays blocker. preflight
    refuses until every confirm is True; then materialize proceeds and the
    stored report is still a blocker — answers do not rewrite the scan."""
    site = _site(tmp_path, _drill_files())
    secret = _secret(site)
    assert secret["tier"] == "blocker", secret
    assert "declared:" in secret["detail"], secret["detail"]
    assert DRILL_REASON in secret["detail"], secret["detail"]
    assert "Downgrades claimed" in secret["detail"], secret["detail"]
    assert secret["acceptance"]["blocking_only_declared"] is True
    assert DRILL_CONFIRM in secret["acceptance"]["questions"]

    _answer_domain(site)
    problems = preflight(site)
    assert "blockers_present" in _codes(problems), problems
    item = _problem(problems, "blockers_present")["items"][0]
    assert item["id"] == "core.secret-scan"
    assert [q["id"] for q in item["awaiting_acceptance"]] == [DRILL_CONFIRM]
    with pytest.raises(MaterializeRefused) as refused:
        materialize(site)
    assert refused.value.code in ("blockers_present", "answers_missing")

    service.set_answers(site, {DRILL_CONFIRM: True})
    assert preflight(site) == []
    manifest = materialize(site, confirm_warnings=True)
    assert manifest.version == 1
    assert manifest.body["declared_test_material"] == [{
        "path": DRILL_PATH,
        "reason": DRILL_REASON,
        "question_id": DRILL_CONFIRM,
        "accepted": True,
    }]
    assert _secret(site)["tier"] == "blocker"


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_proof_axis_unaffected_under_declaration(tmp_path):
    """Proof-axis bypass (attack 5). A published credential format inside the
    declared tree stays a real blocker. Every confirm answered True still
    leaves preflight/materialize refused — blocking_only_declared is
    unconditional False."""
    files = dict(_drill_files())
    files["frontend/scripts/drill/real.mjs"] = f'const t = "{GHP_TOKEN}";\n'
    site = _site(tmp_path, files, name="withproof")
    secret = _secret(site)
    assert secret["tier"] == "blocker"
    assert "[proof]" in secret["detail"], secret["detail"]
    assert secret["acceptance"]["blocking_only_declared"] is False

    _answer_domain(site)
    service.set_answers(site, {DRILL_CONFIRM: True})
    assert "blockers_present" in _codes(preflight(site))
    item = _problem(preflight(site), "blockers_present")["items"][0]
    assert "awaiting_acceptance" not in item
    with pytest.raises(MaterializeRefused) as refused:
        materialize(site, confirm_warnings=True)
    assert refused.value.code == "blockers_present"


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_root_declaration_warns_and_downgrades_nothing(tmp_path):
    """Scan-root swallow (attack 4). Declaring `.` is refused; nothing is
    accepted; no confirm is raised; heuristic findings stay unlabelled and
    blocking. There is no wizard yes that grants a swallow."""
    files = {
        "Dockerfile": 'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n',
        "src/app.py": f'admin_password = "{FAKE_HIGH_ENTROPY}"\n',
        "deployhub.yaml": _declaration("."),
    }
    site = _site(tmp_path, files, name="swallow")
    secret = _secret(site)
    assert secret["tier"] == "blocker", secret
    assert "declared:" not in secret["detail"], secret["detail"]
    assert "scan root" in secret["detail"], secret["detail"]
    assert "acceptance" not in secret
    assert _confirm_ids(site) == []
    assert missing_required(site.project, {"site.domain"}) == []

    _answer_domain(site)
    assert "blockers_present" in _codes(preflight(site))
    with pytest.raises(MaterializeRefused):
        materialize(site, confirm_warnings=True)


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_reason_edit_invalidates_confirm_id(tmp_path):
    """Reason-swap (attack 2). The operator accepted one sentence; the repo
    rewrites only the reason. Content-keyed ids mean the stored True answers
    a question nobody is asking. missing_required re-blocks; materialize
    refuses; the swapped reason is never recorded as accepted."""
    site = _site(tmp_path, _drill_files(), name="swap")
    _answer_domain(site)
    original = _confirm_ids(site)[0]
    service.set_answers(site, {original: True})
    assert preflight(site) == []

    swapped = dict(_drill_files())
    swapped["deployhub.yaml"] = _declaration(
        DRILL_PATH, "ACTUALLY covers prod secrets now")
    _rescan(site, tmp_path, swapped, name="swap")

    assert _confirm_ids(site) != [original]
    assert original not in _confirm_ids(site)
    assert "blockers_present" in _codes(preflight(site))
    assert "answers_missing" in _codes(preflight(site))
    with pytest.raises(MaterializeRefused):
        materialize(site, confirm_warnings=True)


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_index_prepend_does_not_revive_orphaned_true(tmp_path):
    """Index round-trip (attack 3). Under (index, slug) keys, prepend then
    remove handed drill back its old slot and an orphaned True re-applied.
    The index is gone from the key: drill's confirm does not move, a leftover
    slot-style True grants nothing, and the hygiene sweep is not the
    boundary."""
    from wizard.models import WizardAnswer

    site = _site(tmp_path, _drill_files(), name="roundtrip")
    _answer_domain(site)
    first = _confirm_ids(site)[0]
    service.set_answers(site, {first: True})
    WizardAnswer.objects.create(
        site=site, question_id=SLOT_STYLE_ID, value=True, is_secret=False)
    assert preflight(site) == []

    prepended = dict(_drill_files())
    prepended["frontend/scripts/aaa/readme.md"] = "nothing to see\n"
    prepended["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/aaa\n      reason: prepended tree\n"
        f"    - path: {DRILL_PATH}\n      reason: {DRILL_REASON}\n")
    _rescan(site, tmp_path, prepended, name="roundtrip")

    assert first in _confirm_ids(site), (
        "drill's confirm moved because something unrelated was added in front")
    assert SLOT_STYLE_ID not in _confirm_ids(site)
    assert "answers_missing" in _codes(preflight(site))
    with pytest.raises(MaterializeRefused):
        materialize(site, confirm_warnings=True)

    _rescan(site, tmp_path, _drill_files(), name="roundtrip")
    assert _confirm_ids(site) == [first]
    assert preflight(site) == []
    materialize(site, confirm_warnings=True)


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_scan_loads_declarations_module(tmp_path, monkeypatch):
    """Live scan loads the parser once (R7-13) and extends questions from
    declarations.confirm_questions (R7-14). Two reads of a repo-controlled
    file can disagree inside one scan."""
    files = dict(_drill_files())
    root = _tree(tmp_path, files)

    calls = []
    real_load = declarations.load
    monkeypatch.setattr(declarations, "load",
                        lambda r: (calls.append(str(r)), real_load(r))[1])
    report = scanner_core.scan(root)
    assert len(calls) == 1, f"deployhub.yaml was parsed {len(calls)} times: {calls}"
    assert DRILL_CONFIRM in [q["id"] for q in report["wizard_questions"]]
    assert "core.declaration-file" not in [c["id"] for c in report["checks"]]
    assert report["manifest_draft"]["declared_test_material"] == [
        {"path": DRILL_PATH, "reason": DRILL_REASON}]

    probe = textwrap.dedent(
        '''
        import json, os, sys, tempfile, pathlib
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
        import django
        django.setup()
        import scanner.core
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "Dockerfile").write_text(
            'FROM python:3.12\\nUSER app\\nEXPOSE 8000\\nCMD ["app"]\\n')
        (root / "frontend/scripts/drill").mkdir(parents=True)
        (root / "frontend/scripts/drill/qa.mjs").write_text(
            'const staff_password = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P";\\n')
        (root / "deployhub.yaml").write_text(
            "scanner:\\n  test_material:\\n    - path: frontend/scripts/drill\\n"
            "      reason: red-team drill scripts\\n")
        scanner.core.scan(root)
        print(json.dumps({"loaded": "scanner.declarations" in sys.modules}))
        '''
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        cwd=str(pathlib.Path(__file__).resolve().parent.parent), timeout=120)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout.strip().splitlines()[-1])
    assert outcome["loaded"] is True

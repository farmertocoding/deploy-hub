"""D-012 re-land companions — schema skew, residue, and inverted parking pins.

Live-path E2E of the five attacks lives in tests/test_d012_reland.py. This file
kept the parking-era names the design note cites (the two no-import tests,
inverted) plus the regressions that still hold after re-land: scan-time tier
does not drop, a v1 report cannot materialize, a slot-style leftover True
grants nothing.
"""
import copy
import json

import pytest

from core.models import Project, Site
from scanner import core as scanner_core
from wizard import service
from wizard.materialize import MaterializeRefused, materialize, preflight
from wizard.questions import missing_required, question_set

# A 40-char random value with no marker word — the shape the heuristic axis is for.
FAKE_HIGH_ENTROPY = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P"
DRILL_REASON = "red-team / QA drill scripts; deliberate fake credentials"

DECLARATION = ("scanner:\n"
               "  test_material:\n"
               "    - path: frontend/scripts/drill\n"
               f"      reason: {DRILL_REASON}\n")


def _tree(tmp_path, files, name="proj"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _drill_files():
    """The SATURDAYS_site shape: a drill tree of deliberate credentials, and a module
    that matches so the core suite is composed at all (D-010)."""
    return {
        "Dockerfile": 'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n',
        "frontend/scripts/drill/qa/03_regressions.mjs":
            f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "frontend/scripts/drill/redteam/01_rbac_money.mjs":
            f'const admin_password = "{FAKE_HIGH_ENTROPY}";\n',
        "src/app.py": "print('hello')\n",
    }


def _check(report, check_id):
    found = [c for c in report["checks"] if c["id"] == check_id]
    return found[0] if found else None


def _site(report, name="proj"):
    project = Project.objects.create(
        name=name, slug=name.replace("_", "-"), source_kind=Project.Source.GIT,
        git_url="https://github.com/org/repo.git",
        scan_report=json.loads(json.dumps(report)),
    )
    from dns_fixtures import default_dns_zone

    return Site.objects.create(project=project, name=f"{name}-prod",
                               dns_zone=default_dns_zone())


def _codes(problems):
    return [p["code"] for p in problems]


# ── §6.1 full-tier regression ─────────────────────────────────────────────────

def test_d012_a_declared_tree_reports_at_full_tier(tmp_path):
    """Scan-time tier does not drop (D-012r). Two deliberate credentials sit under
    a tree the repo declares as test material: labelled, still blocker. The grant
    is the wizard, not this scan."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = DECLARATION
    report = scanner_core.scan(_tree(tmp_path, files))

    secret = _check(report, "core.secret-scan")
    assert secret["tier"] == "blocker", secret["detail"]
    for rel in ("frontend/scripts/drill/qa/03_regressions.mjs:1",
                "frontend/scripts/drill/redteam/01_rbac_money.mjs:1"):
        assert f"{rel}: [heuristic, declared:" in secret["detail"], secret["detail"]
    assert "Downgrades claimed" in secret["detail"], secret["detail"]
    assert DRILL_REASON in secret["detail"]


def test_d012_no_check_anywhere_carries_an_acceptance_contract(tmp_path):
    """Re-land: only core.secret-scan publishes the contract, and only when a
    declaration labelled something. Other checks stay silent so as_dict omits
    the key on a repo that declares nothing."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = DECLARATION
    report = scanner_core.scan(_tree(tmp_path, files))

    secret = _check(report, "core.secret-scan")
    assert secret["acceptance"]["blocking_only_declared"] is True
    for check in report["checks"]:
        if check["id"] != "core.secret-scan":
            assert "acceptance" not in check, check
    assert report["manifest_draft"]["declared_test_material"] == [
        {"path": "frontend/scripts/drill", "reason": DRILL_REASON}]


@pytest.mark.django_db
def test_d012_the_wizard_asks_no_declaration_confirm(tmp_path):
    """INVERTED: the wizard asks the content-keyed confirm, and it is required.
    Name kept; the parked assertion was the defect D-012r closed."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = DECLARATION
    report = scanner_core.scan(_tree(tmp_path, files))

    confirms = [q for q in report["wizard_questions"]
                if q["id"].startswith("scanner.test_material.")]
    assert len(confirms) == 1, report["wizard_questions"]
    assert confirms[0]["kind"] == "bool"
    assert confirms[0]["default"] is None

    site = _site(report)
    assert [q.id for q in question_set(site.project)
            if q.id.startswith("scanner.test_material.")] == [confirms[0]["id"]]
    assert missing_required(site.project, {"site.domain"}) == [confirms[0]["id"]]


def test_d012_a_present_declaration_file_produces_exactly_one_notice(tmp_path):
    """The parking-era presence notice is gone: the file is honored, so a warning
    that said it was not would be a lie. No core.declaration-file line."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = DECLARATION
    report = scanner_core.scan(_tree(tmp_path, files))

    notices = [c for c in report["checks"] if c["id"] == "core.declaration-file"]
    assert notices == []


def test_d012_without_the_file_the_report_is_byte_identical(tmp_path):
    """The byte-identity property, which is why the notice is emitted from a
    `Path.is_file()` test and from nothing else: a repo that carries no
    `deployhub.yaml` must produce the report it produced before any of this landed, to
    the byte — the `as_dict` None-omission rule, and five recorded demo artifacts, both
    rest on it.

    Asserted by deleting the file from a tree that had one and re-scanning, so the two
    reports being compared come from the same bytes of source with the one difference.
    """
    files = dict(_drill_files())
    files["deployhub.yaml"] = DECLARATION
    root = _tree(tmp_path, files)
    with_file = scanner_core.scan(root)

    (root / "deployhub.yaml").unlink()
    without_file = scanner_core.scan(root)
    never = scanner_core.scan(_tree(tmp_path, _drill_files(), name="never"))

    assert not [c for c in without_file["checks"] if c["id"] == "core.declaration-file"]
    assert json.dumps(without_file, sort_keys=True) == json.dumps(never, sort_keys=True)
    assert with_file != without_file, "the notice was not emitted at all"


def test_d012_a_directory_named_deployhub_yaml_is_not_a_declaration_file(tmp_path):
    """Presence is `Path.is_file()`. A directory (or a dangling symlink) with that name
    declares nothing and carries no claim, so it raises no notice — R8-14's contract
    about what counts as "present" left with the mechanism it guarded, and the safe
    reading of "not a file" is "no claim was made"."""
    root = _tree(tmp_path, _drill_files())
    (root / "deployhub.yaml").mkdir()
    (root / "deployhub.yaml" / "inner.txt").write_text("not a claim\n", encoding="utf-8")

    report = scanner_core.scan(root)
    assert not [c for c in report["checks"] if c["id"] == "core.declaration-file"]


# ── §6.3 schema skew (R8-2's named regression) ────────────────────────────────

@pytest.mark.django_db
def test_d012_a_stored_report_from_the_previous_schema_cannot_materialize(tmp_path):
    """R8-2, closed. Bumping `SCHEMA_VERSION` is only half a fix: the rows written
    under the old meaning are still in the database, and until this refusal existed a
    v1 report — one whose `core.secret-scan` carries a baked-in `acceptance` contract,
    with a stored `True` beside it — walked into `preflight`, cleared its blocker
    through the acceptance route, and materialized a manifest under the semantics this
    phase removed.

    The refusal runs BEFORE the blocker walk on purpose: a report the wizard cannot
    interpret must not have its checks read at all, and `scan_required` is the honest
    instruction — re-scan, and the current scanner writes the current schema.
    """
    report = scanner_core.scan(_tree(tmp_path, _drill_files()))
    stale = copy.deepcopy(report)
    stale["schema_version"] = 1
    stale["manifest_draft"]["schema_version"] = 1
    confirm = "scanner.test_material.frontend-scripts-drill--a38574e34e643d90"
    for check in stale["checks"]:
        if check["id"] == "core.secret-scan":
            check["acceptance"] = {"questions": [confirm],
                                   "blocking_only_declared": True}

    site = _site(stale, name="stale")
    service.set_answers(site, {"site.domain": "app.example.com"})

    problems = preflight(site)
    assert _codes(problems) == ["scan_required"], problems
    assert "schema" in problems[0]["detail"]
    with pytest.raises(MaterializeRefused) as exc:
        materialize(site, confirm_warnings=True)
    assert exc.value.code == "scan_required"


@pytest.mark.django_db
def test_d012_a_current_report_is_not_refused_as_skewed(tmp_path):
    """The control, and the reason the comparison is against `scanner.core` rather than
    a literal: a refusal that fired on the current schema would refuse every project in
    the fleet, and a literal here would go stale at the next bump without a test
    noticing."""
    report = scanner_core.scan(_tree(tmp_path, _drill_files(), name="current"))
    assert report["schema_version"] == scanner_core.SCHEMA_VERSION
    site = _site(report, name="current")
    service.set_answers(site, {"site.domain": "app.example.com"})

    assert "scan_required" not in _codes(preflight(site))


# ── §6.4 residue safety ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_d012_stored_confirm_answers_are_inert_residue(tmp_path, client, django_user_model):
    """What is left in the answers table of a site that answered a confirm before this
    change. The rows are not deleted by any sweep — `scrub_orphaned_declaration_answers`
    left with the prefix it swept for — so they are simply answers to questions this
    project no longer has, which is a state the wizard has always had to survive.

    "Behave as if unknown" is asserted end to end rather than argued: the wizard GET,
    a PATCH, the readiness GET and the materialize POST all run with the row in place,
    and none of them 500s or lets the row change an outcome.
    """
    from wizard.models import WizardAnswer

    report = scanner_core.scan(_tree(tmp_path, dict(
        _drill_files(), **{"deployhub.yaml": DECLARATION}), name="residue"))
    site = _site(report, name="residue")
    service.set_answers(site, {"site.domain": "app.example.com"})
    # Slot-style leftover from the first (index, slug) key. Not a live confirm.
    WizardAnswer.objects.create(
        site=site,
        question_id="scanner.test_material.1.frontend-scripts-drill",
        value=True, is_secret=False)

    # A confirmed second factor is not decoration: EnrollmentRequiredMiddleware
    # (§6.10) fail-closes every /api/ path for a user who has not enrolled, so a
    # session alone reaches nothing and every assertion below would read 403.
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)

    state = client.get(f"/api/v1/sites/{site.pk}/wizard/")
    assert state.status_code == 200, state.content
    live_confirms = [q for q in state.json()["questions"]
                     if q["id"].startswith("scanner.test_material.")]
    assert live_confirms, "re-land must surface the content-keyed confirm"
    assert all(q["id"] != "scanner.test_material.1.frontend-scripts-drill"
               for q in live_confirms)
    # The slot-style leftover grants nothing; the live confirm is unanswered.
    assert state.json()["can_materialize"] is False

    patched = client.patch(
        f"/api/v1/sites/{site.pk}/wizard/",
        data=json.dumps({"answers": {"site.exposure": "public"}}),
        content_type="application/json")
    assert patched.status_code == 200, patched.content

    readiness = client.get(f"/api/v1/projects/{site.project.pk}/readiness/")
    assert readiness.status_code == 200, readiness.content

    # The declared findings block, and the stored `True` clears nothing: the row is an
    # answer to a question nobody asks, which is exactly what it has to be.
    refused = client.post(f"/api/v1/sites/{site.pk}/manifest/",
                          data=json.dumps({"confirm_warnings": True}),
                          content_type="application/json")
    assert refused.status_code == 409, refused.content
    assert refused.json()["code"] == "blockers_present", refused.json()


@pytest.mark.django_db
def test_d012_a_residue_row_cannot_be_re_submitted(tmp_path):
    """The write path's half. An id the project does not have is an unknown question,
    and unknown questions are rejected rather than ignored — a client replaying a saved
    form must not be able to write the row back in."""
    from django.core.exceptions import ValidationError

    report = scanner_core.scan(_tree(tmp_path, dict(
        _drill_files(), **{"deployhub.yaml": DECLARATION}), name="resubmit"))
    site = _site(report, name="resubmit")

    with pytest.raises(ValidationError):
        service.set_answers(
            site,
            {"scanner.test_material.1.frontend-scripts-drill": True})


# ── §7 the parked module is parked ────────────────────────────────────────────

def test_d012_no_live_code_imports_the_parked_declarations_module():
    """INVERTED on D-012 re-land (Task 3 / D-055). The parser stays unrewritten;
    the live path must import it. Relative forms still count — F1's lesson was
    that `from . import declarations` is the historical wiring line.

    Name kept so the design note's invert instruction is a grep, not a rename.
    """
    import pathlib
    import re

    repo = pathlib.Path(__file__).resolve().parent.parent
    required = {
        "scanner/core.py",
        "scanner/modules/fallbacks.py",
        "wizard/materialize.py",
    }
    pattern = re.compile(r"^\s*(from\s+scanner\s+import\s+.*\bdeclarations\b"
                         r"|from\s+scanner\.declarations\s+import\b"
                         r"|import\s+scanner\.declarations\b"
                         r"|from\s+\.+\s*import\s+.*\bdeclarations\b"
                         r"|from\s+\.+declarations\s+import\b)", re.MULTILINE)

    found = set()
    for path in sorted(repo.rglob("*.py")):
        rel = path.relative_to(repo).as_posix()
        if rel.startswith((
            ".venv/", "node_modules/", "mutants/",
            ".worktrees/", ".pytest_cache/", ".ruff_cache/", ".stage-tmp/",
        )):
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            found.add(rel)
    missing = sorted(required - found)
    assert not missing, (
        f"D-012 re-land wiring is missing a live import of scanner.declarations: "
        f"{missing}")


def test_d012_a_live_run_never_loads_the_parked_module():
    """INVERTED on D-012 re-land (Task 3 / D-055). Same subprocess pin as the
    parking era: a grep cannot see a lazy import inside scan(). After Django
    setup, live entry points, and a scan of a tree that carries deployhub.yaml,
    scanner.declarations MUST be in sys.modules.

    Name kept so the design note's invert instruction is a grep, not a rename.
    """
    import pathlib
    import subprocess
    import sys
    import textwrap

    probe = textwrap.dedent(
        '''
        import json, os, sys, tempfile, pathlib

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
        import django
        django.setup()

        # Every live entry point that could reach the scanner or the wizard.
        import hub.__main__            # the CLI
        import scanner.core
        import scanner.modules
        import wizard.materialize
        import wizard.questions
        import wizard.service
        import wizard.views

        root = pathlib.Path(tempfile.mkdtemp())
        (root / "Dockerfile").write_text(
            'FROM python:3.12\\nUSER app\\nEXPOSE 8000\\nCMD ["app"]\\n')
        (root / "frontend/scripts/drill").mkdir(parents=True)
        (root / "frontend/scripts/drill/qa.mjs").write_text(
            'const staff_password = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P";\\n')
        (root / "deployhub.yaml").write_text(
            "scanner:\\n  test_material:\\n    - path: frontend/scripts/drill\\n"
            "      reason: red-team drill scripts\\n")
        report = scanner.core.scan(root)

        print(json.dumps({
            "loaded": "scanner.declarations" in sys.modules,
            "checks": [c["id"] for c in report["checks"]],
        }))
        '''
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                            text=True, cwd=str(pathlib.Path(__file__).resolve().parent.parent),
                            timeout=120)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout.strip().splitlines()[-1])
    # INVERTED on D-012 re-land (Task 3 / D-055): a live scan of a tree that
    # carries deployhub.yaml MUST load the parser. The presence notice that
    # said the file was ignored is gone with the parking.
    assert "core.declaration-file" not in outcome["checks"], outcome
    assert outcome["loaded"] is True, (
        "a live scan did not import scanner.declarations — D-012 is re-landed "
        "and scan() must load the file once")

"""The operator's half of D-012 — round 7's R7-1 veto, made real.

WHAT ROUND 7 FOUND, and three reviewers found it independently. D-012's trust model
rests on three controls: the report always prints the claim, the operator confirms it,
and the manifest records that acceptance. Only the first existed.

  * the confirm was not in `REQUIRED_IDS` — it is a per-project id, and that set is
    static, so it could never have been in it;
  * its answer went to `body["module_answers"]` and was read by no code in the repo;
  * refusing it changed nothing, on a `fix_hint` that told the operator refusing "is
    how you say the declaration is wrong";
  * `manifest_draft["declared_test_material"]` was frozen straight from the SCAN draft,
    so the audit artifact asserted an acceptance that may never have happened.

The downgrade, meanwhile, had already been applied at scan time from a file the scanned
repo writes. A repo unilaterally downgraded its own blockers.

Joseph's ruling, 2026-08-12: **no acceptance, no downgrade.** The scanner half is in
`tests/test_scanner_declarations.py` (declared findings block, and the check publishes
`acceptance`); this file is the wizard half — the gate, the required confirm, and the
manifest that records the answer instead of the request.

Every test here builds its scan report by SCANNING A REAL TREE rather than hand-writing
one. The gate and the question set have to agree on an id derived from a repo-controlled
path, and a hand-written fixture is exactly where that agreement would go unnoticed.
"""
import pytest

from core.models import Project, Site
from scanner import core as scanner_core
from wizard import service
from wizard.materialize import MaterializeRefused, materialize, preflight
from wizard.questions import missing_required, question_set

pytestmark = pytest.mark.django_db

FAKE_HIGH_ENTROPY = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P"
GHP_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
DRILL_REASON = "red-team / QA drill scripts; deliberate fake credentials"
DRILL_CONFIRM = "scanner.test_material.1.frontend-scripts-drill"


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
    """The SATURDAYS_site shape, minus its real blockers: the declared drill tree is
    the ONLY blocking evidence, which is the case the veto is about."""
    return {
        # A module has to match or the core suite never runs (D-010).
        "Dockerfile": "FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD [\"app\"]\n",
        "frontend/scripts/drill/qa/03_regressions.mjs":
            f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "frontend/scripts/drill/redteam/01_rbac_money.mjs":
            f'const admin_password = "{FAKE_HIGH_ENTROPY}";\n',
        "src/app.py": "print('hello')\n",
        "deployhub.yaml": _declaration("frontend/scripts/drill"),
    }


def _site(tmp_path, files, name="proj"):
    report = scanner_core.scan(_tree(tmp_path, files, name=name))
    project = Project.objects.create(
        name=name, slug=name.replace("_", "-"), source_kind=Project.Source.GIT,
        git_url="https://github.com/org/repo.git", scan_report=report)
    return Site.objects.create(project=project, name=f"{name}-prod")


def _answer_domain(site):
    service.set_answers(site, {"site.domain": "app.example.com"})


def _codes(problems):
    return [p["code"] for p in problems]


def _problem(problems, code):
    return next(p for p in problems if p["code"] == code)


# ── (a) a declared-only repo blocks, and the deploy is refused ─────────────────

@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_issue_r7_1_an_unaccepted_declaration_still_refuses_the_deploy(tmp_path):
    """Acceptance (a). Before round 7 this project materialized cleanly: the scan had
    already downgraded the findings to `warning` on the repo's own say-so, so preflight
    saw no blocker at all and there was nothing for an operator to accept."""
    site = _site(tmp_path, _drill_files())
    _answer_domain(site)

    problems = preflight(site)
    assert "blockers_present" in _codes(problems), problems
    blocker = _problem(problems, "blockers_present")
    assert [i["id"] for i in blocker["items"]] == ["core.secret-scan"]

    with pytest.raises(MaterializeRefused) as exc:
        materialize(site)
    assert exc.value.code in ("blockers_present", "answers_missing")


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_issue_r7_1_the_refusal_names_the_declaration_awaiting_acceptance(tmp_path):
    """§3. "The readiness report has blockers; fix them and re-scan" is the wrong
    instruction for this blocker — there is nothing in the repo to fix, and re-scanning
    produces the identical report forever. The operator has to be able to see that the
    thing standing in the way is a claim waiting on their answer."""
    site = _site(tmp_path, _drill_files())
    _answer_domain(site)

    blocker = _problem(preflight(site), "blockers_present")
    item = blocker["items"][0]
    assert [q["id"] for q in item["awaiting_acceptance"]] == [DRILL_CONFIRM]
    assert "frontend/scripts/drill" in item["awaiting_acceptance"][0]["prompt"]
    assert "accept" in blocker["detail"]


# ── (b) accepted → preflight passes ───────────────────────────────────────────

@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1_accepting_every_declaration_clears_the_blocker(tmp_path):
    """Acceptance (b). The downgrade D-012 promised, now bought with the act it was
    always supposed to cost. Note the scan report itself does not change — it still
    reports `blocker`, honestly, because it has no answers; the gate is what moves."""
    site = _site(tmp_path, _drill_files())
    _answer_domain(site)
    service.set_answers(site, {DRILL_CONFIRM: True})

    assert preflight(site) == []
    manifest = materialize(site, confirm_warnings=True)
    assert manifest.version == 1

    check = [c for c in site.project.scan_report["checks"]
             if c["id"] == "core.secret-scan"][0]
    assert check["tier"] == "blocker", (
        "the scan report was rewritten by an answer — the report is the record of what "
        "was scanned, not of what was accepted")


# ── (c) refused → still blocked, and the refusal is on the record ─────────────

@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1_refusing_keeps_it_blocked_and_records_the_refusal(tmp_path):
    """Acceptance (c). The sentence the old `fix_hint` printed — "refusing it is how
    you say the declaration is wrong" — was false: the answer was read by nothing, so
    `False` and `True` produced the same deploy. It is true now, in both halves: the
    findings keep blocking, and the refusal reaches the frozen manifest."""
    site = _site(tmp_path, _drill_files())
    _answer_domain(site)
    service.set_answers(site, {DRILL_CONFIRM: False})

    assert "blockers_present" in _codes(preflight(site))
    with pytest.raises(MaterializeRefused) as exc:
        materialize(site)
    assert exc.value.code == "blockers_present"

    # And once the real fix lands (the repo drops the drill credentials), the refusal
    # is still what the record says happened. Simulated here by accepting a SECOND
    # site's declaration is not the point; the point is the refused entry's shape, so
    # freeze it through a tree whose declared lines are the only blocking evidence and
    # whose confirm is refused — see the manifest test below for the frozen row.
    assert exc.value.problems[0]["items"][0]["awaiting_acceptance"][0]["id"] == (
        DRILL_CONFIRM)


# ── (d) a real blocker in a declared tree is never clearable ──────────────────

@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_1_acceptance_never_clears_a_real_blocker(tmp_path):
    """Acceptance (d), and the guard §3 asks for by name. `blocking_only_declared` is
    False when a `[proof]` line shares the check, and then EVERY confirm answered
    `True` still leaves the deploy refused. Without this, "accept the declaration"
    would be a general-purpose bypass of `core.secret-scan` — the repo picks the tree,
    the operator clicks yes once, and a published credential format ships."""
    files = dict(_drill_files())
    files["frontend/scripts/drill/real.mjs"] = f'const t = "{GHP_TOKEN}";\n'
    site = _site(tmp_path, files, name="withproof")
    _answer_domain(site)
    service.set_answers(site, {DRILL_CONFIRM: True})

    check = [c for c in site.project.scan_report["checks"]
             if c["id"] == "core.secret-scan"][0]
    assert check["acceptance"]["blocking_only_declared"] is False

    assert "blockers_present" in _codes(preflight(site))
    with pytest.raises(MaterializeRefused):
        materialize(site)


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_1_a_blocker_with_no_acceptance_contract_is_unconditional(tmp_path):
    """The same guard one level down, at the gate rather than at the check: a blocker
    that publishes no `acceptance` at all — every check in the suite except this one —
    must never be cleared by an answer. Asserted directly so a future `acceptance`
    reader cannot make "no contract" mean "nothing to satisfy"."""
    files = {k: v for k, v in _drill_files().items() if k != "deployhub.yaml"}
    files[".env"] = "API_KEY=x\n"
    site = _site(tmp_path, files, name="nodecl")
    _answer_domain(site)

    check = [c for c in site.project.scan_report["checks"]
             if c["id"] == "core.secret-scan"][0]
    assert "acceptance" not in check
    assert "blockers_present" in _codes(preflight(site))


# ── (e) the confirm is required ───────────────────────────────────────────────

@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_issue_r7_1_an_unanswered_confirm_refuses_materialization(tmp_path):
    """Acceptance (e), §4. `REQUIRED_IDS` is static and these ids carry the declared
    path, so the confirm was structurally incapable of being required — "advisory in
    v1" is the right default for a module's env question and exactly the wrong one for
    the answer that authorizes a downgrade. Unanswered now refuses in the same shape as
    a missing `site.domain`."""
    site = _site(tmp_path, _drill_files())
    _answer_domain(site)

    assert missing_required(site.project, {"site.domain"}) == [DRILL_CONFIRM]
    missing = _problem(preflight(site), "answers_missing")
    assert [i["id"] for i in missing["items"]] == [DRILL_CONFIRM]
    assert "frontend/scripts/drill" in missing["items"][0]["prompt"]

    # Answering it either way satisfies "required" — refusing is an answer.
    service.set_answers(site, {DRILL_CONFIRM: False})
    assert "answers_missing" not in _codes(preflight(site))


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_issue_r7_1_a_project_with_no_declaration_requires_nothing_new(tmp_path):
    """The control for §4, and the reason `missing_required` reads the project's own
    question set rather than a widened static set: a repo with no `deployhub.yaml`
    must see the wizard it saw before this change."""
    files = {k: v for k, v in _drill_files().items() if k != "deployhub.yaml"}
    site = _site(tmp_path, files, name="nodecl2")

    assert not [q for q in question_set(site.project)
                if q.id.startswith("scanner.test_material.")]
    assert missing_required(site.project, set()) == ["site.domain"]
    assert missing_required(site.project, {"site.domain"}) == []


# ── (f) the manifest records the answer, not the request ─────────────────────

@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r7_1_the_manifest_records_the_acceptance_it_was_given(tmp_path):
    """§5. The frozen row is derived from the ANSWERS: the accepted declaration, with
    the confirm that accepted it named, so the audit trail says who was asked what."""
    site = _site(tmp_path, _drill_files())
    _answer_domain(site)
    service.set_answers(site, {DRILL_CONFIRM: True})

    body = materialize(site, confirm_warnings=True).body
    assert body["declared_test_material"] == [{
        "path": "frontend/scripts/drill",
        "reason": DRILL_REASON,
        "question_id": DRILL_CONFIRM,
        "accepted": True,
    }]
    assert "declared_test_material_refused" not in body
    # Not a bare id -> bool under `module_answers`, which is the shape round 7 found
    # nothing reads.
    assert DRILL_CONFIRM not in body.get("module_answers", {})


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r7_1_the_manifest_never_carries_an_unaccepted_declaration(tmp_path):
    """Acceptance (f), the direction that made the artifact a lie: the draft list was
    frozen verbatim, so a manifest asserted `declared_test_material` for a declaration
    the operator had refused, or had never been asked about at all.

    A refusal is RECORDED rather than dropped — an audit trail that omits the refusals
    is the same defect pointing the other way, and "this declaration was put to the
    operator and turned down" is exactly what the next reader of the repo needs.
    """
    files = dict(_drill_files())
    # A second declaration, refused, over a tree with a real `.env` so the deploy can
    # proceed on the strength of the first — otherwise nothing materializes and there
    # is no frozen row to read.
    files["frontend/scripts/spare/keep.mjs"] = "console.log('nothing');\n"
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"
        f"    - path: frontend/scripts/spare\n      reason: spare drill tree\n")
    site = _site(tmp_path, files, name="tworefused")
    _answer_domain(site)
    spare_confirm = "scanner.test_material.2.frontend-scripts-spare"
    service.set_answers(site, {DRILL_CONFIRM: True, spare_confirm: False})

    body = materialize(site, confirm_warnings=True).body
    assert body["declared_test_material"] == [{
        "path": "frontend/scripts/drill",
        "reason": DRILL_REASON,
        "question_id": DRILL_CONFIRM,
        "accepted": True,
    }]
    assert body["declared_test_material_refused"] == [{
        "path": "frontend/scripts/spare",
        "reason": "spare drill tree",
        "question_id": spare_confirm,
        "accepted": False,
    }]


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r7_1_a_manifest_with_no_declaration_gains_no_key(tmp_path):
    """The control: a project that declares nothing freezes the manifest it froze
    before this change — no `declared_test_material`, no refusal list."""
    files = {k: v for k, v in _drill_files().items() if k != "deployhub.yaml"}
    files.pop("frontend/scripts/drill/qa/03_regressions.mjs")
    files.pop("frontend/scripts/drill/redteam/01_rbac_money.mjs")
    site = _site(tmp_path, files, name="clean")
    _answer_domain(site)

    body = materialize(site, confirm_warnings=True).body
    assert "declared_test_material" not in body
    assert "declared_test_material_refused" not in body

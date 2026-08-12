"""Declared test-material trees — `deployhub.yaml`, follow-up 2 (spec-declared-test-material.md).

The ruling (Joseph, 2026-08-11): a repo declares its own drill/QA trees, the scan
report always says a downgrade was claimed and by which declaration, and the wizard
makes accepting it the operator's act. Hub-side operator waivers and
scanner-guesses-from-the-path-name were both considered and not chosen — the second is
round-6b's `spec`/`fixtures`/`e2e` mistake, which is why nothing here classifies a
directory by its name.

Motivating measurement: 20 of SATURDAYS_site's 26 blocking heuristic lines are
`frontend/scripts/drill/**` — red-team and QA scripts holding deliberate
`admin_password` literals. Test material by intent and by content, but not by path, so
`core.secret-scan` had no honest way to know.

Every downgrade path in here is written against the same rule N6 established: scope the
AXIS, never the walk, and keep the `[proof]` axis and the `.env` handler at full tier.
"""
import pathlib

import pytest

from scanner import core, declarations
from scanner.modules import fallbacks

REPO = pathlib.Path(__file__).resolve().parent.parent

# A 40-char random value with no marker word — the shape the heuristic axis is for.
FAKE_HIGH_ENTROPY = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P"
GHP_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"

DRILL_REASON = "red-team / QA drill scripts; deliberate fake credentials"

# Round 7 (R7-1). The section header stopped saying "not blocking", because until the
# operator accepts the claim it IS blocking — the old wording asserted an outcome the
# scanner cannot know, since the scanner has no answers.
DECLARED_SECTION_HEADER = (
    "Declared test material (downgrade requested by deployhub.yaml — these findings "
    "block until you accept it in the wizard):")


def _drill_confirm_id(reason=DRILL_REASON, path="frontend/scripts/drill"):
    """The confirm id, derived rather than typed. Round 7's second veto made the id a
    function of the CLAIM, so a literal in a test would be a second implementation of
    the very derivation the fix exists to keep single."""
    return declarations.confirm_question_id(path, reason)


def _tree(tmp_path, files, name="proj"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _declaration(path, reason=DRILL_REASON):
    return ("scanner:\n"
            "  test_material:\n"
            f"    - path: {path}\n"
            f"      reason: {reason}\n")


def _drill_files():
    """The SATURDAYS_site shape: a drill tree of deliberate credentials."""
    return {
        "frontend/scripts/drill/qa/03_regressions.mjs":
            f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "frontend/scripts/drill/redteam/01_rbac_money.mjs":
            f'const admin_password = "{FAKE_HIGH_ENTROPY}";\n',
        "src/app.py": "print('hello')\n",
    }


def _secret_scan(root):
    results = {c.id: c for c in fallbacks.common_checks(root)}
    return results["core.secret-scan"]


# ── what a declaration does ────────────────────────────────────────────────────

@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_a_declared_tree_downgrades_its_heuristic_findings_with_the_label(tmp_path):
    """The measured case. Two deliberate credentials in a declared drill tree move into
    the third bucket, and every one of them still appears — with the path and the repo's
    own words attached, so the reader sees who claimed what.

    ROUND 7 (R7-1) CHANGED THE TIER THIS ASSERTS. The routing is the same; what the
    routing costs is not. Until the operator accepts the declaration these findings
    still block, so the tier stays `blocker` — see the round-7 section below.
    """
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    label = f'[heuristic, declared: frontend/scripts/drill — "{DRILL_REASON}"]'
    assert result.detail.count(label) == 2, result.detail
    for rel in ("frontend/scripts/drill/qa/03_regressions.mjs:1",
                "frontend/scripts/drill/redteam/01_rbac_money.mjs:1"):
        assert rel in result.detail, f"{rel} vanished from the report"


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_the_byte_identical_tree_without_the_declaration_still_blocks(tmp_path):
    """The control. Nothing about the drill tree itself is what quiets it — only the
    declaration, which is a reviewable file in the scanned repo."""
    result = _secret_scan(_tree(tmp_path, _drill_files()))
    assert result.tier == "blocker", result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail
    assert "declared" not in result.detail


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_a_declaration_covers_only_its_own_subtree(tmp_path):
    """Prefix matching is on PATH SEGMENTS, not on strings: `drill` must not cover
    `drillbits`, and a declaration deep in the tree must not quiet its siblings."""
    files = {
        "frontend/scripts/drill/qa.mjs": f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "frontend/scripts/drillbits/real.mjs":
            f'const api_key = "{FAKE_HIGH_ENTROPY}";\n',
        "deployhub.yaml": _declaration("frontend/scripts/drill"),
    }
    result = _secret_scan(_tree(tmp_path, files))
    assert result.tier == "blocker", result.detail
    assert "frontend/scripts/drillbits/real.mjs:1: [heuristic]" in result.detail
    assert "declared: frontend/scripts/drill" in result.detail


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_declared_material_never_merges_with_auto_detected_test_material(tmp_path):
    """Two different claims: one the scanner made (a `tests/` directory) and one the
    repo made about itself. A reader who cannot tell them apart cannot audit either."""
    files = dict(_drill_files())
    files["tests/test_login.py"] = f'password = "{FAKE_HIGH_ENTROPY}"\n'
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert "Also in test material (not blocking):" in result.detail
    assert DECLARED_SECTION_HEADER in result.detail
    auto_section = result.detail.split("Also in test material (not blocking):", 1)[1]
    auto_lines = auto_section.split("Declared test material", 1)[0]
    assert "tests/test_login.py:1" in auto_lines
    assert "drill" not in auto_lines, (
        "a declared finding was filed under the scanner's own auto-detection")


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_the_report_header_names_the_claim_even_when_it_downgraded_nothing(tmp_path):
    """`N findings` including N=0. A declaration that quiets nothing is still an
    assertion the repo made about itself, and the report is where it is visible —
    otherwise a stale claim only surfaces the day it starts hiding something."""
    with_findings = _secret_scan(_tree(tmp_path, dict(
        _drill_files(), **{"deployhub.yaml": _declaration("frontend/scripts/drill")})))
    assert ('Downgrades claimed by deployhub.yaml: frontend/scripts/drill '
            f'("{DRILL_REASON}", 2 findings)') in with_findings.detail

    quiet = _tree(tmp_path, {
        "frontend/scripts/drill/qa.mjs": "console.log('nothing to see');\n",
        "src/app.py": "print('hello')\n",
        "deployhub.yaml": _declaration("frontend/scripts/drill"),
    }, name="quiet")
    result = _secret_scan(quiet)
    assert result.tier == "ok", result.detail
    assert ('Downgrades claimed by deployhub.yaml: frontend/scripts/drill '
            f'("{DRILL_REASON}", 0 findings)') in result.detail


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_each_declaration_becomes_a_wizard_question_and_is_recorded_in_the_manifest(
        tmp_path):
    """§F5 action-tier friction: the downgrade is the repo's claim, the acceptance is
    the operator's, and the manifest is where that acceptance is logged."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"   # so a module matches
    report = core.scan(_tree(tmp_path, files))

    questions = [q for q in report["wizard_questions"]
                 if q["id"].startswith("scanner.test_material.")]
    assert len(questions) == 1, report["wizard_questions"]
    question = questions[0]
    assert question["kind"] == "bool"
    assert "frontend/scripts/drill" in question["prompt"]
    assert DRILL_REASON in question["prompt"]
    # `wizard.materialize._env_name` turns any question id containing `.env.` into an
    # environment variable name. A declared path is repo-controlled text going into an
    # id, so it must never be able to reach that branch.
    assert ".env." not in question["id"], (
        "a declared path turned a confirm question into an env var")

    assert report["manifest_draft"]["declared_test_material"] == [
        {"path": "frontend/scripts/drill", "reason": DRILL_REASON}]


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_a_repo_with_no_declaration_is_untouched(tmp_path):
    """The five recorded demos must not move. No header, no bucket, no wizard
    question, no manifest key — a repo that declares nothing sees the scanner it had
    before this feature existed."""
    files = dict(_drill_files())
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    report = core.scan(_tree(tmp_path, files))

    assert "declared_test_material" not in report["manifest_draft"]
    assert not [q for q in report["wizard_questions"]
                if q["id"].startswith("scanner.test_material.")]
    secret = [c for c in report["checks"] if c["id"] == "core.secret-scan"][0]
    assert "Downgrades claimed" not in secret["detail"]
    assert "declared" not in secret["detail"]


# ── the guards ─────────────────────────────────────────────────────────────────

@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_a_proof_credential_inside_a_declared_tree_still_blocks(tmp_path):
    """Mirrors N6 exactly: the declaration scopes the HEURISTIC axis and nothing else.
    A real `ghp_…` token in a drill script is a real token — drills use fake-format
    values, and a repo cannot declare its way out of a published credential format."""
    files = dict(_drill_files())
    files["frontend/scripts/drill/qa/setup.mjs"] = f'const t = "{GHP_TOKEN}";\n'
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert "[proof] GitHub token" in result.detail
    assert "frontend/scripts/drill/qa/setup.mjs:1" in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_an_env_file_inside_a_declared_tree_still_counts(tmp_path):
    """The `.env` handler is the other full-tier axis. `vercel env pull` writes real
    production credentials into whatever directory it is run in, and a drill tree is
    not a safe place for that file either."""
    files = dict(_drill_files())
    files["frontend/scripts/drill/.env"] = "DATABASE_PASSWORD=hunter2\n"
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert ("frontend/scripts/drill/.env: .env file present in the scan tree"
            in result.detail)


@pytest.mark.req("SCAN-DECLARED-GUARDS")
@pytest.mark.parametrize("path", [".", "./", "", "/", "  ", "./."])
def test_declaring_the_scan_root_is_rejected(tmp_path, path):
    """A declaration that swallows the whole repo is indistinguishable from hiding."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration(f'"{path}"')
    result = _secret_scan(_tree(tmp_path, files, name=f"root{abs(hash(path))}"))

    assert result.tier == "blocker", result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail
    assert "scan root" in result.detail
    assert "Downgrades claimed" not in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
@pytest.mark.parametrize("path", ["../outside", "frontend/../../etc",
                                  "/etc/secrets", "frontend/scripts/*",
                                  "frontend/scripts/dr?ll"])
def test_an_escaping_or_globbed_path_is_rejected(tmp_path, path):
    """`..`, absolute paths and globs are all ways to declare something other than the
    directory the reviewer read in the diff."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration(f'"{path}"')
    result = _secret_scan(_tree(tmp_path, files, name=f"esc{abs(hash(path))}"))

    assert result.tier == "blocker", result.detail
    assert "deployhub.yaml" in result.detail
    assert "Downgrades claimed" not in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_a_declared_path_missing_from_the_tree_warns_as_stale(tmp_path):
    """A declaration that outlives its directory is exactly the rot the report has to
    surface: it is a live claim that nobody re-read, and the next directory to be given
    that name inherits it."""
    files = {
        "src/app.py": "print('hello')\n",
        "deployhub.yaml": _declaration("frontend/scripts/drill"),
    }
    result = _secret_scan(_tree(tmp_path, files))
    assert result.tier == "warning", result.detail
    assert "frontend/scripts/drill" in result.detail
    assert "does not exist" in result.detail
    assert "Downgrades claimed" not in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
@pytest.mark.parametrize("manifest", sorted(declarations.SCANNER_KEY_FILES))
def test_a_path_holding_a_manifest_the_scanner_keys_on_is_rejected(tmp_path, manifest):
    """The subtler half of the root guard. `backend/` holding `manage.py` is not a
    drill tree, whatever the declaration says, and a declaration around a project's own
    manifest is a repo hiding its production code from the check that reads it.

    Parametrized off the constant, so a name cannot be added without a test (the N6
    lesson: seven of eleven names in one list were asserted by nothing)."""
    files = dict(_drill_files())
    files[f"frontend/scripts/drill/{manifest}"] = "{}\n"
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files, name=f"m{abs(hash(manifest))}"))

    assert result.tier == "blocker", result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail
    assert manifest in result.detail
    assert "Downgrades claimed" not in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_the_scanner_key_file_set_is_frozen_and_covers_the_module_manifests(tmp_path):
    """Freezing the set makes both directions — adding a name and deleting one — a
    reviewed act, and the second assertion keeps it honest against the module that
    already has such a list: `StaticModule` decides "is there a server here" from
    `_SERVER_MANIFESTS`, and anything that answers that question must also refuse a
    declaration wrapped around it."""
    assert declarations.SCANNER_KEY_FILES == frozenset({
        "package.json", "pyproject.toml", "requirements.txt", "manage.py",
        "Dockerfile", "go.mod", "Gemfile", "composer.json",
        "pnpm-workspace.yaml", "settings.py", "deployhub.yaml",
    })
    assert set(fallbacks._SERVER_MANIFESTS) <= declarations.SCANNER_KEY_FILES


@pytest.mark.req("SCAN-DECLARED-GUARDS")
@pytest.mark.parametrize("body", [
    "scanner: [this is not a mapping\n",                     # unparseable YAML
    "scanner: a string\n",                                   # wrong type, one level in
    "scanner:\n  test_material: {}\n",                       # wrong type, list expected
    "scanner:\n  test_material:\n    - frontend/scripts/drill\n",   # entry not a mapping
    "scanner:\n  test_material:\n    - path: frontend/scripts/drill\n",   # no reason
    "scanner:\n  test_material:\n    - path: frontend/scripts/drill\n      reason: ''\n",
    "scanner:\n  test_material:\n    - path: 17\n      reason: numeric path\n",
    "- just\n- a\n- list\n",                                 # not a mapping at all
])
def test_a_malformed_deployhub_yaml_warns_and_applies_nothing(tmp_path, body):
    """A config file the scanner cannot read must never take the scan down with it —
    and must never be read optimistically either. Nothing is downgraded, and the report
    names the file."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = body
    result = _secret_scan(_tree(tmp_path, files, name=f"bad{abs(hash(body))}"))

    assert result.tier == "blocker", result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail
    assert "deployhub.yaml" in result.detail
    assert "Downgrades claimed" not in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_no_other_check_reads_the_declaration(tmp_path):
    """Scope widens by decision, not by drift. Every core check except
    `core.secret-scan` must return exactly what it returns without the file."""
    files = dict(_drill_files())
    files["package.json"] = '{"name": "app"}\n'          # gives lockfile/gitignore work
    files[".gitignore"] = "*.pyc\n"
    plain = _tree(tmp_path, files, name="plain")
    declared = _tree(tmp_path, dict(
        files, **{"deployhub.yaml": _declaration("frontend/scripts/drill")}),
        name="declared")

    def others(root):
        return {c.id: (c.tier, c.detail) for c in fallbacks.common_checks(root)
                if c.id != "core.secret-scan"}

    assert others(plain) == others(declared)


# ── adversarial round 1: the report is part of the attack surface ──────────────
#
# Everything below came out of the independent adversarial pass on the first cut, and
# every one of them was demonstrated by a real scan rather than argued. The theme of
# finding 1 is the one worth carrying forward: the check detail is EVIDENCE a reviewer
# reads to decide whether a deploy is safe, and until this round the scanned repo could
# write arbitrary lines into it.


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_a_reason_cannot_forge_report_lines(tmp_path):
    """The forged-evidence case, verbatim from the adversarial pass.

    `reason` was copied into the header, into every `[heuristic, declared: …]` label and
    into the wizard prompt, newlines and all — so a repo author could write a fake
    section header and fake findings into the report a reviewer trusts, at every tier
    including `ok`. Text that will be read as the justification for hiding findings is
    exactly what was written or it is refused; it is never quietly repaired, because a
    collapsed forgery is still a claim nobody wrote.
    """
    forged = ('drill scripts\\"\\n\\nAlso in test material (not blocking):\\n'
              'src/app.py:1: [heuristic] hardcoded api_key value')
    files = dict(_drill_files())
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/drill\n"
        f'      reason: "{forged}"\n')
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed" not in result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail
    # None of the forged text may reach the report as text a reader could mistake for
    # the scanner's own output.
    assert "Also in test material (not blocking):" not in result.detail
    assert "src/app.py:1: [heuristic] hardcoded api_key value" not in result.detail
    # The refusal names the entry by index and field and gives the offset, and quotes
    # NONE of the value: an escaped copy of a forged section header is still that
    # header, sitting in the report where a reader greps for one.
    assert "entry 1" in result.detail
    assert "control character" in result.detail
    assert "`reason`" in result.detail
    assert "drill scripts" not in result.detail
    for line in result.detail.splitlines():
        assert not line.startswith("src/app.py:1"), line


@pytest.mark.req("SCAN-DECLARED-GUARDS")
@pytest.mark.parametrize("payload,where", [
    ('"line one\\nline two"', "reason"),
    ('"tabbed\\there"', "reason"),
    ('"carriage\\rreturn"', "reason"),
    ('"bell\\a"', "reason"),
    ('"delete\\x7f"', "reason"),
])
def test_any_control_character_in_a_reason_is_a_malformed_entry(tmp_path, payload, where):
    """Not just newline. A tab fakes indentation, a CR overwrites the line a terminal
    already drew, and `\\x7f` renders as nothing at all — every one of them edits what
    the reviewer sees rather than what the file says."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/drill\n"
        f"      {where}: {payload}\n")
    result = _secret_scan(_tree(tmp_path, files, name=f"c{abs(hash(payload))}"))

    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed" not in result.detail
    assert "control character" in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_a_control_character_in_a_path_is_a_malformed_entry(tmp_path):
    """The path is embedded in the same three places the reason is."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        '    - path: "frontend/scripts/drill\\nfaked"\n'
        f"      reason: {DRILL_REASON}\n")
    result = _secret_scan(_tree(tmp_path, files))
    assert result.tier == "blocker", result.detail
    assert "control character" in result.detail
    assert "Downgrades claimed" not in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_a_reason_longer_than_the_cap_is_a_malformed_entry(tmp_path):
    """A wall of text is the other way to edit the report: the findings count sits at
    the end of the header line, and 40 KB of prose in front of it buries the number the
    reader came for. The boundary is asserted in both directions so the cap cannot
    drift by an off-by-one."""
    at_cap = "x" * declarations.MAX_REASON_CHARS
    over_cap = "x" * (declarations.MAX_REASON_CHARS + 1)

    accepted = _tree(tmp_path, dict(_drill_files(), **{
        "deployhub.yaml": _declaration("frontend/scripts/drill", at_cap)}),
        name="at_cap")
    assert _secret_scan(accepted).tier == "blocker", _secret_scan(accepted).detail
    assert "Downgrades claimed" in _secret_scan(accepted).detail

    refused = _tree(tmp_path, dict(_drill_files(), **{
        "deployhub.yaml": _declaration("frontend/scripts/drill", over_cap)}),
        name="over_cap")
    result = _secret_scan(refused)
    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed" not in result.detail
    assert str(declarations.MAX_REASON_CHARS) in result.detail
    assert over_cap not in result.detail, "the refusal pasted the wall of text back in"


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_a_manifest_the_scanner_walks_is_never_hidden_from_the_guard(tmp_path):
    """The N6 class, one layer in: the guard pruned `vendor`, `.hg` and `.svn` while the
    secret scanner's own walk does not, so `svc/vendor/package.json` was invisible to
    the rejection guard and `svc/**` was downgraded anyway. A guard that skips a
    directory the check still reads is a guard with a hole in it."""
    files = {
        "svc/vendor/package.json": '{"name": "svc"}\n',
        "svc/drill.mjs": f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "deployhub.yaml": _declaration("svc"),
    }
    result = _secret_scan(_tree(tmp_path, files))
    assert result.tier == "blocker", result.detail
    assert "package.json" in result.detail
    assert "Downgrades claimed" not in result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_the_guard_prunes_nothing_the_secret_scanner_walks():
    """The parity assertion behind the test above, stated as a property so the two
    lists cannot drift apart again: the guard may skip a directory only where the
    scanner skips it too."""
    assert declarations.guard_prune_dirs() <= fallbacks._SKIP_DIRS


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_an_oversized_declaration_file_is_refused_unparsed(tmp_path):
    """`load` used to read the file unbounded, so a repo could hand the scanner a
    gigabyte of YAML. A config file larger than a quarter of a megabyte is not a config
    file; it is refused before the parser sees it, and downgrades nothing."""
    body = _declaration("frontend/scripts/drill") + ("# " + "y" * 200 + "\n") * 2000
    assert len(body.encode("utf-8")) > declarations.MAX_DECLARATION_BYTES
    files = dict(_drill_files())
    files["deployhub.yaml"] = body
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed" not in result.detail
    assert "too large" in result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail


# ── adversarial round 2: the line break is whatever the RENDERER thinks it is ───
#
# Round 1 refused C0 and DEL and called the forgery closed. It was not: `str.splitlines`
# — which is what builds this report's lines, and what any Python reader of it will use
# — also breaks on U+2028, U+2029 and U+0085, and a browser rendering the JSON breaks on
# the first two as well (they are JS LineTerminators). The PATH vector was the worse of
# the two, because a directory really can be named with U+2028 on every filesystem the
# scanner runs on: the declaration passed the existence check and was ACCEPTED, and the
# forged line appeared in the header and in every label.
#
# The class this validator refuses is therefore defined by what RENDERERS treat as
# structure, not by what YAML admits. Escapes are spelled out below rather than pasted
# as literals, for the same reason the refusal quotes nothing: a test file is read too.

LSEP = "\u2028"        # LINE SEPARATOR — a line break to splitlines() and to JS
PSEP = "\u2029"        # PARAGRAPH SEPARATOR — the same
NEL = "\u0085"         # NEXT LINE — the one C1 character PyYAML lets through
RLO = "\u202e"         # RIGHT-TO-LEFT OVERRIDE — reverses rendered order
ZWSP = "\u200b"        # ZERO WIDTH SPACE — renders as nothing at all
CHINESE_REASON = "\u7d05\u968a\u6f14\u7df4\u7528\u5047\u5bc6\u78bc"   # 紅隊演練用假密碼


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_a_unicode_line_separator_in_a_reason_cannot_forge_report_lines(tmp_path):
    """The verifier's round-2 case. `[\\x00-\\x1f\\x7f]` does not contain U+2028, and
    every line of this report is produced by `splitlines`, which does."""
    forged = (f"drill scripts{LSEP}{LSEP}Also in test material (not blocking):{LSEP}"
              f"src/app.py:1: [heuristic] hardcoded api_key value")
    files = dict(_drill_files())
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/drill\n"
        f'      reason: "{forged}"\n')
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed" not in result.detail
    lines = result.detail.splitlines()
    for line in lines:
        assert line.strip() != "Also in test material (not blocking):", lines
        assert not line.startswith("src/app.py:1"), lines


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_a_unicode_line_separator_in_a_real_directory_name_is_refused(tmp_path):
    """The path vector, with the directory actually on disk — the case round 1 left
    fully open. A filesystem accepts every byte but `/` and NUL, so the declaration
    pointed at a real tree, passed the existence check and was accepted."""
    # No colon anywhere in the name, deliberately: the first cut refused this case by
    # accident, through the Windows drive-letter test (`":" in parts[0]`), which the
    # forged section header happened to contain. A forgery that avoids the colon showed
    # the vector was wide open.
    forged_dir = f"drill{LSEP}Also in test material (not blocking)"
    files = dict(_drill_files())
    files[f"{forged_dir}/qa.mjs"] = f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n'
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        f'    - path: "{forged_dir}"\n'
        f"      reason: {DRILL_REASON}\n")
    root = _tree(tmp_path, files)
    assert (root / forged_dir).is_dir(), "the fixture must put the real directory there"

    result = _secret_scan(root)
    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed" not in result.detail
    for line in result.detail.splitlines():
        assert line.strip() != "Also in test material (not blocking)", result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
@pytest.mark.parametrize("char,name", [
    (LSEP, "U+2028 LINE SEPARATOR"),
    (PSEP, "U+2029 PARAGRAPH SEPARATOR"),
    # NEL is passed as its YAML escape, not as a literal: PyYAML FOLDS a literal
    # U+0085 inside a quoted scalar to a space (it is a line break to the scanner), so
    # the escape is the only way one reaches a value — and it does reach it.
    ("\\u0085", "U+0085 NEXT LINE (YAML escape)"),
    (RLO, "U+202E RIGHT-TO-LEFT OVERRIDE"),
    (ZWSP, "U+200B ZERO WIDTH SPACE"),
    ("\ufeff", "U+FEFF ZERO WIDTH NO-BREAK SPACE"),
    ("\u2060", "U+2060 WORD JOINER"),
    ("\u200f", "U+200F RIGHT-TO-LEFT MARK"),
    ("\u0091", "U+0091 PRIVATE USE ONE (C1)"),
    # The Trojan-Source family (CVE-2021-42574): bidi ISOLATES are the modern
    # reordering mechanism — the one that made source code read as one program and
    # compile as another — and the round-2 class covered only the older embeddings and
    # overrides. Same argument, same field: a reason is read by a human to decide
    # whether hiding findings is justified.
    ("\u2066", "U+2066 LEFT-TO-RIGHT ISOLATE"),
    ("\u2067", "U+2067 RIGHT-TO-LEFT ISOLATE"),
    ("\u2068", "U+2068 FIRST STRONG ISOLATE"),
    ("\u2069", "U+2069 POP DIRECTIONAL ISOLATE"),
    ("\u061c", "U+061C ARABIC LETTER MARK"),
])
def test_deceptive_code_points_are_refused_in_both_fields(tmp_path, char, name):
    """Two families, one rule. The line-breaking ones forge structure; the bidi and
    zero-width ones forge appearance — a reason reading `drill scripts` on screen while
    the bytes say something else is a justification nobody can review."""
    for field in ("reason", "path"):
        files = dict(_drill_files())
        if field == "reason":
            body = ("scanner:\n  test_material:\n"
                    "    - path: frontend/scripts/drill\n"
                    f'      reason: "drill{char}scripts"\n')
        else:
            body = ("scanner:\n  test_material:\n"
                    f'    - path: "frontend/scripts/dr{char}ill"\n'
                    f"      reason: {DRILL_REASON}\n")
        files["deployhub.yaml"] = body
        result = _secret_scan(_tree(tmp_path, files,
                                    name=f"u{abs(hash(char + field))}"))
        assert result.tier == "blocker", f"{name} in {field}: {result.detail}"
        assert "Downgrades claimed" not in result.detail, f"{name} in {field}"


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_an_ordinary_non_ascii_reason_is_accepted_end_to_end(tmp_path):
    """The over-correction guard, and the one that matters most for this fleet: every
    repo it scans is Taiwanese, and the reasons will be written in Chinese. A validator
    that refused 紅隊演練用假密碼 would make the feature unusable by the people it was
    built for — refusing code points that lie about STRUCTURE is not refusing a script.
    """
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill", CHINESE_REASON)
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert (f"Downgrades claimed by deployhub.yaml: frontend/scripts/drill "
            f'("{CHINESE_REASON}", 2 findings)') in result.detail
    assert f'declared: frontend/scripts/drill — "{CHINESE_REASON}"' in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_the_json_cli_emits_the_reason_raw_so_the_validator_is_the_guarantee(
        tmp_path, capsys):
    """`python -m hub scan --json` dumps with `ensure_ascii=False`, so a reason reaches
    a downstream JS/HTML renderer as the characters themselves rather than as `\\uXXXX`
    escapes. That is deliberate and stays — changing it would move the recorded demo
    artifacts — and it is precisely why the refusal above has to cover what a RENDERER
    treats as structure: nothing between this validator and the browser will escape a
    U+2028 on the way. This test is the standing assertion of that division of labour;
    if the CLI ever starts escaping, the comment above is wrong and should be re-read.
    """
    import hub.__main__ as cli

    files = dict(_drill_files())
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill", CHINESE_REASON)
    root = _tree(tmp_path, files)

    cli.main(["scan", str(root), "--json"])
    out = capsys.readouterr().out
    assert CHINESE_REASON in out, "the CLI stopped emitting raw non-ASCII"
    assert "\\u2028" not in out and LSEP not in out


# ── round 7: no acceptance, no downgrade (R7-1 veto) ───────────────────────────
#
# What three reviewers found independently: D-012's trust model had three controls and
# only one of them existed. The claim was printed (control 1, real). The confirm was
# raised (control 2, cosmetic — not in REQUIRED_IDS, answer written to `module_answers`
# and read by nothing, refusing it changed nothing). The manifest recorded the
# acceptance (control 3, false — populated straight from the scan draft, so it asserted
# an acceptance that may never have happened).
#
# Joseph's ruling, 2026-08-12: NO ACCEPTANCE, NO DOWNGRADE. A declaration is a REQUEST.
# The tests below are the two halves of that: the scanner reports the request and keeps
# the findings blocking (here), and the wizard owns the acceptance
# (tests/test_wizard_declaration_acceptance.py).


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1_a_declared_only_repo_blocks_until_the_operator_accepts(tmp_path):
    """The veto, at its narrowest. The repo's only blocking evidence is heuristic lines
    under a tree it declared itself, and before round 7 that was enough to make the
    scan report `warning` — a repo downgrading its own blockers with a file it writes.
    The findings still route to the third bucket; the tier no longer drops for them.
    """
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert result.title == "Secrets in a declared tree — your acceptance is required"
    # Still the third bucket, still labelled, still not merged with anything.
    assert result.detail.count("[heuristic, declared: frontend/scripts/drill") == 2


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1_the_section_header_no_longer_asserts_an_outcome(tmp_path):
    """`not blocking` was a claim about the operator's answer, made by the one component
    that has no answers to read. What the scanner can say honestly is what was asked
    for and what would clear it."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files))

    assert DECLARED_SECTION_HEADER in result.detail
    assert "Declared test material (downgrade claimed by deployhub.yaml, not " \
           "blocking):" not in result.detail


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1_the_acceptance_contract_names_the_confirms_that_clear_it(tmp_path):
    """§2's structured field, so preflight never parses this prose to decide a gate.

    `questions` is exactly the confirm ids whose `True` clears what this check
    downgraded, and it is the SAME id the wizard raises — one derivation, in
    `declarations`, or the gate opens for a question nobody was asked.
    """
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    report = core.scan(_tree(tmp_path, files))

    check = [c for c in report["checks"] if c["id"] == "core.secret-scan"][0]
    assert check["acceptance"] == {
        "questions": [_drill_confirm_id()],
        "blocking_only_declared": True,
    }
    asked = [q["id"] for q in report["wizard_questions"]
             if q["id"].startswith("scanner.test_material.")]
    assert asked == check["acceptance"]["questions"], (
        "the ids the gate opens for and the ids the wizard asks about diverged")


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_1_a_real_blocker_beside_a_declaration_is_never_only_declared(tmp_path):
    """§2/§3's guard: acceptance may clear what the declaration downgraded and nothing
    else. A `[proof]` line inside the declared tree is the case that matters — the tree
    is the same tree, the operator's answer is the same answer, and the deploy must
    stay refused however they answer it."""
    files = dict(_drill_files())
    files["frontend/scripts/drill/real.mjs"] = f'const t = "{GHP_TOKEN}";\n'
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    report = core.scan(_tree(tmp_path, files))

    check = [c for c in report["checks"] if c["id"] == "core.secret-scan"][0]
    assert check["tier"] == "blocker"
    assert check["title"] == "Committed secrets detected"
    assert check["acceptance"]["blocking_only_declared"] is False
    assert check["acceptance"]["questions"] == [_drill_confirm_id()]


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1_a_declaration_that_downgraded_nothing_is_not_a_gate_key(tmp_path):
    """`questions` is "what would clear what this check downgraded", not "every
    declaration in the file". A second declaration quieting nothing must not become
    another id that has to be answered `True` before the first one's findings clear —
    and, the direction that matters, must not become an id whose `True` clears
    findings it never touched."""
    files = dict(_drill_files())
    files["frontend/scripts/quiet/readme.md"] = "nothing to see\n"
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"
        f"    - path: frontend/scripts/quiet\n      reason: {DRILL_REASON}\n")
    result = _secret_scan(_tree(tmp_path, files))

    assert result.acceptance["questions"] == [_drill_confirm_id()]
    # The claim is still printed for both — a declaration that quiets nothing today is
    # still a live assertion about the tree (D-012, unchanged by round 7).
    assert result.detail.count("Downgrades claimed by deployhub.yaml") == 2


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1_a_report_with_no_declaration_carries_no_acceptance_key(tmp_path):
    """The five recorded demo artifacts, again. `acceptance` is omitted from
    `as_dict()` rather than serialized as `null`, so every check of every repo that
    declares nothing is byte-identical to the records taken before it existed."""
    files = dict(_drill_files())
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    report = core.scan(_tree(tmp_path, files))

    for check in report["checks"]:
        assert "acceptance" not in check, check


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_8_the_blocker_path_explains_the_declared_lines_at_all(tmp_path):
    """R7-8. On SATURDAYS_site — the repo that motivated the whole feature — the
    declaration legend lived only on the warning-tier fix_hint, and that repo has two
    `.env` files, so it reports at blocker tier and always did. The operator therefore
    read `[heuristic, declared: …]` lines and a `Downgrades claimed` header with
    nothing anywhere telling them what either meant.
    """
    files = dict(_drill_files())
    files[".env"] = "API_KEY=x\n"                       # a real blocker beside the claim
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed by deployhub.yaml" in result.detail
    assert declarations.DECLARATION_FILE in result.fix_hint, (
        "the blocker fix_hint explains [proof] and [heuristic] and says nothing about "
        "the third label the reader is looking at")
    assert "accept" in result.fix_hint and "refus" in result.fix_hint


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_8_the_fix_hint_no_longer_claims_a_refusal_it_cannot_honour(tmp_path):
    """The false sentence: "refusing it is how you say the declaration is wrong", on a
    confirm whose answer was read by no code. It is true after this change, so it may
    be said — but it has to be said about the mechanism that now exists, and the
    warning tier is no longer where declared findings land at all."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    blocker = _secret_scan(_tree(tmp_path, files))
    assert "refusing it is how you say the declaration is wrong" not in blocker.fix_hint

    warning = _secret_scan(_tree(tmp_path, {
        "tests/test_login.py": f'password = "{FAKE_HIGH_ENTROPY}"\n',
        "src/app.py": "print('hello')\n",
    }, name="autoonly"))
    assert warning.tier == "warning", warning.detail
    assert "declared" not in warning.fix_hint, (
        "the warning tier still describes a declared bucket that can no longer reach "
        "it — declared findings block now")


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_11_the_confirm_question_has_no_default(tmp_path):
    """R7-11. "An unanswered claim is not an accepted one" is the property the whole
    acceptance gate rests on, it is written down in the D-012 record, and until now it
    was pinned by nothing — mutating `default=None` to `default=True` survived the
    entire suite, and would have pre-answered every confirm `True` in any client that
    submits the defaults it was handed."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    report = core.scan(_tree(tmp_path, files))

    confirms = [q for q in report["wizard_questions"]
                if q["id"].startswith("scanner.test_material.")]
    assert confirms, report["wizard_questions"]
    for question in confirms:
        assert question["kind"] == "bool"
        assert question["default"] is None, (
            "a declaration confirm arrived pre-answered")


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_13_the_declaration_file_is_read_exactly_once_per_scan(
        tmp_path, monkeypatch):
    """R7-13. `deployhub.yaml` was parsed twice — once by `common_checks` for the
    check, once by `scan` for the questions and the manifest — under a comment claiming
    "parsed once; two readers below". It is a file the SCANNED REPO controls, so two
    reads can disagree: a write landing between them makes the check downgrade findings
    the confirm never mentions, or raises a confirm for a tree nothing was downgraded
    in. One read, threaded through."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    root = _tree(tmp_path, files)

    calls = []
    real_load = declarations.load
    monkeypatch.setattr(declarations, "load",
                        lambda r: (calls.append(str(r)), real_load(r))[1])
    core.scan(root)
    assert len(calls) == 1, f"deployhub.yaml was parsed {len(calls)} times: {calls}"


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_14_the_confirm_questions_are_built_by_the_declarations_module(
        tmp_path, monkeypatch):
    """R7-14. D-010 made `scanner/core.py` the COMPOSER; the prompt copy, the slug
    scheme and the `_env_name` defense that motivates it are validation rules about a
    declaration, and they belong beside the ones that accepted it. `scan` calls and
    extends."""
    import inspect

    assert "scanner.test_material" not in inspect.getsource(core), (
        "the confirm id scheme is back in the composer")

    sentinel = core.WizardQuestion(id="scanner.test_material.9.sentinel",
                                   prompt="sentinel", kind="bool")
    monkeypatch.setattr(declarations, "confirm_questions", lambda declared: [sentinel])
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    report = core.scan(_tree(tmp_path, files))

    assert "scanner.test_material.9.sentinel" in [
        q["id"] for q in report["wizard_questions"]]


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_14_the_env_name_defense_travelled_with_the_slug_scheme(tmp_path):
    """The defense the id scheme exists for, asserted where the scheme now lives:
    `wizard.materialize._env_name` turns any question id containing `.env.` into an
    environment variable name, and a declared path is text the scanned repo writes."""
    root = _tree(tmp_path, {
        "docker/.env.d/leak.mjs": f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "deployhub.yaml": _declaration("docker/.env.d"),
    })
    questions = declarations.confirm_questions(declarations.load(root))
    assert len(questions) == 1, questions
    assert ".env." not in questions[0].id, questions[0].id
    assert questions[0].default is None


# ── round 7, second veto: the id is of a CLAIM, not of a slot ─────────────────


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1r_the_confirm_id_changes_when_only_the_reason_changes(tmp_path):
    """The id used to be `(index, slug(path))`, so the `reason` — the ENTIRE reviewable
    content of a declaration, and the one field `_read_entry` refuses an entry for
    lacking — was mutable underneath an acceptance that had already been given. A
    stored `True` then meant "somebody once approved this directory", which is not what
    the operator was asked and not what the record claims they said."""
    same_path = _tree(tmp_path, dict(_drill_files(), **{
        "deployhub.yaml": _declaration("frontend/scripts/drill")}), name="a")
    swapped = _tree(tmp_path, dict(_drill_files(), **{
        "deployhub.yaml": _declaration("frontend/scripts/drill",
                                       "ACTUALLY covers prod secrets now")}), name="b")

    first = declarations.confirm_questions(declarations.load(same_path))[0]
    second = declarations.confirm_questions(declarations.load(swapped))[0]
    assert first.id != second.id
    # Still legible, and still the path a human recognizes.
    assert first.id.startswith("scanner.test_material.frontend-scripts-drill--")
    assert second.id.startswith("scanner.test_material.frontend-scripts-drill--")

    # Re-reading the same declaration is stable — an id that moved on its own would
    # re-block every deploy for no reason and train the operator to re-accept blind.
    assert declarations.confirm_questions(declarations.load(same_path))[0].id == first.id


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1r_the_id_is_a_function_of_the_claim_not_of_its_position(tmp_path):
    """The other half of the round-trip attack, at the unit, and the design decision it
    forced. The index used to be part of the key, which made the id a SLOT — something
    an orphaned answer can be left lying in and re-apply from when a declaration comes
    back to it. Content-only keys have no old slot: moving a declaration does not change
    what is being asked, so it does not change the question, and the answer the operator
    already gave still answers it. What changes the question is changing the claim.
    """
    root = _tree(tmp_path, dict(_drill_files(), **{
        "frontend/scripts/aaa/readme.md": "nothing\n",
        "deployhub.yaml": (
            "scanner:\n"
            "  test_material:\n"
            "    - path: frontend/scripts/aaa\n      reason: prepended tree\n"
            f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n")}))
    moved = declarations.confirm_questions(declarations.load(root))[1]
    assert moved.id == _drill_confirm_id()
    assert "scanner.test_material.2." not in moved.id, (
        "the confirm id still encodes a position, which is a slot an orphan can sit in")


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1r_one_claim_written_twice_is_asked_about_once(tmp_path):
    """The cost of dropping the index, paid deliberately. Two entries with the same path
    AND the same reason collapse to one confirm — one claim written twice, and asking
    the operator the same question twice is how you teach them to answer without
    reading. Two entries over one path with DIFFERENT reasons stay two questions,
    because they are two claims."""
    twice = _tree(tmp_path, dict(_drill_files(), **{"deployhub.yaml": (
        "scanner:\n"
        "  test_material:\n"
        f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"
        f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n")}),
        name="twice")
    assert len(declarations.confirm_questions(declarations.load(twice))) == 1

    two_claims = _tree(tmp_path, dict(_drill_files(), **{"deployhub.yaml": (
        "scanner:\n"
        "  test_material:\n"
        f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"
        "    - path: frontend/scripts/drill\n      reason: a second, different claim\n")}),
        name="twoclaims")
    questions = declarations.confirm_questions(declarations.load(two_claims))
    assert len({q.id for q in questions}) == 2
    # Only the first is credited with findings, so only the first gates the blocker —
    # the second is asked and recorded, and holds nothing shut.
    result = _secret_scan(two_claims)
    assert result.acceptance["questions"] == [_drill_confirm_id()]


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_1r_a_directory_named_env_cannot_forge_an_environment_variable(
        tmp_path):
    """The `_env_name` defense, re-asserted against the shape that nearly broke it.

    Appending the digest as a new DOT segment would have reopened the exact hole the id
    scheme exists to close: a repo with a real directory called `env` slugs to `env`,
    and `scanner.test_material.1.env.<digest>` contains `.env.`, so
    `wizard.materialize._env_name` would have turned the digest into an environment
    variable name. The digest is joined to the slug with `--` instead, which the slug
    itself can never contain (runs of non-alphanumerics collapse to one `-`), so the id
    has exactly the dot structure it had before.
    """
    for path in ("env", "docker/.env.d", "config/env"):
        root = _tree(tmp_path, {
            f"{path}/leak.mjs": f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
            "deployhub.yaml": _declaration(path),
        }, name=f"envdir-{abs(hash(path))}")
        questions = declarations.confirm_questions(declarations.load(root))
        assert len(questions) == 1, (path, questions)
        assert ".env." not in questions[0].id, (path, questions[0].id)


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_1r_the_confirm_id_fits_the_column_it_is_stored_in(tmp_path):
    """`WizardAnswer.question_id` is `CharField(max_length=128)` and the slug comes from
    a path the scanned repo chooses, so its length is repo-controlled. The slug is
    bounded; truncating it is safe only BECAUSE the digest is over the full path and
    reason, so two paths that truncate alike still get different ids."""
    deep = "/".join(f"averyverylongdirectorysegment{i}" for i in range(12))
    a = declarations.confirm_question_id(deep + "/alpha", "r")
    b = declarations.confirm_question_id(deep + "/beta", "r")
    assert len(a) <= 128, (len(a), a)
    assert a != b, "two long paths truncated into the same confirm id"


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_1r_the_acceptance_contract_publishes_the_content_keyed_id(tmp_path):
    """The three derivations must still agree after the id gained a digest: what the
    wizard asks, what the check publishes, and what the manifest records."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    files["Dockerfile"] = "FROM python:3.12\nCMD [\"app\"]\n"
    report = core.scan(_tree(tmp_path, files))

    check = [c for c in report["checks"] if c["id"] == "core.secret-scan"][0]
    asked = [q["id"] for q in report["wizard_questions"]
             if q["id"].startswith("scanner.test_material.")]
    assert check["acceptance"]["questions"] == asked
    assert asked[0] == declarations.confirm_question_id(
        "frontend/scripts/drill", DRILL_REASON)


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_8r_the_legend_does_not_promise_a_deploy_it_cannot_deliver(tmp_path):
    """The copy nuance the verifier flagged, and SATURDAYS_site is exactly the case:
    it has two `.env` files, so `blocking_only_declared` is False and accepting the
    drill declaration will NOT let it deploy. The legend told that operator that
    accepting clears the block. The narrative in the demo record was already honest
    about this; the report the operator actually reads has to be too."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    declared_only = _secret_scan(_tree(tmp_path, files, name="declonly"))
    assert declared_only.acceptance["blocking_only_declared"] is True
    assert "still block" not in declared_only.fix_hint

    files[".env"] = "API_KEY=x\n"
    mixed = _secret_scan(_tree(tmp_path, files, name="mixed"))
    assert mixed.acceptance["blocking_only_declared"] is False
    assert "still block" in mixed.fix_hint, (
        "the legend promises that accepting clears a deploy that no answer can clear")
    assert "these findings block until you accept" in mixed.detail


# ── round 7-B: the rest of the queue (spec-r7-scanner-findings.md) ─────────────

@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_3_a_reason_cannot_forge_a_second_finding_inside_one_line(tmp_path):
    """The forgery class reopening a THIRD way. Rounds 1 and 2 closed the structure
    BETWEEN lines (a reason that writes lines of its own); this is the structure WITHIN
    one line. The label packs four fields into a string delimited by `[`, `]`, `"`, `—`
    and `:`, and the round-1/2 validator refuses only code points that break or reorder
    lines — a `"` and a `]` walk straight through it.

    The verifier's exact reason string, which renders as a line reading as though it
    carried a second finding."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/drill\n"
        '      reason: fake creds"] hardcoded prod_master_key value — "see docs\n')
    result = _secret_scan(_tree(tmp_path, files))

    assert result.tier == "blocker", result.detail
    # Nothing was downgraded: the claim was refused, so the drill findings block on
    # their own account and the label was never rendered.
    assert "Downgrades claimed" not in result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail
    assert "prod_master_key" not in result.detail, (
        "the forged label text reached the report")


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_3_a_directory_name_cannot_forge_a_second_finding_either(tmp_path):
    """The same hole through the other field of the same label. `path` is repo-controlled
    text too — a real directory may be named `drill" — "anything` on every filesystem this
    runs on — and it is rendered into the same label, ahead of the reason, with the same
    delimiters. Fixing one field and not the other is this codebase's recurring defect
    written small.

    The `]` half of the path attack was already closed, by accident rather than by
    intent: `]` is in `_GLOB_CHARS`, so a path carrying one is refused as a glob. The
    quote was not, and a label reading `declared: drill" — "stale — "drill scripts"`
    leaves a reader unable to say where the claimed path ends and the repo's words
    begin — which is the whole content of the evidence."""
    evil = 'drill" — "covers everything'
    files = {
        f"{evil}/qa.mjs": f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "deployhub.yaml": ("scanner:\n"
                           "  test_material:\n"
                           f'    - path: {evil!r}\n'
                           "      reason: drill scripts\n"),
    }
    result = _secret_scan(_tree(tmp_path, files, name="evilpath"))

    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed" not in result.detail
    assert "[heuristic, declared:" not in result.detail, (
        "a directory name was rendered into an evidence label it can forge")
    assert "[heuristic] hardcoded staff_password value" in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
@pytest.mark.parametrize("reason", [
    "red-team drill — deliberate fake credentials",      # em dash, the label's own
    "QA's drill scripts, don't panic",                   # apostrophes
    "drills (see docs/security.md) for the rota",        # parens close no enclosure
    "測試用的假憑證（紅隊演練）",                              # the fleet's own language
])
def test_issue_r7_3_a_legitimate_reason_is_not_collateral(tmp_path, reason):
    """The over-correction guard the spec names, and it is why the refusal is the
    ENCLOSURE CLOSERS rather than "every character the label uses": the em dash IS a
    label delimiter and a reason that contains one forges nothing, because the reason is
    rendered inside a quoted region an em dash cannot end."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill", reason)
    result = _secret_scan(_tree(tmp_path, files, name=f"ok{abs(hash(reason))}"))

    assert f'[heuristic, declared: frontend/scripts/drill — "{reason}"]' in result.detail
    assert result.detail.count("[heuristic, declared:") == 2, result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_3_the_labels_structural_characters_are_frozen(tmp_path):
    """The drift test, and it is the answer to "the next delimiter someone adds".

    Enumerating characters to refuse has now failed twice, so what is frozen here is the
    LABEL'S OWN PUNCTUATION. Add a delimiter to `Declaration.label()` and this test goes
    red, which puts the author in front of the one question that matters: can a `reason`
    or a `path` close the enclosure it is rendered inside? If it can, the character joins
    `LABEL_ENCLOSURE_CLOSERS`; if it cannot — as the em dash cannot — it does not.
    A frozen refusal set alone would have gone green on that change."""
    rendered = declarations.Declaration(path="PATH", reason="REASON").label()
    skeleton = rendered.replace("PATH", "").replace("REASON", "")
    punctuation = {ch for ch in skeleton if not ch.isalnum() and not ch.isspace()}
    assert punctuation == {":", "—", '"'}, (
        f"the evidence label's punctuation changed to {punctuation!r} — decide, for "
        f"every character that is new, whether a repo-controlled field can close the "
        f"enclosure it is rendered inside, and put it in LABEL_ENCLOSURE_CLOSERS if it "
        f"can")
    # The bracket pair belongs to the caller in `_check_secret_scan`, which is why the
    # closer set holds `]` although `label()` never prints one.
    assert set(declarations.LABEL_ENCLOSURE_CLOSERS) == {'"', "]"}


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_4_a_declared_split_settings_package_is_rejected(tmp_path):
    """The fleet's own layout. `SCANNER_KEY_FILES` names a literal `settings.py`, and
    not one repo in the fleet has one: they all carry a settings PACKAGE
    (`config/settings/base.py`, `prod.py`) that `django._settings_files` discovers by the
    PARENT DIRECTORY's name. So declaring `backend/config` was accepted, and a heuristic
    secret beside `base.py` was downgraded by a file the repo writes."""
    files = {
        "backend/config/settings/base.py": "DEBUG = False\n",
        "backend/config/settings/prod_extras.py":
            f'stripe_secret_key = "{FAKE_HIGH_ENTROPY}"\n',
        "deployhub.yaml": _declaration("backend/config"),
    }
    result = _secret_scan(_tree(tmp_path, files, name="splitsettings"))

    assert result.tier == "blocker", result.detail
    assert "Downgrades claimed" not in result.detail
    assert "[heuristic] hardcoded stripe_secret_key value" in result.detail
    assert "settings" in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_4_the_guard_reads_djangos_own_settings_rule(tmp_path):
    """DERIVED, not restated — the N6/N7 lesson, and R7-4 is precisely that drift: the
    guard held its own idea of what a settings file is, django held another, and the
    fleet's layout fell in the gap.

    Every shape below is asked of both sides at once: whatever `django` discovers as a
    settings file, the guard must refuse a declaration wrapped around it, and whatever
    django does not, the guard must not refuse on this account."""
    from scanner.modules import django as django_module

    shapes = {
        "svc/settings.py": True,
        "svc/config/settings/base.py": True,
        "svc/config/settings/prod.py": True,
        "svc/config/settings/__init__.py": False,      # a package marker, not settings
        "svc/settings/theme.json": False,              # not python
        "svc/settings.py.bak": False,
    }
    for rel, expected in shapes.items():
        root = tmp_path / f"shape{abs(hash(rel))}"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("X = 1\n", encoding="utf-8")
        discovered = [p for p in django_module.DjangoScannerModule()._settings_files(root)]
        assert bool(discovered) is expected, (rel, discovered)
        assert bool(declarations._settings_package_file_in(root / "svc")) is expected, (
            f"{rel}: the manifest guard and django._settings_files disagree, which is "
            f"the drift R7-4 is")


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_4_a_settings_directory_of_non_python_files_is_not_rejected(tmp_path):
    """The over-correction guard the spec names. The rule is "django would read a
    settings module here", not "a directory called settings exists here" — the second is
    round-6b's classify-by-name mistake in a new costume, and it would refuse a drill
    tree holding `settings/keymap.json`."""
    files = dict(_drill_files())
    files["frontend/scripts/drill/settings/keymap.json"] = '{"a": 1}\n'
    files["frontend/scripts/drill/settings/README.md"] = "not python\n"
    files["deployhub.yaml"] = _declaration("frontend/scripts/drill")
    result = _secret_scan(_tree(tmp_path, files, name="jsonsettings"))

    assert "Downgrades claimed" in result.detail, result.detail
    assert result.detail.count("[heuristic, declared:") == 2, result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_5_a_deeply_nested_declaration_file_cannot_crash_the_scan(tmp_path):
    """The module docstring promises `load` never raises for anything the scanned repo
    controls. It did: 100k `[` characters is 100 KB — comfortably under the 256 KB byte
    cap that is supposed to bound this input — and `yaml.safe_load` recurses per opening
    bracket, so a `RecursionError` came out of `load`, out of `scan`, and onto the
    operator's terminal as a traceback. A byte cap is not a depth cap."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = "scanner:\n  test_material: " + "[" * 100_000
    root = _tree(tmp_path, files, name="deep")

    loaded = declarations.load(root)          # must not raise
    assert loaded.accepted == ()
    assert loaded.problems, "a file that could not be parsed produced no problem line"
    result = _secret_scan(root)
    assert result.tier == "blocker", result.detail
    assert "deployhub.yaml" in result.detail
    assert "Downgrades claimed" not in result.detail


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_10_the_declaration_count_is_capped(tmp_path):
    """`MAX_REASON_CHARS` stops one entry burying the findings count under a wall of
    prose; ~3000 entries fit under the byte cap and rebuild the wall out of header lines
    — and out of wizard questions, which is the worse half: 3004 questions is a wizard
    nobody reads to the end.

    The cap is on ENTRIES READ, not on entries accepted, because 3000 REFUSED entries
    build the same wall out of problem lines."""
    entries = "".join(f"    - path: d{i}\n      reason: drill {i}\n" for i in range(120))
    files = {"src/app.py": "print('hello')\n",
             "deployhub.yaml": "scanner:\n  test_material:\n" + entries}
    for i in range(120):
        files[f"d{i}/qa.mjs"] = f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n'
    root = _tree(tmp_path, files, name="many")

    loaded = declarations.load(root)
    assert len(loaded.accepted) == declarations.MAX_DECLARATIONS
    assert any("120" in p and "50" in p for p in loaded.problems), loaded.problems
    result = _secret_scan(root)
    # The entries past the cap were never applied, so their findings still block —
    # a cap that DOWNGRADED the overflow would be a wall of text with a hole under it.
    assert result.tier == "blocker", result.detail
    assert "[heuristic] hardcoded staff_password value" in result.detail
    assert result.detail.count("Downgrades claimed") == declarations.MAX_DECLARATIONS


@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
def test_issue_r7_6_auto_detected_test_material_wins_over_a_declaration(tmp_path):
    """The precedence clause is written in the requirement text and in a code comment,
    and a mutation dropping it survived the whole suite — every fixture keeps the two
    path sets disjoint, so nothing ever exercised the overlap.

    It matters because it is a credit claim: relabelling an ALREADY non-blocking finding
    as declared lets a declaration take credit for a downgrade it did not make, and the
    header's `N findings` — the number the reader came for — is what carries the lie."""
    files = {
        "tests/drills/probe.py": f'admin_password = "{FAKE_HIGH_ENTROPY}"\n',
        "deployhub.yaml": _declaration("tests/drills"),
    }
    result = _secret_scan(_tree(tmp_path, files, name="overlap"))

    assert result.tier == "warning", result.detail
    assert "tests/drills/probe.py:1: [heuristic] hardcoded admin_password value" \
        in result.detail
    assert "[heuristic, declared:" not in result.detail
    assert ('Downgrades claimed by deployhub.yaml: tests/drills '
            f'("{DRILL_REASON}", 0 findings)') in result.detail
    assert result.acceptance is None, (
        "a declaration credited with nothing became a key to the gate")


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_7_one_bad_entry_does_not_take_its_siblings_down(tmp_path):
    """Entry-level isolation: whole-file structure is fatal to the whole file, a bad
    ENTRY costs only itself. A mutation making one bad entry drop every sibling survived
    the suite because NO test anywhere built a two-entry `deployhub.yaml` — and on a real
    repo that mutation turns a `warning` into a `blocker`, so the direction it fails in
    is "the deploy is refused for a typo in an unrelated entry"."""
    files = dict(_drill_files())
    files["deployhub.yaml"] = (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/gone\n"
        "      reason: a tree that was deleted three releases ago\n"
        "    - path: frontend/scripts/drill\n"
        f"      reason: {DRILL_REASON}\n")
    result = _secret_scan(_tree(tmp_path, files, name="siblings"))

    assert result.tier == "blocker", result.detail
    # the valid sibling still applies …
    assert result.detail.count("[heuristic, declared:") == 2, result.detail
    assert ('Downgrades claimed by deployhub.yaml: frontend/scripts/drill '
            f'("{DRILL_REASON}", 2 findings)') in result.detail
    # … and the stale one still warns, by name.
    assert "frontend/scripts/gone" in result.detail
    assert "rejected as stale" in result.detail
    assert result.acceptance == {
        "questions": [_drill_confirm_id()], "blocking_only_declared": True}


@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_issue_r7_12_the_warning_title_says_which_of_the_two_things_happened(tmp_path):
    """`_warning_title` has three branches and collapsing all three to one string left
    the suite green. The title is the one line a reader sees in a summary listing, and
    "declarations need attention" versus "test material only" are different jobs."""
    stale = {"src/app.py": "print('hello')\n",
             "deployhub.yaml": _declaration("frontend/scripts/drill")}
    assert _secret_scan(_tree(tmp_path, stale, name="t1")).title == (
        "deployhub.yaml declarations need attention")

    merged = dict(stale)
    merged["tests/test_login.py"] = f'password = "{FAKE_HIGH_ENTROPY}"\n'
    assert _secret_scan(_tree(tmp_path, merged, name="t2")).title == (
        "Secret-shaped values in test material only; "
        "deployhub.yaml declarations need attention")

    clean = {"tests/test_login.py": f'password = "{FAKE_HIGH_ENTROPY}"\n'}
    assert _secret_scan(_tree(tmp_path, clean, name="t3")).title == (
        "Secret-shaped values in test material only")


def test_issue_r7_15_the_declarations_record_carries_no_dead_field():
    """`_by_path` was declared, written by nothing and read by nothing. Freezing the
    field list is what keeps the next one from surviving three rounds of review."""
    assert set(declarations.Declarations.__dataclass_fields__) == {
        "accepted", "problems", "present"}

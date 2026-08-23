"""`scanner/declarations.py` — the PARKED `deployhub.yaml` parser, kept from rotting.

WHAT THIS FILE IS NOW. D-012 left Phase 1 on 2026-08-16 (Joseph's round-6 cap decision,
`claude/decision-2026-08-16-round-6-cap.md`, Option A): no downgrades, no confirms, no
acceptance contracts, and no live path that reads `deployhub.yaml` at all. The module
stays on master because the mechanism RETURNS as its own phase and the six adversarial
rounds behind this parser are that phase's threat-model floor — so its PURE FUNCTIONS
keep being exercised here, and every test that pinned the WIRING (a downgraded finding,
a labelled third bucket, a header, an `acceptance` contract, a confirm in a scan report)
left with the wiring it described. The scan-level properties Phase 1 does hold are in
tests/test_d012_out_of_phase_1.py.

SCAN-M4 (Phase 4 Task 0 / D-055): these parser tests keep running but no longer carry
full-text SCAN-DECLARED-TEST-MATERIAL / SCAN-DECLARED-GUARDS markers. Parser-only
proofs do not prove the live path. Full-text markers land in Task 3 E2E.

So every test below asks `scanner.declarations` a question directly:

    declarations.load(root)              what the file parsed to, and what it refused
    declarations.confirm_questions(…)    the confirm ids and prompts it would raise
    declarations.confirm_question_id(…)  the content-keyed derivation behind them
    Declaration.covers/label             the two pure renderings the report used

That is a deliberate narrowing, not a loss: what these rounds actually established is
what this PARSER refuses, and the refusals are what a future phase must not lose. What
a refused claim then did to a check is a property of the check, and there is no such
check this phase.

Motivating measurement, kept because the future phase inherits the problem: 20 of
SATURDAYS_site's 26 blocking heuristic lines are `frontend/scripts/drill/**` — red-team
and QA scripts holding deliberate `admin_password` literals. Test material by intent and
by content, but not by path, so `core.secret-scan` has no honest way to know.
"""
import pathlib

import pytest

from scanner import declarations
from scanner.modules import fallbacks

REPO = pathlib.Path(__file__).resolve().parent.parent

# A 40-char random value with no marker word — the shape the heuristic axis is for.
FAKE_HIGH_ENTROPY = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P"

DRILL_REASON = "red-team / QA drill scripts; deliberate fake credentials"


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
    """The SATURDAYS_site shape: a drill tree of deliberate credentials.

    The credentials are still here although nothing reads them for a tier any more:
    `_read_entry` refuses a declaration over a directory that does not exist, so the
    tree the claim names has to be real for the accept path to be exercised at all.
    """
    return {
        "frontend/scripts/drill/qa/03_regressions.mjs":
            f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "frontend/scripts/drill/redteam/01_rbac_money.mjs":
            f'const admin_password = "{FAKE_HIGH_ENTROPY}";\n',
        "src/app.py": "print('hello')\n",
    }


def _load(tmp_path, files, name="proj"):
    return declarations.load(_tree(tmp_path, files, name=name))


def _declared(tmp_path, body, name="proj", files=None):
    """Parse a `deployhub.yaml` body over the drill tree."""
    tree = dict(files if files is not None else _drill_files())
    tree["deployhub.yaml"] = body
    return _load(tmp_path, tree, name=name)


def _problems(loaded):
    return "\n".join(loaded.problems)


# ── what a declaration parses to ───────────────────────────────────────────────

def test_a_well_formed_declaration_is_accepted_with_its_words_intact(tmp_path):
    """The measured case, at the parser. The entry is accepted, normalized, and carries
    the repo's own words verbatim — `reason` is copied, never repaired, because the
    whole point of the field is that a reviewer reads exactly what was written."""
    loaded = _declared(tmp_path, _declaration("frontend/scripts/drill"))

    assert len(loaded.accepted) == 1, loaded
    entry = loaded.accepted[0]
    assert entry.path == "frontend/scripts/drill"
    assert entry.reason == DRILL_REASON
    assert loaded.problems == ()
    assert loaded.present is True
    assert entry.label() == f'declared: frontend/scripts/drill — "{DRILL_REASON}"'


def test_a_declaration_covers_only_its_own_subtree(tmp_path):
    """Prefix matching is on PATH SEGMENTS, not on strings: `drill` must not cover
    `drillbits`, and a declaration deep in the tree must not reach its siblings.

    Asserted through `covers`/`covering` rather than through a scan, which is where the
    rule lives — the check that consulted it is gone, and this is the function a future
    phase's check would consult again."""
    loaded = _declared(tmp_path, _declaration("frontend/scripts/drill"), files={
        "frontend/scripts/drill/qa.mjs": f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "frontend/scripts/drillbits/real.mjs":
            f'const api_key = "{FAKE_HIGH_ENTROPY}";\n',
    })
    entry = loaded.accepted[0]

    assert entry.covers("frontend/scripts/drill/qa.mjs")
    assert entry.covers("frontend/scripts/drill/deeper/nested/qa.mjs")
    assert not entry.covers("frontend/scripts/drillbits/real.mjs")
    assert not entry.covers("frontend/scripts/other.mjs")
    assert loaded.covering("frontend/scripts/drill/qa.mjs") is entry
    assert loaded.covering("frontend/scripts/drillbits/real.mjs") is None


def test_a_repo_with_no_declaration_file_parses_to_nothing(tmp_path):
    """`present` is False and nothing is accepted — the state every repo in the fleet
    but one is in, and the reason the whole feature could be added (and now unwired)
    without moving a recorded demo artifact."""
    loaded = _load(tmp_path, _drill_files())

    assert loaded.accepted == ()
    assert loaded.problems == ()
    assert loaded.present is False
    assert loaded is declarations.NONE


# ── the guards ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [".", "./", "", "/", "  ", "./."])
def test_declaring_the_scan_root_is_rejected(tmp_path, path):
    """A declaration that swallows the whole repo is indistinguishable from hiding."""
    loaded = _declared(tmp_path, _declaration(f'"{path}"'),
                       name=f"root{abs(hash(path))}")

    assert loaded.accepted == ()
    assert "scan root" in _problems(loaded), loaded.problems


@pytest.mark.parametrize("path", ["../outside", "frontend/../../etc",
                                  "/etc/secrets", "frontend/scripts/*",
                                  "frontend/scripts/dr?ll"])
def test_an_escaping_or_globbed_path_is_rejected(tmp_path, path):
    """`..`, absolute paths and globs are all ways to declare something other than the
    directory the reviewer read in the diff."""
    loaded = _declared(tmp_path, _declaration(f'"{path}"'),
                       name=f"esc{abs(hash(path))}")

    assert loaded.accepted == ()
    assert loaded.problems, "an escaping path was refused silently"


def test_a_declared_path_missing_from_the_tree_is_rejected_as_stale(tmp_path):
    """A declaration that outlives its directory is exactly the rot a report has to
    surface: it is a live claim that nobody re-read, and the next directory to be given
    that name inherits it."""
    loaded = _declared(tmp_path, _declaration("frontend/scripts/drill"),
                       files={"src/app.py": "print('hello')\n"})

    assert loaded.accepted == ()
    assert "frontend/scripts/drill" in _problems(loaded)
    assert "does not exist" in _problems(loaded)


@pytest.mark.parametrize("manifest", sorted(declarations.SCANNER_KEY_FILES))
def test_a_path_holding_a_manifest_the_scanner_keys_on_is_rejected(tmp_path, manifest):
    """The subtler half of the root guard. `backend/` holding `manage.py` is not a
    drill tree, whatever the declaration says, and a declaration around a project's own
    manifest is a repo hiding its production code from the check that reads it.

    Parametrized off the constant, so a name cannot be added without a test (the N6
    lesson: seven of eleven names in one list were asserted by nothing)."""
    files = dict(_drill_files())
    files[f"frontend/scripts/drill/{manifest}"] = "{}\n"
    loaded = _declared(tmp_path, _declaration("frontend/scripts/drill"),
                       name=f"m{abs(hash(manifest))}", files=files)

    assert loaded.accepted == ()
    assert manifest in _problems(loaded)


def test_the_scanner_key_file_set_is_frozen_and_covers_the_module_manifests():
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


def test_the_parked_parser_and_the_live_notice_name_the_same_file():
    """D-012 out of Phase 1 left one string in two places on purpose: this module is
    parked, so `fallbacks._check_declaration_file` may not import it for the file's
    name, and a second literal is the price. Two copies of a constant drift — this
    codebase's recurring finding — so the copy is pinned here rather than trusted."""
    assert fallbacks.DECLARATION_FILE == declarations.DECLARATION_FILE


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
def test_a_malformed_deployhub_yaml_produces_problems_and_applies_nothing(tmp_path, body):
    """A config file the scanner cannot read must never take the scan down with it —
    and must never be read optimistically either. `load` returns problems, never
    raises, and accepts nothing."""
    loaded = _declared(tmp_path, body, name=f"bad{abs(hash(body))}")

    assert loaded.accepted == ()
    assert loaded.problems, "a malformed file produced no problem line"
    assert loaded.present is True


# ── adversarial round 1: the report is part of the attack surface ──────────────
#
# Everything below came out of the independent adversarial pass on the first cut, and
# every one of them was demonstrated by a real scan rather than argued. The theme of
# finding 1 is the one worth carrying forward — it is why these tests outlive the
# mechanism: `reason` and `path` are repo-controlled text that a report renders as
# EVIDENCE a reviewer reads to decide whether a deploy is safe, and until this round the
# scanned repo could write arbitrary lines into it. Any phase that re-introduces the
# mechanism re-introduces that surface.


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
    loaded = _declared(tmp_path, "scanner:\n"
                                 "  test_material:\n"
                                 "    - path: frontend/scripts/drill\n"
                                 f'      reason: "{forged}"\n')

    assert loaded.accepted == ()
    problems = _problems(loaded)
    # The refusal names the entry by index and field and gives the offset, and quotes
    # NONE of the value: an escaped copy of a forged section header is still that
    # header, sitting where a reader greps for one.
    assert "entry 1" in problems
    assert "control character" in problems
    assert "`reason`" in problems
    assert "drill scripts" not in problems
    assert "Also in test material (not blocking):" not in problems
    for line in problems.splitlines():
        assert not line.startswith("src/app.py:1"), line


@pytest.mark.parametrize("payload", [
    '"line one\\nline two"',
    '"tabbed\\there"',
    '"carriage\\rreturn"',
    '"bell\\a"',
    '"delete\\x7f"',
])
def test_any_control_character_in_a_reason_is_a_malformed_entry(tmp_path, payload):
    """Not just newline. A tab fakes indentation, a CR overwrites the line a terminal
    already drew, and `\\x7f` renders as nothing at all — every one of them edits what
    the reviewer sees rather than what the file says."""
    loaded = _declared(tmp_path, "scanner:\n"
                                 "  test_material:\n"
                                 "    - path: frontend/scripts/drill\n"
                                 f"      reason: {payload}\n",
                       name=f"c{abs(hash(payload))}")

    assert loaded.accepted == ()
    assert "control character" in _problems(loaded)


def test_a_control_character_in_a_path_is_a_malformed_entry(tmp_path):
    """The path is embedded in the same places the reason is."""
    loaded = _declared(tmp_path, "scanner:\n"
                                 "  test_material:\n"
                                 '    - path: "frontend/scripts/drill\\nfaked"\n'
                                 f"      reason: {DRILL_REASON}\n")

    assert loaded.accepted == ()
    assert "control character" in _problems(loaded)


def test_a_reason_longer_than_the_cap_is_a_malformed_entry(tmp_path):
    """A wall of text is the other way to edit the report: the findings count sits at
    the end of the header line, and 40 KB of prose in front of it buries the number the
    reader came for. The boundary is asserted in both directions so the cap cannot
    drift by an off-by-one."""
    at_cap = "x" * declarations.MAX_REASON_CHARS
    over_cap = "x" * (declarations.MAX_REASON_CHARS + 1)

    accepted = _declared(tmp_path, _declaration("frontend/scripts/drill", at_cap),
                         name="at_cap")
    assert len(accepted.accepted) == 1, accepted.problems

    refused = _declared(tmp_path, _declaration("frontend/scripts/drill", over_cap),
                        name="over_cap")
    assert refused.accepted == ()
    assert str(declarations.MAX_REASON_CHARS) in _problems(refused)
    assert over_cap not in _problems(refused), (
        "the refusal pasted the wall of text back in")


def test_a_manifest_the_scanner_walks_is_never_hidden_from_the_guard(tmp_path):
    """The N6 class, one layer in: the guard pruned `vendor`, `.hg` and `.svn` while the
    secret scanner's own walk does not, so `svc/vendor/package.json` was invisible to
    the rejection guard and `svc/**` was declared anyway. A guard that skips a directory
    the check still reads is a guard with a hole in it."""
    loaded = _declared(tmp_path, _declaration("svc"), files={
        "svc/vendor/package.json": '{"name": "svc"}\n',
        "svc/drill.mjs": f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
    })

    assert loaded.accepted == ()
    assert "package.json" in _problems(loaded)


def test_the_guard_prunes_nothing_the_secret_scanner_walks():
    """The parity assertion behind the test above, stated as a property so the two
    lists cannot drift apart again: the guard may skip a directory only where the
    scanner skips it too."""
    assert declarations.guard_prune_dirs() <= fallbacks._SKIP_DIRS


def test_an_oversized_declaration_file_is_refused_unparsed(tmp_path):
    """`load` used to read the file unbounded, so a repo could hand the scanner a
    gigabyte of YAML. A config file larger than a quarter of a megabyte is not a config
    file; it is refused before the parser sees it, and accepts nothing."""
    body = _declaration("frontend/scripts/drill") + ("# " + "y" * 200 + "\n") * 2000
    assert len(body.encode("utf-8")) > declarations.MAX_DECLARATION_BYTES
    loaded = _declared(tmp_path, body)

    assert loaded.accepted == ()
    assert "too large" in _problems(loaded)


# ── adversarial round 2: the line break is whatever the RENDERER thinks it is ───
#
# Round 1 refused C0 and DEL and called the forgery closed. It was not: `str.splitlines`
# — which is what builds a report's lines, and what any Python reader of it will use —
# also breaks on U+2028, U+2029 and U+0085, and a browser rendering the JSON breaks on
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
# The fleet's own language, spelled in escapes for the same reason as the rest.
CHINESE_REASON = "\u7d05\u968a\u6f14\u7df4\u7528\u5047\u5bc6\u78bc"


def test_a_unicode_line_separator_in_a_reason_is_refused(tmp_path):
    """The verifier's round-2 case. `[\\x00-\\x1f\\x7f]` does not contain U+2028, and
    every line of a report is produced by `splitlines`, which does."""
    forged = (f"drill scripts{LSEP}{LSEP}Also in test material (not blocking):{LSEP}"
              f"src/app.py:1: [heuristic] hardcoded api_key value")
    loaded = _declared(tmp_path, "scanner:\n"
                                 "  test_material:\n"
                                 "    - path: frontend/scripts/drill\n"
                                 f'      reason: "{forged}"\n')

    assert loaded.accepted == ()
    for line in _problems(loaded).splitlines():
        assert line.strip() != "Also in test material (not blocking):", loaded.problems
        assert not line.startswith("src/app.py:1"), loaded.problems


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
    files["deployhub.yaml"] = ("scanner:\n"
                               "  test_material:\n"
                               f'    - path: "{forged_dir}"\n'
                               f"      reason: {DRILL_REASON}\n")
    root = _tree(tmp_path, files)
    assert (root / forged_dir).is_dir(), "the fixture must put the real directory there"

    loaded = declarations.load(root)
    assert loaded.accepted == ()
    for line in _problems(loaded).splitlines():
        assert line.strip() != "Also in test material (not blocking)", loaded.problems


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
        if field == "reason":
            body = ("scanner:\n  test_material:\n"
                    "    - path: frontend/scripts/drill\n"
                    f'      reason: "drill{char}scripts"\n')
        else:
            body = ("scanner:\n  test_material:\n"
                    f'    - path: "frontend/scripts/dr{char}ill"\n'
                    f"      reason: {DRILL_REASON}\n")
        loaded = _declared(tmp_path, body, name=f"u{abs(hash(char + field))}")
        assert loaded.accepted == (), f"{name} in {field} was accepted"
        assert loaded.problems, f"{name} in {field} was refused silently"


def test_an_ordinary_non_ascii_reason_is_accepted(tmp_path):
    """The over-correction guard, and the one that matters most for this fleet: every
    repo it scans is Taiwanese, and the reasons will be written in Chinese. A validator
    that refused 紅隊演練用假密碼 would make the feature unusable by the people it was
    built for — refusing code points that lie about STRUCTURE is not refusing a script.
    """
    loaded = _declared(tmp_path,
                       _declaration("frontend/scripts/drill", CHINESE_REASON))

    assert len(loaded.accepted) == 1, loaded.problems
    assert loaded.accepted[0].reason == CHINESE_REASON
    assert (loaded.accepted[0].label()
            == f'declared: frontend/scripts/drill — "{CHINESE_REASON}"')


# ── round 7: the confirm the mechanism would raise ─────────────────────────────
#
# The confirm no longer reaches a wizard — nothing calls `confirm_questions` in a live
# path — but its DERIVATION is the part two rounds of veto were spent on, and it is the
# part a future phase must not re-invent. The id is keyed on the declaration's CONTENT
# so that editing the claim invalidates the acceptance, and it carries a slug rather
# than the raw path so a repo-controlled directory name cannot turn a confirm into an
# environment variable.


def test_issue_r7_11_the_confirm_question_has_no_default(tmp_path):
    """R7-11. "An unanswered claim is not an accepted one" is the property the whole
    acceptance gate rested on, and until round 7 it was pinned by nothing — mutating
    `default=None` to `default=True` survived the entire suite, and would have
    pre-answered every confirm `True` in any client that submits the defaults it was
    handed."""
    loaded = _declared(tmp_path, _declaration("frontend/scripts/drill"))
    questions = declarations.confirm_questions(loaded)

    assert len(questions) == 1, questions
    assert questions[0].kind == "bool"
    assert questions[0].default is None, "a declaration confirm arrived pre-answered"
    assert "frontend/scripts/drill" in questions[0].prompt
    assert DRILL_REASON in questions[0].prompt


def test_issue_r7_14_the_env_name_defense_travelled_with_the_slug_scheme(tmp_path):
    """The defense the id scheme exists for, asserted where the scheme lives:
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


def test_issue_r7_1r_one_claim_written_twice_is_asked_about_once(tmp_path):
    """The cost of dropping the index, paid deliberately. Two entries with the same path
    AND the same reason collapse to one confirm — one claim written twice, and asking
    the operator the same question twice is how you teach them to answer without
    reading. Two entries over one path with DIFFERENT reasons stay two questions,
    because they are two claims."""
    twice = _declared(tmp_path, (
        "scanner:\n"
        "  test_material:\n"
        f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"
        f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"),
        name="twice")
    assert len(declarations.confirm_questions(twice)) == 1

    two_claims = _declared(tmp_path, (
        "scanner:\n"
        "  test_material:\n"
        f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"
        "    - path: frontend/scripts/drill\n      reason: a second, different claim\n"),
        name="twoclaims")
    questions = declarations.confirm_questions(two_claims)
    assert len({q.id for q in questions}) == 2
    # Only the first is ever credited with a finding — `covering` takes the first match
    # — so the second is a claim that is asked about and gates nothing.
    assert two_claims.covering("frontend/scripts/drill/qa/03_regressions.mjs") is (
        two_claims.accepted[0])


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


def test_issue_r7_1r_the_confirm_id_fits_the_column_it_is_stored_in():
    """`WizardAnswer.question_id` is `CharField(max_length=128)` and the slug comes from
    a path the scanned repo chooses, so its length is repo-controlled. The slug is
    bounded; truncating it is safe only BECAUSE the digest is over the full path and
    reason, so two paths that truncate alike still get different ids."""
    deep = "/".join(f"averyverylongdirectorysegment{i}" for i in range(12))
    a = declarations.confirm_question_id(deep + "/alpha", "r")
    b = declarations.confirm_question_id(deep + "/beta", "r")
    assert len(a) <= 128, (len(a), a)
    assert a != b, "two long paths truncated into the same confirm id"


# ── round 7-B: the rest of the queue (spec-r7-scanner-findings.md) ─────────────

def test_issue_r7_3_a_reason_cannot_forge_a_second_finding_inside_one_line(tmp_path):
    """The forgery class reopening a THIRD way. Rounds 1 and 2 closed the structure
    BETWEEN lines (a reason that writes lines of its own); this is the structure WITHIN
    one line. The label packs four fields into a string delimited by `[`, `]`, `"`, `—`
    and `:`, and the round-1/2 validator refuses only code points that break or reorder
    lines — a `"` and a `]` walk straight through it.

    The verifier's exact reason string, which renders as a line reading as though it
    carried a second finding."""
    loaded = _declared(tmp_path, (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/drill\n"
        '      reason: fake creds"] hardcoded prod_master_key value — "see docs\n'))

    assert loaded.accepted == ()
    assert "prod_master_key" not in _problems(loaded), (
        "the forged label text reached the refusal as text")


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
    loaded = _load(tmp_path, {
        f"{evil}/qa.mjs": f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n',
        "deployhub.yaml": ("scanner:\n"
                           "  test_material:\n"
                           f'    - path: {evil!r}\n'
                           "      reason: drill scripts\n"),
    }, name="evilpath")

    assert loaded.accepted == ()
    assert loaded.problems, "a forging directory name was refused silently"


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
    loaded = _declared(tmp_path, _declaration("frontend/scripts/drill", reason),
                       name=f"ok{abs(hash(reason))}")

    assert len(loaded.accepted) == 1, loaded.problems
    assert (loaded.accepted[0].label()
            == f'declared: frontend/scripts/drill — "{reason}"')


def test_issue_r7_3_the_labels_structural_characters_are_frozen():
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
    # The bracket pair belonged to the caller in `_check_secret_scan`, which is why the
    # closer set holds `]` although `label()` never prints one. That caller is gone with
    # D-012's wiring; the closer stays, because the future phase's label will be
    # rendered inside something and `]` is what closed the last one.
    assert set(declarations.LABEL_ENCLOSURE_CLOSERS) == {'"', "]"}


def test_issue_r7_4_a_declared_split_settings_package_is_rejected(tmp_path):
    """The fleet's own layout. `SCANNER_KEY_FILES` names a literal `settings.py`, and
    not one repo in the fleet has one: they all carry a settings PACKAGE
    (`config/settings/base.py`, `prod.py`) that `django._settings_files` discovers by the
    PARENT DIRECTORY's name. So declaring `backend/config` was accepted, and a heuristic
    secret beside `base.py` was downgraded by a file the repo writes."""
    loaded = _load(tmp_path, {
        "backend/config/settings/base.py": "DEBUG = False\n",
        "backend/config/settings/prod_extras.py":
            f'stripe_secret_key = "{FAKE_HIGH_ENTROPY}"\n',
        "deployhub.yaml": _declaration("backend/config"),
    }, name="splitsettings")

    assert loaded.accepted == ()
    assert "settings" in _problems(loaded)


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


def test_issue_r7_4_a_settings_directory_of_non_python_files_is_not_rejected(tmp_path):
    """The over-correction guard the spec names. The rule is "django would read a
    settings module here", not "a directory called settings exists here" — the second is
    round-6b's classify-by-name mistake in a new costume, and it would refuse a drill
    tree holding `settings/keymap.json`."""
    files = dict(_drill_files())
    files["frontend/scripts/drill/settings/keymap.json"] = '{"a": 1}\n'
    files["frontend/scripts/drill/settings/README.md"] = "not python\n"
    loaded = _declared(tmp_path, _declaration("frontend/scripts/drill"),
                       name="jsonsettings", files=files)

    assert len(loaded.accepted) == 1, loaded.problems


def test_issue_r7_5_a_deeply_nested_declaration_file_cannot_crash_the_load(tmp_path):
    """The module docstring promises `load` never raises for anything the scanned repo
    controls. It did: 100k `[` characters is 100 KB — comfortably under the 256 KB byte
    cap that is supposed to bound this input — and `yaml.safe_load` recurses per opening
    bracket, so a `RecursionError` came out of `load`, out of `scan`, and onto the
    operator's terminal as a traceback. A byte cap is not a depth cap."""
    loaded = _declared(tmp_path, "scanner:\n  test_material: " + "[" * 100_000,
                       name="deep")   # must not raise

    assert loaded.accepted == ()
    assert loaded.problems, "a file that could not be parsed produced no problem line"


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

    loaded = _load(tmp_path, files, name="many")
    assert len(loaded.accepted) == declarations.MAX_DECLARATIONS
    assert any("120" in p and "50" in p for p in loaded.problems), loaded.problems
    # The entries past the cap were never read, so nothing under them is covered by any
    # accepted declaration — a cap that read them anyway would be a wall of text with a
    # hole under it.
    assert loaded.covering(f"d{declarations.MAX_DECLARATIONS + 1}/qa.mjs") is None


def test_issue_r7_7_one_bad_entry_does_not_take_its_siblings_down(tmp_path):
    """Entry-level isolation: whole-file structure is fatal to the whole file, a bad
    ENTRY costs only itself. A mutation making one bad entry drop every sibling survived
    the suite because NO test anywhere built a two-entry `deployhub.yaml` — and on a real
    repo that mutation refused a deploy for a typo in an unrelated entry."""
    loaded = _declared(tmp_path, (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/gone\n"
        "      reason: a tree that was deleted three releases ago\n"
        "    - path: frontend/scripts/drill\n"
        f"      reason: {DRILL_REASON}\n"), name="siblings")

    # the valid sibling still applies …
    assert [d.path for d in loaded.accepted] == ["frontend/scripts/drill"]
    # … and the stale one is still refused, by name.
    assert "frontend/scripts/gone" in _problems(loaded)
    assert "rejected as stale" in _problems(loaded)


def test_issue_r7_15_the_declarations_record_carries_no_dead_field():
    """`_by_path` was declared, written by nothing and read by nothing. Freezing the
    field list is what keeps the next one from surviving three rounds of review."""
    assert set(declarations.Declarations.__dataclass_fields__) == {
        "accepted", "problems", "present"}


def test_issue_r7f_the_confirm_digest_is_sixteen_hex_characters():
    """The length is the security argument, and it was asserted by nothing: shortening
    `_CONFIRM_DIGEST_CHARS` to 4 survived the whole suite, because every other test
    derives the expected id from the same function it is testing.

    Sixteen hex is 64 bits, and the docstring on `confirm_question_id` says why that
    number: the attacker controls both inputs and aims at ONE stored id, so forging a
    claim that keeps somebody's acceptance is a second preimage — 2^n, not the birthday
    2^(n/2). At 16 bits it is ~65k grinds against a plausible-sounding reason; at 64 it
    is out of reach. Pinned with a LITERAL on purpose: a bound derived from the constant
    under test cannot fail when the constant moves."""
    import re

    qid = declarations.confirm_question_id("frontend/scripts/drill", DRILL_REASON)
    assert re.fullmatch(r"scanner\.test_material\..+--[0-9a-f]{16}", qid), qid
    assert len(qid) <= 128, len(qid)


@pytest.mark.parametrize("reason,closer", [
    ("fake creds] hardcoded admin_password value", "]"),
    ('fake creds" — "covers prod too', '"'),
])
def test_issue_r7f_each_enclosure_closer_is_refused_on_its_own(tmp_path, reason, closer):
    """One character at a time. The verifier's forge string carries BOTH `"` and `]`, so
    it would still be refused if only one of them were, and the `]` case on the PATH
    side is caught by the glob rule — which this module's own comment calls an accident,
    and an accident is not a defence you can cite. So each closer is pinned on its own."""
    loaded = _declared(tmp_path, ("scanner:\n"
                                  "  test_material:\n"
                                  "    - path: frontend/scripts/drill\n"
                                  f"      reason: {reason!r}\n"),
                       name=f"c{abs(hash(reason))}")

    assert loaded.accepted == ()
    assert closer in _problems(loaded) or "U+" in _problems(loaded), loaded.problems


# ── round 8: two assertions that asserted nothing ──────────────────────────────


@pytest.mark.parametrize("escape,name", [
    ("\\x9b", "U+009B CONTROL SEQUENCE INTRODUCER"),
    ("\\x9c", "U+009C STRING TERMINATOR"),
    ("\\x9d", "U+009D OPERATING SYSTEM COMMAND"),
])
def test_issue_r8_5_a_c1_control_reaches_a_value_as_a_yaml_escape_and_is_refused(
        tmp_path, escape, name):
    """R8-5: the `\\x80-\\x9f` arm of `_CONTROL_CHARS_RE` was asserted by nothing —
    deleting it left the whole suite green.

    The arm had two would-be carriers and neither carried it.
    `test_deceptive_code_points_are_refused_in_both_fields` passes a LITERAL U+0091,
    which PyYAML's reader refuses outright (`ReaderError`: "unacceptable character
    #x0091"), so `load` returns "is not valid YAML" and the parametrized case is green
    on a refusal this module never made — the value never reaches `_read_entry` at all.
    NEL (U+0085) does reach it, but it is a line break to `str.splitlines`, so the belt
    beneath the character class catches it and the arm is still unasserted.

    The real carrier is a YAML ESCAPE. `\\x9b` inside a double-quoted scalar is a
    PyYAML-admitted escape — `yaml.safe_load('reason: "a\\\\x9bb"')` yields
    `{'reason': 'a\\x9bb'}` — and U+009B..U+009D are not line breaks to `splitlines`,
    so the C1 arm is the only thing standing between a CSI byte and a report a reviewer
    reads as evidence. Refusing them is not pedantry: CSI is the introducer of an ANSI
    escape sequence, and a terminal printing the scanner's output will act on it.

    Asserted at the parser, on both fields, because post-extraction there is no tier and
    no report to assert against: the entry is refused with the control-character
    problem, and nothing is accepted.
    """
    for field in ("reason", "path"):
        if field == "reason":
            body = ("scanner:\n"
                    "  test_material:\n"
                    "    - path: frontend/scripts/drill\n"
                    f'      reason: "drill{escape}scripts"\n')
        else:
            body = ("scanner:\n"
                    "  test_material:\n"
                    f'    - path: "frontend/scripts/dr{escape}ill"\n'
                    f"      reason: {DRILL_REASON}\n")
        loaded = _declared(tmp_path, body, name=f"c1{abs(hash(escape + field))}")

        problems = _problems(loaded)
        assert loaded.accepted == (), f"{name} in {field} was accepted"
        # The specific refusal, not merely "something went wrong": a `ReaderError` from
        # PyYAML also empties `accepted`, and that is exactly how this arm stayed
        # unasserted for six rounds.
        assert "control character" in problems, f"{name} in {field}: {problems!r}"
        assert f"`{field}`" in problems, problems
        assert "not valid YAML" not in problems, (
            "the escape did not reach the validator — PyYAML refused the document "
            "instead, which is the false green R8-5 is about")
        # The value is named by code point and offset and never quoted back, per the
        # refusal's own rule.
        assert f"U+{ord(chr(int(escape[2:], 16))):04X}" in problems, problems


def test_issue_r8_12_a_refusal_quotes_back_a_bounded_amount_of_a_giant_value(tmp_path):
    """R8-12: `_QUOTE_LIMIT` was asserted by nothing — raising it to 10**9 survived the
    whole suite, because every test that trips a `_quote`-carrying refusal uses a short
    value.

    The carrier is the one refusal a huge value can reach cheaply. A `path` is refused
    for a glob character BEFORE any `stat`, so a ~200 KB path — comfortably inside
    `MAX_DECLARATION_BYTES` — costs the attacker one line of YAML and buys a 200 000
    character problem line. That is `MAX_REASON_CHARS`' wall of text rebuilt out of the
    refusal instead of out of the acceptance, and the same reader loses the same
    findings count off the end of the same header.

    Mirrors `test_a_reason_longer_than_the_cap_is_a_malformed_entry`: the refusal
    happens, it does not paste the wall of text back in, and the bound is asserted with
    a LITERAL rather than with `_QUOTE_LIMIT` — a bound derived from the constant under
    test cannot fail when the constant moves.
    """
    giant = "d" * 200_000 + "*"
    loaded = _declared(tmp_path, ("scanner:\n"
                                  "  test_material:\n"
                                  f'    - path: "{giant}"\n'
                                  f"      reason: {DRILL_REASON}\n"), name="giant")

    assert loaded.accepted == ()
    problems = _problems(loaded)
    assert "looks like a glob" in problems, problems
    assert "(truncated)" in problems, problems
    assert giant not in problems, "the refusal pasted the 200 KB path back in"
    # One problem line, and it stays a line: entry coordinates, the truncated quote and
    # the sentence, not the repo's own 200 KB.
    assert len(problems) < 1000, (
        f"the refusal for a 200 KB path was {len(problems)} characters long")


# ── the mutation gate's pins (spec-mutation-gate.md) ──────────────────────────
#
# `make mutation` found each of these: a mutation of `scanner/declarations.py` the suite
# could not tell from the real code. R8-5 and R8-12 above are two of the same class,
# found by hand in round 8; the gate found the rest of the family in one run.
#
# The theme is the one the parked module's own docstring warns about — this is a parser
# whose OUTPUT is evidence a reviewer reads, so "was it refused" is only half of any
# assertion here, and half is what almost all of these lines had.


@pytest.mark.parametrize("body,why", [
    ("", "an empty file"),
    ("scanner:\n", "no `scanner` mapping"),
    ("scanner: a string\n", "`scanner` of the wrong type"),
    ("scanner:\n  test_material:\n", "no `test_material` list"),
    ("scanner:\n  test_material: {}\n", "`test_material` of the wrong type"),
    ("- a\n- b\n", "a top-level sequence"),
    ("scanner: [this is not a mapping\n", "unparseable YAML"),
    ("scanner:\n  test_material: " + "[" * 100_000, "a file too deep to parse"),
    ("#" * (declarations.MAX_DECLARATION_BYTES + 1), "a file over the byte cap"),
    ("scanner:\n  test_material:\n    - path: frontend/scripts/drill\n"
     "      reason: ok\n", "a well-formed file"),
])
def test_the_declaration_file_is_reported_as_present_however_it_parses(tmp_path, body,
                                                                       why):
    """`present` says "this repo carries a `deployhub.yaml`", and it is the field the
    report's presence notice is built from — the ONE thing Phase 1 still says about a
    declaration file (`core.declaration-file`). Every early return sets it, and every
    one of those could be flipped to `False` or dropped: eighteen mutants lived on this
    field alone, because the tests around each malformed shape assert `accepted == ()`
    and `problems`, and never that the file was noticed at all.

    A `present=False` on a malformed file is not a cosmetic loss: it is the scanner
    telling the operator there is no declaration file in a repo that has one, which is
    the same lie as parsing it optimistically.
    """
    loaded = _declared(tmp_path, body, name=f"p{abs(hash(body))}")

    assert loaded.present is True, f"{why} reported no declaration file"


def test_a_declaration_file_that_is_not_utf8_is_a_problem_not_a_crash(tmp_path):
    """`load` promises it never raises for anything the scanned repo controls, and the
    `UnicodeDecodeError` arm of that promise was exercised by nothing — its whole
    `problems` tuple could be replaced with `None`, which is `Declarations.problems`
    holding a non-tuple that every consumer iterates."""
    root = _tree(tmp_path, _drill_files(), name="notutf8")
    (root / declarations.DECLARATION_FILE).write_bytes(b"scanner:\n  test_material: \xff\xfe\n")

    loaded = declarations.load(root)   # must not raise

    assert loaded.accepted == ()
    assert loaded.present is True
    assert any("could not be read" in p for p in loaded.problems), loaded.problems


def test_a_declaration_file_that_cannot_be_stat_ed_is_a_problem_not_a_crash(tmp_path,
                                                                           monkeypatch):
    """The other unreadable arm, and the one no filesystem this suite can build reaches:
    `path.stat()` failing after `is_file()` said yes. Patched at `Path.stat` rather than
    faked with a fixture tree, because the point is the handler, not the cause."""
    root = _tree(tmp_path, dict(_drill_files(), **{"deployhub.yaml": "scanner:\n"}),
                 name="nostat")
    real_stat = pathlib.Path.stat
    seen = []

    def refusing_stat(self, *args, **kwargs):
        # `is_file()` stats too, so the first call has to succeed — the arm under test
        # is the one where the file exists and then cannot be measured.
        if self.name == declarations.DECLARATION_FILE and seen:
            raise OSError(5, "Input/output error")
        if self.name == declarations.DECLARATION_FILE:
            seen.append(self)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", refusing_stat)

    loaded = declarations.load(root)   # must not raise

    assert loaded.accepted == ()
    assert loaded.present is True
    assert any("could not be read" in p for p in loaded.problems), loaded.problems


def test_a_file_exactly_at_the_byte_cap_is_still_parsed(tmp_path):
    """The byte cap's boundary, in the direction the existing test does not look: it
    feeds a file far over the limit, so `>` could become `>=` and the only casualty
    would be the one repo whose declaration file is exactly 256 KB."""
    entry = _declaration("frontend/scripts/drill")
    padding = "#" + "p" * (declarations.MAX_DECLARATION_BYTES - len(entry) - 2) + "\n"
    body = entry + padding
    assert len(body.encode("utf-8")) == declarations.MAX_DECLARATION_BYTES

    loaded = _declared(tmp_path, body, name="atcap")

    assert len(loaded.accepted) == 1, loaded.problems


def test_a_file_with_exactly_the_maximum_number_of_entries_is_read_whole(tmp_path):
    """`MAX_DECLARATIONS`' boundary, same argument as the byte cap's: the R7-10 test
    uses 120 entries, so the comparison could move by one and take a legitimate 50th
    declaration with it."""
    entries = "".join(f"    - path: d{i}\n      reason: drill {i}\n"
                      for i in range(declarations.MAX_DECLARATIONS))
    files = {"src/app.py": "print('hello')\n",
             "deployhub.yaml": "scanner:\n  test_material:\n" + entries}
    for i in range(declarations.MAX_DECLARATIONS):
        files[f"d{i}/qa.mjs"] = f'const staff_password = "{FAKE_HIGH_ENTROPY}";\n'

    loaded = _load(tmp_path, files, name="atmax")

    assert len(loaded.accepted) == declarations.MAX_DECLARATIONS
    assert loaded.problems == (), loaded.problems


def test_the_refusal_quoter_truncates_and_escapes_and_quotes_the_value_itself():
    """`_quote` is four lines and carried five mutants: `repr` could be handed `None` on
    any of its three branches and the truncation marker could be rewritten, because
    every test that reaches it asserts on the SENTENCE around the quote and never on the
    quote. R8-12 pinned the bound; this pins that what is inside the bound is the
    repo's own text.

    Asserted with literals rather than against `_QUOTE_LIMIT`, for the reason
    `test_issue_r7f_the_confirm_digest_is_sixteen_hex_characters` gives: a bound derived
    from the constant under test cannot fail when the constant moves.
    """
    assert declarations._quote("drill") == "'drill'"
    assert declarations._quote("a\nb") == "'a\\nb'"          # never a real newline
    assert declarations._quote("x" * 80) == "'" + "x" * 80 + "'"
    assert declarations._quote("y" * 81) == "'" + "y" * 80 + "' (truncated)"
    assert declarations._quote(17) == "17"                   # the non-string arm


@pytest.mark.parametrize("path,reason", [
    ("frontend/scripts/drill", "''"),                    # no reason
    ("frontend/scripts/drill", "x" * 201),               # reason over the cap
    (".//", DRILL_REASON),                               # the scan root
    ("/etc/secrets", DRILL_REASON),                      # absolute
    ("../outside", DRILL_REASON),                        # escapes the root
])
def test_every_refusal_that_quotes_a_path_quotes_the_real_one(tmp_path, path, reason):
    """Five refusals print the offending path through `_quote` so the repo's author can
    find the entry, and the argument could be replaced by `None` in every one of them
    with the suite green — leaving a refusal that says `(None)` and names nothing.

    Each is asserted on the `repr` form the quoter produces, which is also what keeps a
    newline in a path from forging a line in the message that rejects it.
    """
    body = ("scanner:\n"
            "  test_material:\n"
            f'    - path: "{path}"\n'
            f"      reason: {reason}\n")
    loaded = _declared(tmp_path, body, name=f"q{abs(hash(path + reason))}")

    assert loaded.accepted == ()
    assert repr(path) in _problems(loaded), loaded.problems


def test_an_enclosure_closer_at_the_very_start_of_a_value_is_refused(tmp_path):
    """`if at >= 0` — weakened to `> 0` or `>= 1`, a value that OPENS with `]` or `"`
    walks straight through the guard, and opening with the closer is the easiest forgery
    of the lot. Every existing case puts the character in the middle."""
    for closer in declarations.LABEL_ENCLOSURE_CLOSERS:
        body = ("scanner:\n"
                "  test_material:\n"
                "    - path: frontend/scripts/drill\n"
                f"      reason: {closer + ' fake creds'!r}\n")
        loaded = _declared(tmp_path, body, name=f"lead{ord(closer)}")

        assert loaded.accepted == (), f"a leading {closer!r} was accepted"
        assert "at offset 0" in _problems(loaded), loaded.problems


def test_the_refusal_reports_the_first_closer_not_the_last(tmp_path):
    """`value.find(closer)` could become `rfind` and the coordinates the refusal gives —
    the only thing it gives, since it deliberately quotes nothing — would point at a
    different character than the one that closes the enclosure first."""
    body = ("scanner:\n"
            "  test_material:\n"
            "    - path: frontend/scripts/drill\n"
            '      reason: \'a"b"c\'\n')
    loaded = _declared(tmp_path, body, name="firstcloser")

    assert loaded.accepted == ()
    assert "at offset 1" in _problems(loaded), loaded.problems


@pytest.mark.parametrize("path,phrase", [
    (".//", "declares the scan root"),
    ("/etc/secrets", "is an absolute path"),
    ("C:/windows/system32", "is an absolute path"),
    ("../outside", "escapes the scan root"),
    ("frontend/scripts/*", "looks like a glob"),
])
def test_each_path_refusal_says_which_rule_refused_it(tmp_path, path, phrase):
    """The existing test for this family asserts only that SOMETHING was refused, and
    every one of these paths is refused by a later rule too — a nonexistent directory is
    "rejected as stale" — so five separate guards could be deleted and the suite stayed
    green while the report told the operator the wrong thing to fix.

    `.//` is the one worth naming: `rstrip("/")` is what turns it into `.`, and with
    that call weakened (to `lstrip`, to `strip(None)`, or to a different character set)
    a path that means the repository root stops being recognized as one. The `or` chain
    in front of it hides the same way — flipped to `and`, the root check only fires when
    both spellings match.
    """
    loaded = _declared(tmp_path, _declaration(f'"{path}"'),
                       name=f"rule{abs(hash(path))}")

    assert loaded.accepted == ()
    assert phrase in _problems(loaded), loaded.problems


def test_a_trailing_slash_is_normalized_away_rather_than_refused(tmp_path):
    """The other side of `rstrip("/")`: a declaration written with a trailing slash is
    how people write directories, and it must be the SAME declaration."""
    loaded = _declared(tmp_path, _declaration("frontend/scripts/drill/"))

    assert [d.path for d in loaded.accepted] == ["frontend/scripts/drill"]

    # …and ONLY the slash: `rstrip` takes a character SET, so a widened one silently
    # eats the last characters of a legitimate directory name and declares its parent.
    files = dict(_drill_files())
    files["frontend/scripts/drillX/qa.mjs"] = "const a = 1;\n"
    named_x = _declared(tmp_path, _declaration("frontend/scripts/drillX"),
                        name="trailingx", files=files)
    assert [d.path for d in named_x.accepted] == ["frontend/scripts/drillX"], (
        named_x.problems)


def test_an_unparseable_file_reports_the_parsers_own_first_line(tmp_path):
    """The YAML refusal quotes `str(exc).splitlines()[0]` — the parser's one-line
    summary — and it could become `None`, or line 1 instead of line 0, with nothing
    noticing: the existing test asserts only that a problem exists. Line 1 of a PyYAML
    error is the `in "<unicode string>", line N, column M:` frame, which tells the
    author nothing and drags a quoted copy of their own file into the report."""
    loaded = _declared(tmp_path, "scanner: [unclosed\n", name="badyaml")

    problems = _problems(loaded)
    assert "not valid YAML" in problems
    assert "while parsing a flow sequence" in problems, problems
    assert "<unicode string>" not in problems, problems


def test_a_settings_package_refusal_names_the_file_django_would_read(tmp_path):
    """R7-4's guard reports WHICH file made it fire, and `str(PurePosixPath(*rel.parts))`
    could be handed `None` — the refusal then names a directory holding `None`. The
    existing R7-4 test asserts the entry was refused and not which file did it."""
    files = dict(_drill_files())
    files["backend/config/settings/base.py"] = "SECRET = 1\n"   # log-scrub: allow
    loaded = _declared(tmp_path, _declaration("backend/config"), name="settingspkg",
                       files=files)

    assert loaded.accepted == ()
    assert "settings/base.py" in _problems(loaded), loaded.problems


def test_the_confirm_slug_is_lowercased_alphanumerics_with_the_edges_trimmed():
    """Three mutations lived in one line of `confirm_question_id`: the character class
    could lose its uppercase range, and the `strip("-")` could strip whitespace or the
    wrong character set. Every other test in this file derives the expected id from the
    function itself — deliberately, so the CONTENT-keying stays single — which leaves
    the slug's own shape asserted by nothing.

    The slug matters beyond tidiness: `_env_name` turns any question id containing
    `.env.` into an environment variable name, and the slug is what guarantees a
    repo-controlled path cannot put a dot there.
    """
    import re as _re

    qid = declarations.confirm_question_id("X_Drill_", DRILL_REASON)

    # Matched WHOLE, not split on `--`: a slug that kept its trailing separator makes
    # the id `x-drill---<digest>`, and splitting on the first `--` hands back `x-drill`
    # either way. The separator is part of what is being asserted.
    assert _re.fullmatch(
        _re.escape(declarations.CONFIRM_ID_PREFIX) + r"x-drill--[0-9a-f]{16}", qid), qid


def test_a_repeated_claim_is_skipped_without_dropping_the_ones_after_it(tmp_path):
    """`continue` in the de-duplication loop could become `break`, and every claim after
    a repeat would go unasked — an operator confirming the questions they were shown
    while an unasked declaration sits in the file. The existing de-duplication test has
    nothing after the duplicate."""
    files = dict(_drill_files())
    files["frontend/scripts/qa"] = None
    files.pop("frontend/scripts/qa")
    files["frontend/scripts/qa/x.mjs"] = "const a = 1;\n"
    body = ("scanner:\n"
            "  test_material:\n"
            f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"
            f"    - path: frontend/scripts/drill\n      reason: {DRILL_REASON}\n"
            f"    - path: frontend/scripts/qa\n      reason: {DRILL_REASON}\n")
    loaded = _declared(tmp_path, body, name="dupthenmore", files=files)

    ids = [q.id for q in declarations.confirm_questions(loaded)]
    assert len(loaded.accepted) == 3, loaded.problems
    assert ids == [_drill_confirm_id(),
                   _drill_confirm_id(path="frontend/scripts/qa")]


# ── R15-SEC-2: the class widened, and this rule's set did not shrink ──────────

def test_issue_r15_sec_2_the_refusal_set_only_grew():
    """`_CONTROL_CHARS_RE` is compiled from `scanner.presentation.CONTROL_CLASS` (R15-SEC-1
    put the set in one place). R15-SEC-2 widened that class by the `surrogateescape` range
    for the CLI's sake — and a shared constant is exactly where a security rule gets
    narrowed by somebody solving a different problem.

    So: every code point this module refused before still is refused, and every addition
    is one somebody argued for. Computed over the whole code space rather than sampled,
    because "which characters does this regex match" is a question with an exact answer
    and a sample is how a range goes missing from the middle.

    R21-ARCH-2 is the second widening, and it is listed here in the same shape: the
    invisible NON-LETTERS the class had missed. The direction of this test is what
    matters — the set may only grow, and it may only grow by ranges written down.

    vss-supplement is the third, and it is the residual R21-ARCH-2 disclosed: the
    variation selectors SUPPLEMENT U+E0100-E01EF, the same characters as U+FE00-FE0F one
    plane up, left out only because that round's spec named exactly the other ranges.
    Listed below with the rest; the expectation is strictly larger than it was.

    vss-r1 is the fourth and it is the same lesson once more: U+034F and the RESERVED
    default-ignorables (U+2065, U+FFF0-FFF8, and everything in U+E0000-E0FFF that is not
    a tag character or a selector) render as nothing by design and belong to no script, so
    a `reason` could carry them and read as something it does not say. The exclusion
    assertion at the bottom GREW with it — it now names all four Hangul fillers, the Khmer
    inherent vowels and the two notation-bound families (Duployan, musical), which is the
    bucket the ruling of 2026-08-19 puts out and the set this test may never see refused.
    """
    historical = declarations.re.compile(
        "["
        "\\x00-\\x1f\\x7f\\x80-\\x9f"
        "\\u2028\\u2029\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069"
        "\\u061c\\u2060-\\u2064\\ufeff"
        "]")
    every = "".join(map(chr, range(0x110000)))
    surrogateescape = {chr(cp) for cp in range(0xDC80, 0xDD00)}          # R15-SEC-2
    invisible_non_letters = {chr(0x180E), chr(0xE0001)}.union(           # R21-ARCH-2
        *({chr(cp) for cp in range(start, stop)} for start, stop in
          [(0x206A, 0x2070), (0xFE00, 0xFE10), (0xFFF9, 0xFFFC),
           (0xE0020, 0xE0080),
           (0xE0100, 0xE01F0)]))                                        # vss-supplement
    unbound_default_ignorables = {chr(0x034F), chr(0x2065)}.union(       # vss-r1
        *({chr(cp) for cp in range(start, stop)} for start, stop in
          [(0xFFF0, 0xFFF9), (0xE0000, 0xE0001), (0xE0002, 0xE0020),
           (0xE0080, 0xE0100), (0xE01F0, 0xE1000)]))

    before = set(historical.findall(every))
    now = set(declarations._CONTROL_CHARS_RE.findall(every))

    assert before < now, "the refusal set shrank"
    assert now - before == (surrogateescape | invisible_non_letters
                            | unbound_default_ignorables), (
        "the class grew by something other than the widenings on record")

    # The exclusions this module ARGUED for, which no widening has disturbed: a
    # blank-looking LETTER is a badly written reason, not a forgery (round-6b), and a mark
    # that is part of how a script or a notation spells itself is that script's business.
    excluded = {chr(0x00AD)}                                            # soft hyphen
    excluded |= {chr(cp) for cp in (0x115F, 0x1160, 0x3164, 0xFFA0)}    # Hangul fillers
    excluded |= {chr(cp) for cp in (0x17B4, 0x17B5)}                    # Khmer vowels
    excluded |= {chr(cp) for cp in (0x180B, 0x180C, 0x180D, 0x180F)}    # Mongolian FVS
    excluded |= {chr(cp) for cp in range(0x1BCA0, 0x1BCA4)}             # Duployan
    excluded |= {chr(cp) for cp in range(0x1D173, 0x1D17B)}             # musical controls
    assert not (excluded & now), (
        f"a disclosed exclusion is now refused: {sorted(excluded & now)}")


def test_issue_r15_sec_2_a_declaration_carrying_an_undecodable_byte_is_still_refused():
    """…and the widening is not only set arithmetic: `deployhub.yaml` is repo-controlled
    text too, and a `reason` carrying an undecodable byte now meets the same refusal every
    other control code point meets — the coordinates, and not one character of the value.
    """
    entry = {"path": "frontend/drill", "reason": "drill scripts \udc9b here"}

    parsed, problem = declarations._read_entry(pathlib.Path("/nonexistent"), 0, entry)

    assert parsed is None
    assert "control character in its `reason`" in problem
    assert "U+DC9B" in problem
    assert "\udc9b" not in problem, "the refusal quoted the value it refused"

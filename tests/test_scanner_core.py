"""Scanner core: dispatch, precedence, merge, and the no-execution rule."""
import os
import pathlib

import pytest

from scanner import core
from scanner.modules.fallbacks import common_checks

REPO = pathlib.Path(__file__).resolve().parent.parent

# The common core suite, frozen. `scanner.core.scan` composes it into EVERY report
# (D-010 / SPEC-django-common-checks.md §1.3): a module may supersede a core result
# only by emitting the same id, never by omitting it. Adding a check to
# `common_checks` must be a conscious edit here too.
FROZEN_CORE_IDS = frozenset({
    "core.secret-scan", "core.lockfile", "core.gitignore", "core.tests-exist",
    "core.healthz", "core.digest-pins", "core.exposure-auth",
})


@pytest.mark.req("SEC-SCAN-NOEXEC")
def test_hub_side_scanner_code_invokes_no_subprocess_machinery():
    """Review3 §M1: the scanner's Hub-side path must be statically incapable of
    executing project code. Grep the whole scanner package for execution entry
    points — none may appear, in any module, ever (the sandbox runner will live
    OUTSIDE scanner/)."""
    banned = ("subprocess", "os.system", "os.exec", "os.spawn", "pty.",
              "commands.", "popen", "check_output", "check_call")
    offenders = []
    for py in (REPO / "scanner").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{py.relative_to(REPO)}: {token}")
    assert offenders == [], offenders


@pytest.mark.req("SCAN-S1-MODULAR-DISPATCH")
def test_multiple_matches_merge_into_one_report_and_manifest(tmp_path):
    class FakeModule:
        def __init__(self, name, hits, fragment):
            self.name, self._hits, self._fragment = name, hits, fragment

        def detect(self, root):
            return self._hits

        def checks(self, root):
            return [core.CheckResult(id=f"{self.name}.c", tier="ok", title="x")]

        def sandbox_checks(self, root):
            return []

        def wizard_questions(self, root):
            return [core.WizardQuestion(id=f"{self.name}.q", prompt="?")]

        def manifest_fragment(self, root, answers=None):
            return self._fragment

    fw, fb = core._FRAMEWORK_MODULES[:], core._FALLBACK_MODULES[:]
    core._FRAMEWORK_MODULES[:] = [
        FakeModule("svc", True, {"components": {"service": {"kind": "svc"}}}),
        FakeModule("stat", True, {"components": {"static_route": {"dir": "dist"}},
                                  "deploy_strategy": "recreate"}),
        FakeModule("nope", False, {}),
    ]
    core._FALLBACK_MODULES[:] = [FakeModule("fall", True, {})]
    try:
        mods = core.detect_modules(tmp_path)
        assert [m.name for m in mods] == ["svc", "stat"]  # fallback NOT consulted
        report = core.scan(tmp_path)
        # ONE manifest (§V5): both components under one draft, recreate wins (§N1).
        draft = report["manifest_draft"]
        assert draft["components"]["service"] == {"kind": "svc"}
        assert draft["components"]["static_route"] == {"dir": "dist"}
        assert draft["deploy_strategy"] == "recreate"
        assert report["schema_version"] == core.SCHEMA_VERSION
        assert {c["id"] for c in report["checks"]} >= {"svc.c", "stat.c"}
    finally:
        core._FRAMEWORK_MODULES[:] = fw
        core._FALLBACK_MODULES[:] = fb


@pytest.mark.req("SCAN-V4-FALLBACK-PRECEDENCE")
def test_fallbacks_run_only_when_no_framework_module_matches(tmp_path):
    class Stub:
        def __init__(self, name, hits):
            self.name, self._hits = name, hits

        def detect(self, root):
            return self._hits

        checks = staticmethod(lambda root: [])
        sandbox_checks = staticmethod(lambda root: [])
        wizard_questions = staticmethod(lambda root: [])
        manifest_fragment = staticmethod(lambda root, answers=None: {})

    fw, fb = core._FRAMEWORK_MODULES[:], core._FALLBACK_MODULES[:]
    core._FRAMEWORK_MODULES[:] = [Stub("django", False)]
    core._FALLBACK_MODULES[:] = [Stub("dockerfile", True)]
    try:
        assert [m.name for m in core.detect_modules(tmp_path)] == ["dockerfile"]
    finally:
        core._FRAMEWORK_MODULES[:] = fw
        core._FALLBACK_MODULES[:] = fb


@pytest.mark.req("SCAN-V4-FALLBACK-PRECEDENCE")
def test_issue_r4_11_a_matching_framework_module_suppresses_matching_fallbacks(tmp_path):
    """R4-11 WI-1: the precedence rule has two directions and only one was tested.

    The sibling test above stubs the framework module with `detect=False`, so
    `matched` is always empty and the "framework wins over an ALSO-matching
    fallback" direction never runs. Making `detect_modules` return
    `matched + fallbacks` kept it green. This asserts the other direction:
    both sides match, and the fallback must still not be consulted.
    """
    class Stub:
        def __init__(self, name, hits):
            self.name, self._hits = name, hits

        def detect(self, root):
            return self._hits

        checks = staticmethod(lambda root: [])
        sandbox_checks = staticmethod(lambda root: [])
        wizard_questions = staticmethod(lambda root: [])
        manifest_fragment = staticmethod(lambda root, answers=None: {})

    fw, fb = core._FRAMEWORK_MODULES[:], core._FALLBACK_MODULES[:]
    core._FRAMEWORK_MODULES[:] = [Stub("django", True), Stub("node-ts", False)]
    core._FALLBACK_MODULES[:] = [Stub("dockerfile", True), Stub("static", True)]
    try:
        assert [m.name for m in core.detect_modules(tmp_path)] == ["django"]
    finally:
        core._FRAMEWORK_MODULES[:] = fw
        core._FALLBACK_MODULES[:] = fb


@pytest.mark.req("SEC-SCAN-NOEXEC")
def test_sandbox_specs_surface_as_pending_results(tmp_path):
    """R4-11 WI-5: this is the only assertion that an executing check is
    *classified* as executing, and it carried no marker — so the second half of
    SEC-SCAN-NOEXEC ("every check is classified static or executing, and executing
    checks run only in a sandbox off the Hub") rode free while the grep test above
    proved only the first half."""
    spec = core.SandboxSpec(id="node.install", command=["pnpm", "install",
                                                        "--frozen-lockfile",
                                                        "--ignore-scripts"])
    result = spec.as_result()
    assert result.tier == "pending_sandbox" and result.execution == "executing"


@pytest.mark.req("SEC-SCAN-NOEXEC")
def test_issue_r4_11_every_real_module_check_is_classified_static_or_executing():
    """The classification clause, asserted over the real registry rather than one
    hand-built spec: every check a real module emits declares an `execution`, and
    the two classes map onto tiers exactly one way — executing ⇒ pending_sandbox
    (deferred to the off-Hub runner), static ⇒ never pending_sandbox."""
    import scanner.modules  # noqa: F401 — importing registers the modules

    roots = [REPO / "sample-node-site",
             REPO / "tests" / "fixtures" / "django" / "uv_asgi",
             REPO / "tests" / "fixtures" / "fallbacks" / "dockerfile_project"]
    seen_executing = 0
    for root in roots:
        report = core.scan(root)
        assert report["checks"], f"no checks produced for {root.name}"
        for check in report["checks"]:
            assert check["execution"] in ("static", "executing"), check
            if check["execution"] == "executing":
                seen_executing += 1
                assert check["tier"] == "pending_sandbox", check
            else:
                assert check["tier"] != "pending_sandbox", check
    assert seen_executing, "no executing check was emitted — the classification " \
                           "clause would be vacuously true"


# ── D-010: the core suite is composed by the registry, for every module ─────────
#
# The defect this closes (SPEC-django-common-checks.md): `scanner/modules/django.py`
# never called `common_checks`, so a Django scan report carried ZERO `core.*` checks
# — including blocker-tier `core.secret-scan`. A Django repo with a committed `.env`
# holding an `AKIA…` key scanned clean while the byte-identical Node repo blocked.
# Every project in the fleet is Django. The fix moves composition out of the modules
# and into `core.scan`, which makes forgetting unrepresentable rather than merely
# tested-for. These three tests are the three layers silence has to get past.

MODULE_FIXTURES = {
    "django": REPO / "tests" / "fixtures" / "django" / "uv_asgi",
    "node-ts": REPO / "sample-node-site",
    "dockerfile": REPO / "tests" / "fixtures" / "fallbacks" / "dockerfile_project",
    "static": REPO / "tests" / "fixtures" / "fallbacks" / "static_site",
}


def test_every_registered_module_scan_carries_the_full_core_suite(tmp_path):
    """The invariant (D-010): every scan report with >=1 matched module carries all
    seven `core.*` ids, each exactly once. Inapplicability is expressed by
    supersession (a module emitting the SAME id), never by absence."""
    import scanner.modules  # noqa: F401 — importing registers the modules

    core_ids = {c.id for c in common_checks(tmp_path)}
    assert core_ids == set(FROZEN_CORE_IDS), (
        "the common core suite changed: update FROZEN_CORE_IDS deliberately, and "
        "check every module's supersessions still line up")

    framework, fallback = core.registered_modules()
    assert {m.name for m in framework + fallback} == set(MODULE_FIXTURES), (
        "a module was registered without a MODULE_FIXTURES row. Add one pointing at "
        "a fixture tree the module detects — otherwise the core-suite invariant "
        "silently stops covering your module, which is exactly how the django gap "
        "survived (D-010).")

    for name, root in MODULE_FIXTURES.items():
        report = core.scan(root)
        assert name in report["modules"], f"{name}: {root} no longer detects"
        ids = [c["id"] for c in report["checks"]]
        assert core_ids <= set(ids), (
            f"{name}: core suite missing "
            f"{sorted(core_ids - set(ids))} from the scan report")
        assert len(ids) == len(set(ids)), (
            f"{name}: duplicate check ids in the report: "
            f"{sorted(i for i in set(ids) if ids.count(i) > 1)}")


@pytest.mark.req("SCAN-S1-MODULAR-DISPATCH")
def test_monorepo_match_runs_the_core_suite_exactly_once(tmp_path):
    """Two framework modules co-match (§V4 permits it) and the outputs merge into
    ONE report — so the core suite must appear once, not once per module.

    Honesty note for the reviewer: this test is green on `05cd0d5` *by accident* —
    node-ts supplies the suite there and django's omission is masked. Its red
    conditions are the two wrong futures: per-module composition (every core id
    twice) and no composition at all (zero).
    """
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    (tmp_path / "requirements.txt").write_text("Django==5.2\n")
    (tmp_path / "settings.py").write_text(
        "import os\nSECRET_KEY = os.environ['DJANGO_SECRET_KEY']\n")
    (tmp_path / "package.json").write_text(
        '{"name": "svc", "dependencies": {"fastify": "^4.28.1"}}\n')

    report = core.scan(tmp_path)
    assert report["modules"] == ["django", "node-ts"]
    ids = [c["id"] for c in report["checks"]]
    for core_id in FROZEN_CORE_IDS:
        assert ids.count(core_id) == 1, (
            f"{core_id} appeared {ids.count(core_id)} times in a two-module report")


def test_module_emitting_unknown_core_id_is_a_loud_error(tmp_path):
    """The override guard: a module may supersede a core result by emitting the same
    id, but a typo'd / invented `core.*` id must not silently append itself to the
    suite — that is how an unreviewed pseudo-core check would enter a report."""
    class BogusCoreModule:
        name = "bogus"

        def detect(self, root):
            return True

        def checks(self, root):
            return [core.CheckResult(id="core.bogus", tier="ok", title="x")]

        def sandbox_checks(self, root):
            return []

        def wizard_questions(self, root):
            return []

        def manifest_fragment(self, root, answers=None):
            return {}

    fw, fb = core._FRAMEWORK_MODULES[:], core._FALLBACK_MODULES[:]
    core._FRAMEWORK_MODULES[:] = [BogusCoreModule()]
    core._FALLBACK_MODULES[:] = []
    try:
        with pytest.raises(ValueError):
            core.scan(tmp_path)
    finally:
        core._FRAMEWORK_MODULES[:] = fw
        core._FALLBACK_MODULES[:] = fb


# ── R10-A3: the refusal hook, and what a module that has none declares ─────────

def test_issue_r10_a3_a_module_without_the_hook_declares_no_refusals():
    """`refused_paths` is optional, and its absence is a claim: this module has told the
    operator about no files of its own, so `core.symlinked-files` keeps all of them.

    That is true of every registered module but `node-ts` — `fallbacks` and `django`
    read through the shared walk and the shared `read_contained`, whose refusals ARE the
    core check's list — so the default is what almost every scan uses and it may not
    quietly become "refuses everything".
    """
    class Plain:
        name = "plain"

    assert core.module_refused_paths(Plain(), "/nonexistent") == []

    framework, fallback = core.registered_modules()
    declaring = [m.name for m in framework + fallback
                 if getattr(m, "refused_paths", None) is not None]
    assert declaring == ["node-ts"], declaring


# ── R11-A2: the refusal hook had a contract nobody wrote down and nothing checked ──
#
# `module_refused_paths` subtracts what a module returns from `core.symlinked-files`.
# What SPELLING of a path makes that subtraction land was stated nowhere, and the
# subtraction is done by set membership on `Path`, so a module returning the same file
# under a different spelling subtracts nothing and one file is two warning lines again —
# the exact defect R10-A3 closed, reopened silently. In the other direction there was no
# check at all: a path the module never mentioned in any check it emits deletes core's
# line for that file, and the operator is told about it by nobody.
#
# Both are fail-open, and both are demonstrated below against modules that pass every
# other gate in this file.

class _RefusingModule:
    """A module that declares a refusal. What it RETURNS is the test's variable."""

    name = "refusing-test-module"

    def __init__(self, returned, detail=None, tier="warning"):
        self._returned = returned
        self._detail = detail
        # F-2: the TIER the module's own sentence is emitted at. A refusal is a warning
        # (`node-ts.symlinked-files` and `core.symlinked-files` both are) — this is a
        # parameter so a test can emit the sentence somewhere the operator does not read
        # a refusal from, which is how the prefix rule was defeated.
        self._tier = tier

    def detect(self, root):
        return True

    def refused_paths(self, root):
        return self._returned(pathlib.Path(root))

    def checks(self, root):
        if self._detail is None:
            return []
        return [core.CheckResult(id="refusing-test-module.refusals", tier=self._tier,
                                 title="what this module refused to read",
                                 detail=self._detail(pathlib.Path(root)))]

    def sandbox_checks(self, root):
        return []

    def wizard_questions(self, root):
        return []

    def manifest_fragment(self, root, answers=None):
        return {}


def _linked_env(tmp_path):
    """A tree whose committed `.env` resolves into a neighbour — the refusal both the
    core walk and a framework module could name."""
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    (neighbour / "secrets.env").write_text("AWS_SECRET_ACCESS_KEY=x\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    os.symlink("../neighbour/secrets.env", root / ".env")
    return root


@pytest.fixture
def registry_sandbox():
    """Register modules for one test and put the real registry back afterwards."""
    frameworks, fallbacks = core.registered_modules()
    yield
    core._FRAMEWORK_MODULES[:] = frameworks
    core._FALLBACK_MODULES[:] = fallbacks


def test_issue_r11_a2_a_resolved_spelling_is_refused_out_loud(tmp_path,
                                                              registry_sandbox):
    """DEFEAT ONE: the same file, resolved.

    `_check_symlinked_files` subtracts by `Path` equality against what the CORE walk
    found, which is the root-joined walked spelling. A module that returns
    `path.resolve()` — the obvious thing to write, and what half this module's own
    containment code does — hands over a path that matches nothing, subtracts nothing,
    and the file is reported twice: once by core and once by the module. Silently, and
    in the direction R10-A3 was filed about.
    """
    root = _linked_env(tmp_path)
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [(r / ".env").resolve()],
        detail=lambda r: "refused '.env'")]
    core._FALLBACK_MODULES[:] = []

    with pytest.raises(ValueError, match="outside the scan root"):
        core.scan(root)


def test_issue_r11_a2_a_refusal_the_module_never_reported_is_refused_out_loud(
        tmp_path, registry_sandbox):
    """DEFEAT TWO: fail-open, in the direction that deletes a warning.

    The hook's whole justification is "I have already told the operator about these
    files, in my own words". A module that returns a path and says nothing about it
    anywhere deletes core's line for that file and leaves no trace: no check names it,
    no count moves, and the operator's model of what the scan read is wrong with nothing
    on screen to correct it.
    """
    root = _linked_env(tmp_path)
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / ".env"], detail=None)]
    core._FALLBACK_MODULES[:] = []

    with pytest.raises(ValueError, match="names it in no check"):
        core.scan(root)


def test_issue_r11_a2_an_honest_module_is_not_accused(tmp_path, registry_sandbox):
    """…and the guard has to let the honest arrangement through, or it is a gate that
    forbids the feature. The contract is: the root-joined walked spelling, named in the
    detail of a check this module emits. Both halves, and the subtraction still lands.
    """
    root = _linked_env(tmp_path)
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / ".env"],
        detail=lambda r: "symlinked file '.env' resolves outside the scan root")]
    core._FALLBACK_MODULES[:] = []

    report = core.scan(root)
    ids = [c["id"] for c in report["checks"]]

    assert "refusing-test-module.refusals" in ids
    assert "core.symlinked-files" not in ids, (
        "the subtraction did not land — the file is refused twice again")
    # `core.secret-scan` still names it, and that is the R9-A carve-out rather than a
    # second refusal line: an escaping `.env` is READ by the secret axis on purpose,
    # because a linked credential is a finding whichever tree it lives in.
    assert ".env" in next(c for c in report["checks"]
                          if c["id"] == "core.secret-scan")["detail"]


def test_issue_r11_a2_a_long_path_printed_in_bounded_form_is_not_accused(
        tmp_path, registry_sandbox):
    """The one way an honest module could have tripped this, closed by design.

    Repo-controlled text in a report is BOUNDED — `node_ts._quote_pattern` cuts at 80
    characters and appends `(truncated)` — so a deeply nested refused file is named in
    the detail by a prefix of its own path. A guard demanding the whole string would
    accuse the module that behaves most carefully, which is the wrong direction for a
    gate to be wrong in.
    """
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    (neighbour / "metrics.ts").write_text("export const m = 1;\n", encoding="utf-8")
    root = tmp_path / "repo"
    deep = root / ("packages/a-rather-long-package-name/src/features/telemetry/"
                   "collectors/runtime")
    deep.mkdir(parents=True)
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    rel = (deep / "metrics.ts").relative_to(root).as_posix()
    assert len(rel) > 80, rel
    os.symlink(os.path.relpath(neighbour / "metrics.ts", deep), deep / "metrics.ts")
    # …and it really does leave the tree, so the refusal under test is a refusal. The
    # first draft of this counted `..` by hand, came up one short, and asserted the
    # absence of a check that a contained link would never have produced.
    assert not (deep / "metrics.ts").resolve().is_relative_to(root)

    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / rel],
        detail=lambda r: f"symlinked source file {rel[:80]!r} (truncated) — not read")]
    core._FALLBACK_MODULES[:] = []

    report = core.scan(root)

    assert "core.symlinked-files" not in [c["id"] for c in report["checks"]], (
        "the subtraction did not land — the module named the file in the only form a "
        "bounded report can print it in")
    # The module's line is the only one that mentions the file at all — by the bounded
    # prefix, which is the only spelling of it a truncating report contains.
    assert [c["id"] for c in report["checks"] if rel[:80] in c["detail"]] == \
        ["refusing-test-module.refusals"]


def test_issue_r11_a2_the_live_module_satisfies_its_own_contract(tmp_path):
    """The contract is not a rule invented for the test modules above: the one module
    that declares the hook has to pass it on a real tree, through the real registry."""
    neighbour = tmp_path / "edge-neighbour" / "shared-lib" / "src"
    neighbour.mkdir(parents=True)
    (neighbour / "metrics.ts").write_text("export const m = 1;\n", encoding="utf-8")
    root = tmp_path / "edgerepo"
    src = root / "packages" / "server" / "src"
    src.mkdir(parents=True)
    (root / "package.json").write_text('{"name": "edge", "private": true}\n',
                                       encoding="utf-8")
    (root / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\n",
                                              encoding="utf-8")
    (root / "packages" / "server" / "package.json").write_text(
        '{"name": "@e/server", "main": "dist/index.js",\n'
        ' "dependencies": {"fastify": "^4.28.0"}}\n', encoding="utf-8")
    (src / "index.ts").write_text("import Fastify from 'fastify';\n", encoding="utf-8")
    os.symlink("../../../../edge-neighbour/shared-lib/src/metrics.ts",
               src / "metrics.ts")

    report = core.scan(root)

    assert [c["id"] for c in report["checks"] if "metrics.ts" in c["detail"]] == \
        ["node-ts.symlinked-files"]


def _sibling_links(tmp_path):
    """A deep package with two escaping source links, `alpha.ts` and `beta.ts`.

    The directory part is longer than `_REFUSAL_NAMED_PREFIX`, so the two files'
    repo-relative spellings share their first 60 characters — which is the whole point:
    the truncation tolerance cannot tell them apart, and something else has to.
    """
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    for name in ("alpha.ts", "beta.ts"):
        (neighbour / name).write_text("export const x = 1;\n", encoding="utf-8")
    root = tmp_path / "repo"
    deep = root / ("packages/a-rather-long-package-name/src/features/telemetry/"
                   "collectors/runtime")
    deep.mkdir(parents=True)
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    rel = {name: (deep / name).relative_to(root).as_posix()
           for name in ("alpha.ts", "beta.ts")}
    assert rel["alpha.ts"][:core._REFUSAL_NAMED_PREFIX] == \
        rel["beta.ts"][:core._REFUSAL_NAMED_PREFIX], rel
    for name in ("alpha.ts", "beta.ts"):
        # `relpath` rather than a hand-counted run of `..`: the first draft of this
        # helper was one `..` short, so both links resolved INSIDE the root, nothing
        # escaped, and the assertion that core still reports the unnamed sibling passed
        # over an empty list. A committed link that does not escape is not this fixture.
        os.symlink(os.path.relpath(neighbour / name, deep), deep / name)
        assert not (deep / name).resolve().is_relative_to(root), name
    return root, rel


def test_issue_f2_a_prefix_match_only_counts_where_a_refusal_is_reported(
        tmp_path, registry_sandbox):
    """F-2: the truncation tolerance let a SIBLING's name vouch for a file, in any tier.

    `_REFUSAL_NAMED_PREFIX` exists so a module that prints a bounded form of a long path
    is not accused of hiding a refusal it reported. Two files under one deep directory
    share that prefix, so an `advice`-tier line mentioning `alpha.ts` satisfied the guard
    for `beta.ts` — and `beta.ts` then dropped out of `core.symlinked-files` with nothing
    anywhere saying it was not read. Fail-open, through the tolerance added to keep the
    guard honest.

    A refusal is a WARNING wherever this repo emits one (`core.symlinked-files`,
    `node-ts.symlinked-files`), so a prefix now only counts in a warning-or-worse detail:
    the weaker match is admitted only where the operator reads refusals from. The exact
    spelling still counts anywhere, because it names the file and nothing else does.
    """
    root, rel = _sibling_links(tmp_path)
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / rel["beta.ts"]],
        detail=lambda r: f"vendored module {rel['alpha.ts']!r} is imported from outside",
        tier="advice")]
    core._FALLBACK_MODULES[:] = []

    with pytest.raises(ValueError, match="names it in no check"):
        core.scan(root)


def test_issue_f2_the_same_line_at_warning_tier_is_accepted(tmp_path, registry_sandbox):
    """…and the tier is the whole of the difference, so the rule is about WHERE the
    sentence is and not about what it says.

    Same module, same detail, emitted as a warning: the prefix counts, and this is the
    honest long-path case R11-A2 added the tolerance for. Its own path is what the line
    names here — a module quoting a bounded form of the file it refused.
    """
    root, rel = _sibling_links(tmp_path)
    truncated = rel["beta.ts"][:core._REFUSAL_NAMED_PREFIX]
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / rel["beta.ts"]],
        detail=lambda r: f"symlinked source file {truncated!r} (truncated) — not read")]
    core._FALLBACK_MODULES[:] = []

    report = core.scan(root)
    refusals = [c for c in report["checks"] if c["id"] == "core.symlinked-files"]

    assert refusals, "alpha.ts was never named by the module and must still be reported"
    assert "alpha.ts" in refusals[0]["detail"]
    assert "beta.ts" not in refusals[0]["detail"], (
        "the module's own line names it; this one must not name it again")

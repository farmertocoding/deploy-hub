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


# ── R11-A2 / R12-A1: the refusal hook, and a guard that used to read prose ────
#
# `module_refused_paths` lets a module say "I have already told the operator about these
# files, in my own words", and `scan` acts on it by dropping them from
# `core.symlinked-files`. R11-A2 gave that claim a guard. R12-A1 replaced what the guard
# LOOKS AT: it read `detail`, which is a report line — quoted through `repr`, truncated,
# capped, pluralized — and matching a path against a report line is a coincidence
# detector. Three demonstrations below, all on trees anybody can commit, all green before
# the machine-readable field existed.

class _RefusingModule:
    """A module that declares a refusal. What it RETURNS and what its check REPORTS are
    the test's two variables, because the whole finding is that those are different
    things and only one of them is a fact."""

    name = "refusing-test-module"

    def __init__(self, returned, detail=None, declared=None, tier="warning",
                 check_id="refusing-test-module.refusals", supersedes=None):
        self._returned = returned
        self._detail = detail
        self._declared = declared
        self._tier = tier
        self._check_id = check_id
        if supersedes is not None:
            self.supersedes = supersedes

    def detect(self, root):
        return True

    def refused_paths(self, root):
        return self._returned(pathlib.Path(root))

    def checks(self, root):
        if self._detail is None and self._declared is None:
            return []
        root = pathlib.Path(root)
        return [core.CheckResult(
            id=self._check_id, tier=self._tier,
            title="what this module refused to read",
            detail=self._detail(root) if self._detail else "",
            refused_paths=list(self._declared(root) if self._declared else []))]

    def sandbox_checks(self, root):
        return []

    def wizard_questions(self, root):
        return []

    def manifest_fragment(self, root, answers=None):
        return {}


@pytest.fixture
def registry_sandbox():
    """Register modules for one test and put the real registry back afterwards."""
    frameworks, fallbacks = core.registered_modules()
    yield
    core._FRAMEWORK_MODULES[:] = frameworks
    core._FALLBACK_MODULES[:] = fallbacks


def _escaping_tree(tmp_path, names, contents="export const x = 1;\n"):
    """A repo whose `src/` carries one committed symlink per name, each resolving into a
    neighbouring tree — the shape both refusal channels are about."""
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    for name in names:
        target = neighbour / pathlib.PurePosixPath(name).name
        target.write_text(contents, encoding="utf-8")
        link = root / "src" / pathlib.PurePosixPath(name).name
        os.symlink(os.path.relpath(target, link.parent), link)
        assert not link.resolve().is_relative_to(root), name
    return root


def test_issue_r11_a2_a_resolved_spelling_is_refused_out_loud(tmp_path,
                                                              registry_sandbox):
    """The spelling half of the contract, unchanged by R12-A1.

    `_check_symlinked_files` subtracts by `Path` equality against what the CORE walk
    found, which is the root-joined walked spelling. A module that returns
    `path.resolve()` hands over a path that matches nothing, subtracts nothing, and the
    file is reported twice — by core and by the module — which is the defect R10-A3 was
    filed to fix, reopened by a one-word edit.
    """
    root = _escaping_tree(tmp_path, ["metrics.ts"])
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [(r / "src/metrics.ts").resolve()],
        declared=lambda r: ["src/metrics.ts"])]
    core._FALLBACK_MODULES[:] = []

    with pytest.raises(ValueError, match="outside the scan root"):
        core.scan(root)


def test_issue_r11_a2_a_refusal_the_module_never_reported_is_refused_out_loud(
        tmp_path, registry_sandbox):
    """Fail-open, in the direction that deletes a warning: a module that returns a path
    and reports it in no check deletes core's line for that file and leaves no trace."""
    root = _escaping_tree(tmp_path, ["metrics.ts"])
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / "src/metrics.ts"])]
    core._FALLBACK_MODULES[:] = []

    with pytest.raises(ValueError, match="no check in the finished report"):
        core.scan(root)


def test_issue_r11_a2_an_honest_module_is_not_accused(tmp_path, registry_sandbox):
    """…and the guard has to let the honest arrangement through, or it forbids the
    feature. The contract is: the walked spelling from the hook, the repo-relative POSIX
    spelling in some check's `refused_paths`, and the subtraction still lands.
    """
    root = _escaping_tree(tmp_path, ["metrics.ts"])
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / "src/metrics.ts"],
        declared=lambda r: ["src/metrics.ts"],
        detail=lambda r: "symlinked file 'src/metrics.ts' resolves outside the root")]
    core._FALLBACK_MODULES[:] = []

    report = core.scan(root)
    ids = [c["id"] for c in report["checks"]]

    assert "refusing-test-module.refusals" in ids
    assert "core.symlinked-files" not in ids, (
        "the subtraction did not land — the file is refused twice again")


def test_issue_r12_a1_s2_a_longer_name_containing_the_path_does_not_vouch_for_it(
        tmp_path, registry_sandbox):
    """S2: `rel in details` was an UNANCHORED SUBSTRING match.

    `src/metrics.ts` is a substring of `src/metrics.tsx`, so a module that refused the
    first while its report named the second passed the guard. Measured before the fix, on
    this tree: the scan returned green, `core.symlinked-files` named `src/metrics.tsx`
    alone, and `src/metrics.ts` — refused, subtracted, gone — appeared in no check at all.

    Two files whose names differ by one character is the smallest version. The same hole
    swallowed any pair where one path contains the other, which on a real tree is every
    `foo.ts` beside a `foo.ts.map`.
    """
    root = _escaping_tree(tmp_path, ["metrics.ts", "metrics.tsx"])
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / "src/metrics.ts"],
        declared=lambda r: ["src/metrics.tsx"],
        detail=lambda r: "refused src/metrics.tsx")]
    core._FALLBACK_MODULES[:] = []

    with pytest.raises(ValueError, match="src/metrics.ts"):
        core.scan(root)


def test_issue_r12_a1_a_sibling_under_the_same_directory_does_not_vouch_either(
        tmp_path, registry_sandbox):
    """…and the deep-sibling case with it, which the deleted prefix tolerance had to be
    tiered to survive (F-2). Set membership has no tolerance to tier: `alpha.ts` is not
    `beta.ts`, at any path length, in any check.
    """
    root = _escaping_tree(tmp_path, ["alpha.ts", "beta.ts"])
    core._FRAMEWORK_MODULES[:] = [_RefusingModule(
        returned=lambda r: [r / "src/beta.ts"],
        declared=lambda r: ["src/alpha.ts"])]
    core._FALLBACK_MODULES[:] = []

    with pytest.raises(ValueError, match="src/beta.ts"):
        core.scan(root)


def test_issue_r12_a1_s3_a_backslash_in_a_committed_name_does_not_kill_the_scan(
        tmp_path):
    """S3: the LIVE module, and a one-file denial of service.

    `node-ts` names refused paths in its report through `_quote_pattern`, which is
    `repr` — correct for a report line, because a filename may contain a newline. The
    guard compared the RAW spelling against that line, so a committed symlink called
    `src/metri\\cs.ts` — legal on every filesystem this runs on, and committable —
    printed as `'src/metri\\\\cs.ts'` and matched nothing. `scan()` then raised, accusing
    the module of hiding a refusal it had just announced: every scan of that repository
    dead, from one file in it.

    No registry substitution here: this is the real module through the real registry, on
    the tree that produced the crash.
    """
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    (neighbour / "metrics.ts").write_text("export const x = 1;\n", encoding="utf-8")
    root = tmp_path / "repo"
    src = root / "src"
    src.mkdir(parents=True)
    (root / "package.json").write_text(
        '{"name": "e", "main": "dist/index.js",\n'
        ' "dependencies": {"fastify": "^4.28.0"}}\n', encoding="utf-8")
    (src / "index.ts").write_text("import Fastify from 'fastify';\n", encoding="utf-8")
    link = src / "metri\\cs.ts"
    os.symlink(os.path.relpath(neighbour / "metrics.ts", src), link)

    report = core.scan(root)
    line = next(c for c in report["checks"] if c["id"] == "node-ts.symlinked-files")

    assert line["refused_paths"] == ["src/metri\\cs.ts"], (
        "the fact carries the name the filesystem has")
    assert "metri\\\\cs.ts" in line["detail"], (
        "…and the sentence still quotes it, which is why the two cannot be one field")


def test_issue_r12_a1_s4_a_second_supersession_cannot_delete_the_naming(
        tmp_path, registry_sandbox):
    """S4: the guard ran on what each module EMITTED, before supersession resolved.

    An honest module refuses a file, reports it, and satisfies the guard. A second module
    superseding the same core id then replaces that check — and the refusal the first
    module had subtracted from `core.symlinked-files` is reported by nothing that reaches
    the operator. Measured before the fix: `core.symlinked-files` surviving as an `ok`
    line reading "Nothing was refused", with the escaping file named nowhere, and the
    scan returning 0.

    The guard now runs against the SURVIVING report. `register` refuses this pair
    outright as well (below); the two are not redundant — registration catches the
    declaration, this catches the report, and a test that swaps the registry directly
    (as this one does) is exactly the shape a future in-process caller might have.
    """
    root = _escaping_tree(tmp_path, ["metrics.ts", "other.ts"])
    namer = _RefusingModule(
        returned=lambda r: [r / "src/metrics.ts"],
        declared=lambda r: ["src/metrics.ts"],
        detail=lambda r: "src/metrics.ts — not read",
        check_id="core.symlinked-files",
        supersedes=frozenset({"core.symlinked-files"}))
    quieter = _RefusingModule(
        returned=lambda r: [], declared=lambda r: [], tier="ok",
        detail=lambda r: "", check_id="core.symlinked-files",
        supersedes=frozenset({"core.symlinked-files"}))
    quieter.name = "quieter-test-module"
    core._FRAMEWORK_MODULES[:] = [namer, quieter]
    core._FALLBACK_MODULES[:] = []

    with pytest.raises(ValueError, match="no check in the finished report"):
        core.scan(root)


def test_issue_r12_a1_s4_two_modules_may_not_supersede_one_core_id(registry_sandbox):
    """…and the declaration itself is refused at import time, where the diff shows it.

    Supersession replaces an entry IN PLACE, so with two claimants the report shows
    whichever module ran last — an ordering nothing declares and no test reads.
    """
    core._FRAMEWORK_MODULES[:] = []
    core._FALLBACK_MODULES[:] = []
    first = _RefusingModule(returned=lambda r: [],
                            supersedes=frozenset({"core.lockfile"}))
    second = _RefusingModule(returned=lambda r: [],
                             supersedes=frozenset({"core.lockfile", "core.gitignore"}))
    second.name = "second-test-module"

    core.register(first)
    with pytest.raises(ValueError, match="core.lockfile"):
        core.register(second)

    # A module that supersedes something else entirely is fine — the rule is about one
    # id having one owner, not about supersession being rare.
    third = _RefusingModule(returned=lambda r: [],
                            supersedes=frozenset({"core.gitignore"}))
    third.name = "third-test-module"
    core.register(third)


def test_issue_r12_a1_s4_the_live_registry_has_no_overlapping_supersessions():
    """The rule holds for the modules that are actually loaded, which `register` can only
    promise for modules registered THROUGH it — the tests above swap the lists directly,
    and so could a future caller."""
    framework, fallback = core.registered_modules()
    claimed = {}
    for module in framework + fallback:
        for check_id in core.module_supersedes(module):
            claimed.setdefault(check_id, []).append(module.name)

    assert {k: v for k, v in claimed.items() if len(v) > 1} == {}, claimed


def test_issue_r12_a1_the_field_is_absent_from_a_check_that_refused_nothing():
    """`as_dict` omits `refused_paths` when it is empty, which is almost every check.

    A stored report from a tree with no committed links is BYTE-IDENTICAL to the one this
    field did not exist for — which is what keeps the recorded demo artifacts, the sim
    fixtures and every `Project.scan_report` in the database where they are, and why
    `SCHEMA_VERSION` does not move: a bump means a stored report's MEANING changed (R8-2),
    and absent still means "no refusals", exactly as it did when absence was the only
    possibility.
    """
    plain = core.CheckResult(id="x.y", tier="ok", title="t").as_dict()
    assert sorted(plain) == ["detail", "execution", "fix_hint", "id", "tier", "title"]

    naming = core.CheckResult(id="x.y", tier="warning", title="t",
                              refused_paths=["src/a.ts"]).as_dict()
    assert naming["refused_paths"] == ["src/a.ts"]


def test_issue_r12_a1_the_core_refusal_line_reports_every_path_it_is_about(tmp_path):
    """`core.symlinked-files` prints ten paths and counts the rest, because a report is
    for reading. The FACT is all of them — a guard that read the prose would have been
    satisfied by the first ten and blind to the eleventh."""
    from scanner.modules.fallbacks import _MAX_SKIPPED_REPORTED

    names = [f"file{i:02d}.ts" for i in range(_MAX_SKIPPED_REPORTED + 3)]
    root = _escaping_tree(tmp_path, names)

    # `common_checks` directly: this tree is a `.py` file and a row of links, which no
    # framework module claims, so a full `scan` composes no core suite at all.
    line = next(c for c in common_checks(root) if c.id == "core.symlinked-files")

    assert sorted(line.refused_paths) == [f"src/{name}" for name in names]
    assert line.detail.count("\n") < len(names), "the prose is capped, as designed"
    assert "and 3 more" in line.detail

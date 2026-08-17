"""Scanner core: dispatch, precedence, merge, and the no-execution rule."""
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

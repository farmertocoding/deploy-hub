"""Scanner core: dispatch, precedence, merge, and the no-execution rule."""
import pathlib

import pytest

from scanner import core

REPO = pathlib.Path(__file__).resolve().parent.parent


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

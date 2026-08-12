"""Gate-integrity tests for conformance/check.py (R4-9, SPEC-gate-integrity §3).

Round 4 found that `check.py` measured *marker presence*, not test outcomes: a
marked test could fail, be skipped, or live in a file pytest never collects and
the gate still exited 0.  These tests pin the corrected semantics.

Every test here drives `check.py` **as a subprocess** against a throwaway repo
built in `tmp_path` (registry + tests + run-report + Makefile + docs).  Nothing
is imported or monkeypatched: the property under test is that the gate behaves
correctly *when actually invoked*, which is exactly what the AST-walk version
failed at.

Chicken-and-egg note: the pytest plugin in tests/conftest.py writes the real
`conformance/run-report.json` at session finish.  These tests never spawn a
nested pytest, and every subprocess here is launched with
`CONFORMANCE_RUN_REPORT=off` so that even if one ever did, it could not clobber
the report of the run it is executing inside.
"""
import json
import os
import pathlib
import re
import subprocess
import sys

import gates
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
CHECK = REPO / "conformance" / "check.py"


def head_sha():
    out = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def write_repo(root, *, reqs, tests_src=None, report="auto", waivers="",
               makefile=None, files=None, outcomes=None, workflows=None):
    """Build a throwaway repo tree for check.py to run against.

    reqs      : list of dicts -> conformance/requirements.yaml
    tests_src : {"tests/test_x.py": "<source>"}
    report    : dict written verbatim, None to write no file at all, or "auto"
                to build a fresh report from `outcomes` with the real HEAD sha.
    files     : {"path": "content"} arbitrary extra files (demos, docs, ...)
    workflows : {"push-checks.yml": "<yaml>"} -> .github/workflows/ (round-5 F3:
                a gate: target only resolves if some workflow step invokes it)
    """
    root = pathlib.Path(root)
    (root / "conformance").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)

    lines = ["schema_version: 1", "requirements:"]
    for r in reqs:
        first = True
        for k, v in r.items():
            prefix = "  - " if first else "    "
            first = False
            if isinstance(v, list):
                lines.append(f"{prefix}{k}:")
                for item in v:
                    lines.append(f"      - {json.dumps(item)}")
            elif isinstance(v, int):
                lines.append(f"{prefix}{k}: {v}")
            else:
                lines.append(f"{prefix}{k}: {json.dumps(str(v))}")
    (root / "conformance" / "requirements.yaml").write_text("\n".join(lines) + "\n")

    for rel, src in (tests_src or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)

    if report == "auto":
        report = {
            "schema_version": 1,
            "sha": head_sha(),
            # The report is bound to the working tree, not just to HEAD (round-5
            # deferral): HEAD does not move when a file is edited. A fixture standing in
            # for a real run has to carry the same binding the plugin writes.
            "tree": gates.tree_fingerprint(REPO),
            "generated_at": "2026-08-11T00:00:00Z",
            "pytest_exitstatus": 0,
            # Round-5 F7: an absent full_run key now means "partial", so a fixture that
            # wants to stand in for a full suite has to say so, exactly as the plugin does.
            "full_run": True,
            "narrowed_by": [],
            "outcomes": outcomes or {},
        }
    if report is not None:
        (root / "conformance" / "run-report.json").write_text(json.dumps(report, indent=2))

    (root / "WAIVERS.md").write_text(waivers)
    (root / "Makefile").write_text(
        makefile if makefile is not None else DEFAULT_MAKEFILE)

    if workflows is not None:
        wf_dir = root / ".github" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        for name, content in workflows.items():
            (wf_dir / name).write_text(content)

    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def run_check(root, phase=1, extra=()):
    # CONFORMANCE_RUN_REPORT=off so that nothing this subprocess might in turn
    # spawn can overwrite the run report of the pytest session we are inside.
    env = dict(os.environ, CONFORMANCE_RUN_REPORT="off")
    return subprocess.run(
        [sys.executable, str(CHECK), "--repo", str(root), "--phase", str(phase), *extra],
        capture_output=True, text=True, env=env,
    )


def matrix(root):
    return json.loads((pathlib.Path(root) / "conformance" / "matrix.json").read_text())


def status_of(root, req_id):
    return matrix(root)["requirements"][req_id]["status"]


DEFAULT_MAKEFILE = ".PHONY: test\ntest:\n\tpytest -q\n"

MARKED_TEST = (
    'import pytest\n\n\n@pytest.mark.req("{rid}")\ndef {name}():\n    assert True\n'
)


def _req(rid, **kw):
    r = {"id": rid, "phase": 1, "verify": "test",
         "source": "deploy-system-plan.md §4.5",
         "text": "A requirement that exists purely for this fixture."}
    r.update(kw)
    return r


# ── rule 1: outcomes come from the run, not the AST ──────────────────────────

def test_issue_r4_9_failing_marked_test_makes_the_gate_red(tmp_path):
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-FAILING")],
        tests_src={"tests/test_fixture.py": MARKED_TEST.format(rid="FIX-FAILING", name="test_a")},
        outcomes={"tests/test_fixture.py::test_a": "failed"},
    )
    res = run_check(root)
    assert res.returncode != 0, f"gate stayed green on a failing marked test:\n{res.stdout}"
    assert "FIX-FAILING" in res.stdout
    assert status_of(root, "FIX-FAILING") == "failed"


def test_issue_r4_9_uncollected_marker_is_red(tmp_path):
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-UNCOLLECTED")],
        tests_src={"tests/helpers_probe.py":
                   MARKED_TEST.format(rid="FIX-UNCOLLECTED", name="test_never_collected")},
        outcomes={"tests/test_other.py::test_unrelated": "passed"},
    )
    res = run_check(root)
    assert res.returncode != 0, f"gate stayed green on an uncollected marker:\n{res.stdout}"
    assert "not-collected" in res.stdout
    assert "tests/helpers_probe.py::test_never_collected" in res.stdout
    assert status_of(root, "FIX-UNCOLLECTED") == "not-collected"


# ── rule 2: skips prove nothing ──────────────────────────────────────────────

def test_issue_r4_9_skipped_only_requirement_is_not_verified(tmp_path):
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-SKIPPED")],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-SKIPPED", name="test_s")},
        outcomes={"tests/test_fixture.py::test_s": "skipped"},
    )
    res = run_check(root)
    assert res.returncode != 0, f"gate stayed green on a skipped-only req:\n{res.stdout}"
    assert status_of(root, "FIX-SKIPPED") == "skipped-only"

    # ...and an xfail is no better than a skip.
    root2 = write_repo(
        tmp_path / "xfail",
        reqs=[_req("FIX-SKIPPED")],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-SKIPPED", name="test_s")},
        outcomes={"tests/test_fixture.py::test_s": "xfailed"},
    )
    assert run_check(root2).returncode != 0
    assert status_of(root2, "FIX-SKIPPED") == "skipped-only"


# ── rule 1: report freshness ─────────────────────────────────────────────────

def test_issue_r4_9_stale_or_missing_run_report_is_red(tmp_path):
    stale = write_repo(
        tmp_path / "stale",
        reqs=[_req("FIX-FRESH")],
        tests_src={"tests/test_fixture.py": MARKED_TEST.format(rid="FIX-FRESH", name="test_a")},
        report={"schema_version": 1, "sha": "0" * 40, "generated_at": "2026-01-01T00:00:00Z",
                "outcomes": {"tests/test_fixture.py::test_a": "passed"}},
    )
    res = run_check(stale)
    assert res.returncode != 0, f"a stale run report was accepted as green:\n{res.stdout}"
    assert "run-report" in (res.stdout + res.stderr)
    assert "0000000000" in (res.stdout + res.stderr), "the stale sha must be named"

    absent = write_repo(
        tmp_path / "absent",
        reqs=[_req("FIX-FRESH")],
        tests_src={"tests/test_fixture.py": MARKED_TEST.format(rid="FIX-FRESH", name="test_a")},
        report=None,
    )
    res2 = run_check(absent)
    assert res2.returncode != 0, f"a missing run report was accepted as green:\n{res2.stdout}"
    assert "run-report" in (res2.stdout + res2.stderr)


def test_issue_r4_9_partial_run_report_is_red_without_a_wall_of_not_collected(tmp_path):
    """`pytest -k foo` then `make conformance` must fail once, clearly.

    Not one of the spec's nine: found while running this suite. Accepting a
    narrowed report would report every marker outside the selection as
    `not-collected`, burying any real finding under ~30 false ones.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-PARTIAL")],
        tests_src={"tests/test_fixture.py": MARKED_TEST.format(rid="FIX-PARTIAL", name="test_a")},
        report={"schema_version": 1, "sha": head_sha(),
                "tree": gates.tree_fingerprint(REPO),
                "generated_at": "2026-08-11T00:00:00Z", "pytest_exitstatus": 0,
                "full_run": False, "invocation_args": ["-q", "tests/test_other.py"],
                "outcomes": {"tests/test_other.py::test_unrelated": "passed"}},
    )
    res = run_check(root)
    assert res.returncode != 0, f"a partial run report was accepted:\n{res.stdout}"
    assert "run-report partial" in res.stdout
    assert "not-collected" not in res.stdout, (
        f"a partial report must fail once, not once per requirement:\n{res.stdout}")


# ── rule 3: verify: demo names its artifact, and the artifact has content ────

def test_issue_r4_9_empty_demo_artifact_is_red(tmp_path):
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-DEMO", verify="demo", demo=["conformance/demos/phase-1.md"])],
        files={"conformance/demos/phase-1.md": ""},
    )
    res = run_check(root)
    assert res.returncode != 0, f"an empty demo artifact passed the gate:\n{res.stdout}"
    assert "conformance/demos/phase-1.md" in res.stdout
    assert status_of(root, "FIX-DEMO") == "uncovered"

    # Round-5 F4: emptiness was `st_size == 0`, so a file someone had truncated to a
    # newline — or to the blank template they meant to fill in — recorded a demo that
    # was never performed. A demo artifact with no content is an empty demo artifact
    # whether or not the bytes are whitespace.
    for label, content in (("newline", "\n"),
                           ("spaces and tabs", "   \t\n  \n"),
                           ("crlf", "\r\n\r\n")):
        blank = write_repo(
            tmp_path / f"blank-{label.split()[0]}",
            reqs=[_req("FIX-DEMO", verify="demo", demo=["conformance/demos/phase-1.md"])],
            files={"conformance/demos/phase-1.md": content},
        )
        res_blank = run_check(blank)
        assert res_blank.returncode != 0, (
            f"a whitespace-only demo artifact ({label}, {content!r}) passed the gate:\n"
            f"{res_blank.stdout}")
        assert "conformance/demos/phase-1.md" in res_blank.stdout
        assert "empty" in res_blank.stdout, (
            f"the failure must say the artifact is empty:\n{res_blank.stdout}")
        assert status_of(blank, "FIX-DEMO") == "uncovered"

    # The directory form has the same hole: `any(f.stat().st_size > 0 ...)` was happy
    # with a directory of blank files.
    blank_dir = write_repo(
        tmp_path / "blank-dir",
        reqs=[_req("FIX-DEMO", verify="demo", demo=["conformance/demos/phase-1/"])],
        files={"conformance/demos/phase-1/.keep": "",
               "conformance/demos/phase-1/notes.md": "\n \n",
               "conformance/demos/phase-1/shot.txt": "\t\n"},
    )
    res_dir = run_check(blank_dir)
    assert res_dir.returncode != 0, (
        f"a demo directory holding only whitespace files passed the gate:\n{res_dir.stdout}")
    assert "conformance/demos/phase-1/" in res_dir.stdout
    assert status_of(blank_dir, "FIX-DEMO") == "uncovered"

    # ...and one file with real content in it is still enough.
    mixed = write_repo(
        tmp_path / "mixed",
        reqs=[_req("FIX-DEMO", verify="demo", demo=["conformance/demos/phase-1/"])],
        files={"conformance/demos/phase-1/.keep": "",
               "conformance/demos/phase-1/notes.md": "  \n",
               "conformance/demos/phase-1/shot.txt": "evidence\n"},
    )
    res_mixed = run_check(mixed)
    assert res_mixed.returncode == 0, (
        f"a demo directory with one real artifact was rejected:\n"
        f"{res_mixed.stdout}{res_mixed.stderr}")
    assert status_of(mixed, "FIX-DEMO") == "verified"


def test_issue_r4_9_demo_directory_form_is_accepted(tmp_path):
    ok = write_repo(
        tmp_path / "ok",
        reqs=[_req("FIX-DEMO", verify="demo",
                   demo=["conformance/demos/phase-1.md", "conformance/demos/phase-1/"])],
        files={"conformance/demos/phase-1.md": "# recorded\nsomething happened\n",
               "conformance/demos/phase-1/shot.txt": "evidence\n"},
    )
    res = run_check(ok)
    assert res.returncode == 0, (
        f"a populated demo directory was rejected:\n{res.stdout}{res.stderr}")
    assert status_of(ok, "FIX-DEMO") == "verified"

    empty = write_repo(
        tmp_path / "empty",
        reqs=[_req("FIX-DEMO", verify="demo", demo=["conformance/demos/phase-1/"])],
        files={"conformance/demos/phase-1/.keep": ""},
    )
    assert run_check(empty).returncode != 0, "a demo directory with no content passed"
    assert status_of(empty, "FIX-DEMO") == "uncovered"


# ── rule 4: checklist / static-gate must name a real gate ────────────────────

def test_issue_r4_9_checklist_req_without_a_named_gate_is_red(tmp_path):
    bare = write_repo(
        tmp_path / "bare",
        reqs=[_req("FIX-CHECKLIST", verify="checklist")],
    )
    res = run_check(bare)
    assert res.returncode != 0, f"a checklist req with no gate rode free:\n{res.stdout}"
    assert "FIX-CHECKLIST" in res.stdout
    assert status_of(bare, "FIX-CHECKLIST") == "uncovered"

    # A gate: naming a target that is not in the Makefile is just as red.
    bogus = write_repo(
        tmp_path / "bogus",
        reqs=[_req("FIX-CHECKLIST", verify="checklist", gate="no-such-target")],
        makefile=".PHONY: test\ntest:\n\tpytest -q\n",
    )
    res2 = run_check(bogus)
    assert res2.returncode != 0, "a gate naming a non-existent target passed"
    assert "no-such-target" in res2.stdout

    # A gate: naming a real Makefile target is accepted — and the target set is
    # read from the Makefile as it stands, never hard-coded. (Round-5 F3: "real"
    # now also means review-round runs it and CI invokes it; see
    # test_issue_f3_gate_must_be_a_review_round_target_that_ci_invokes.)
    real = write_repo(
        tmp_path / "real",
        reqs=[_req("FIX-CHECKLIST", verify="static-gate", gate="invented-later")],
        makefile=".PHONY: test invented-later review-round\ntest:\n\tpytest -q\n\n"
                 "invented-later:\n\t@echo gated\n\n"
                 "review-round: test invented-later\n\t@echo gates green\n",
        workflows={"push-checks.yml":
                   "name: push-checks\non: [push]\njobs:\n  gates:\n"
                   "    runs-on: ubuntu-latest\n    steps:\n"
                   "      - name: the new gate\n        run: make invented-later\n"},
    )
    res3 = run_check(real)
    assert res3.returncode == 0, (
        f"a real Makefile target was not recognised:\n{res3.stdout}{res3.stderr}")
    assert status_of(real, "FIX-CHECKLIST") == "verified"


# ── rule 5: retired ids ──────────────────────────────────────────────────────

def test_issue_r4_9_retired_id_in_a_marker_is_red(tmp_path):
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-OLD", status="retired",
                   retired_reason="superseded by FIX-NEW"),
              _req("FIX-NEW")],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-OLD", name="test_old")
                   + '\n\n@pytest.mark.req("FIX-NEW")\ndef test_new():\n    assert True\n'},
        outcomes={"tests/test_fixture.py::test_old": "passed",
                  "tests/test_fixture.py::test_new": "passed"},
    )
    res = run_check(root)
    assert res.returncode != 0, f"a marker on a retired id passed the gate:\n{res.stdout}"
    assert "FIX-OLD" in res.stdout
    assert "FIX-NEW" in res.stdout, "the replacement named by retired_reason must be printed"


# ── rule 6: text_hash ────────────────────────────────────────────────────────

PROBE_DOC = """# Probe plan doc

## A. A section

**A1. The pinned decision.** The body of the requirement's source section,
which is what text_hash covers.

**A2. Another decision.** Not part of A1's body.
"""


def test_issue_r4_9_text_hash_mismatch_is_red(tmp_path):
    files = {"docs/plan/probe-doc.md": PROBE_DOC}
    bad = write_repo(
        tmp_path / "bad",
        reqs=[_req("FIX-HASH", source="probe-doc.md §A1", text_hash="sha256:" + "0" * 64)],
        tests_src={"tests/test_fixture.py": MARKED_TEST.format(rid="FIX-HASH", name="test_h")},
        outcomes={"tests/test_fixture.py::test_h": "passed"},
        files=files,
    )
    res = run_check(bad)
    assert res.returncode != 0, f"a stale text_hash passed the gate:\n{res.stdout}{res.stderr}"
    assert "FIX-HASH" in res.stdout
    assert "tests/test_fixture.py::test_h" in res.stdout, (
        "re-review list must name the linked tests")

    # The recomputed hash for the same section must be accepted.
    good_hash = None
    for line in res.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("recomputed: sha256:"):
            good_hash = stripped.split("sha256:", 1)[1].split()[0]
    assert good_hash, f"check.py must print the recomputed hash so it can be pinned:\n{res.stdout}"

    good = write_repo(
        tmp_path / "good",
        reqs=[_req("FIX-HASH", source="probe-doc.md §A1", text_hash="sha256:" + good_hash)],
        tests_src={"tests/test_fixture.py": MARKED_TEST.format(rid="FIX-HASH", name="test_h")},
        outcomes={"tests/test_fixture.py::test_h": "passed"},
        files=files,
    )
    res2 = run_check(good)
    assert res2.returncode == 0, f"a correct text_hash was rejected:\n{res2.stdout}{res2.stderr}"


# ── F3: a gate: value must name a gate that actually runs ────────────────────

REAL_GATE_MAKEFILE = (
    ".PHONY: test real-gate noop-gate orphan-gate review-round\n"
    "test:\n\tpytest -q\n\n"
    "real-gate:\n\t@echo enforcing something\n\n"
    "noop-gate:\n\t@true\n\n"
    "orphan-gate:\n\t@echo enforcing something\n\n"
    "review-round: test real-gate orphan-gate\n\t@echo mechanical gates green\n"
)

GATE_WORKFLOW = """\
name: push-checks
on: [push]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - name: unit tests
        run: make test
      - name: real gate
        run: make real-gate
      - name: noop-gate
        run: echo "this step is named after the target and enforces nothing"
"""


def _gate_repo(root, gate, **kw):
    return write_repo(
        root,
        reqs=[_req("FIX-GATE", verify="static-gate", gate=gate)],
        makefile=REAL_GATE_MAKEFILE,
        workflows={"push-checks.yml": GATE_WORKFLOW},
        **kw,
    )


def test_issue_f3_gate_must_be_a_review_round_target_that_ci_invokes(tmp_path):
    """`gate:` resolved on a name alone, so any name would do (round-5 F3).

    R4-9 rule 4 accepted a `gate:` value that was *either* a Makefile target *or* the
    `name:` of a workflow step. Both halves are satisfiable by something that enforces
    nothing: `noop-gate:\\n\\t@true` is a Makefile target, and a step called `noop-gate`
    whose `run:` is an `echo` is a named workflow step. Either made a requirement
    `verified`.

    A gate is now: a Makefile target, listed as a prerequisite of `review-round` (so a
    review round runs it), invoked by at least one workflow step (so CI runs it too).
    Neither half is sufficient alone, and a workflow step *name* is no longer a gate
    value at all — a name is not an enforcement.
    """
    # (a) a real target that review-round does not run — a gate nobody executes.
    noop = _gate_repo(tmp_path / "noop", "noop-gate")
    res = run_check(noop)
    assert res.returncode != 0, (
        f"`noop-gate:\\n\\t@true` resolved as a gate on the strength of its name:\n"
        f"{res.stdout}{res.stderr}")
    assert "noop-gate" in res.stdout and "review-round" in res.stdout, (
        f"the failure must name the target and what it is missing:\n{res.stdout}")
    assert status_of(noop, "FIX-GATE") == "uncovered"

    # (b) a review-round prerequisite that no workflow invokes — CI does not run it.
    orphan = _gate_repo(tmp_path / "orphan", "orphan-gate")
    res2 = run_check(orphan)
    assert res2.returncode != 0, (
        f"a gate no workflow invokes was accepted:\n{res2.stdout}{res2.stderr}")
    assert "orphan-gate" in res2.stdout, res2.stdout
    assert status_of(orphan, "FIX-GATE") == "uncovered"

    # (c) a workflow step *name* is not a gate, however suggestive.
    step_name = _gate_repo(tmp_path / "stepname", "noop-gate", waivers="")
    assert run_check(step_name).returncode != 0, (
        "a workflow step named after the gate made the requirement verified")

    # (d) a target that is missing from the Makefile entirely.
    absent = _gate_repo(tmp_path / "absent", "no-such-target")
    res4 = run_check(absent)
    assert res4.returncode != 0
    assert "no-such-target" in res4.stdout

    # (e) the honest case: a review-round prerequisite that a workflow step invokes.
    good = _gate_repo(tmp_path / "good", "real-gate")
    res5 = run_check(good)
    assert res5.returncode == 0, (
        f"a real gate (review-round prerequisite, invoked by CI) was rejected:\n"
        f"{res5.stdout}{res5.stderr}")
    assert status_of(good, "FIX-GATE") == "verified"


def test_issue_f3_the_live_registry_gates_still_resolve():
    """Verify rather than assume: PROC-GENERATED-NOT-STALE's gate must survive the rule.

    `check-generated` is a `review-round` prerequisite and push-checks invokes it, so it
    should — but F3 changes what `gate:` means, and the point of the change is lost if
    the one requirement still carrying a gate quietly stops resolving.
    """
    registry = yaml.safe_load(
        (REPO / "conformance/requirements.yaml").read_text(encoding="utf-8"))
    gated = {r["id"]: r["gate"] for r in registry["requirements"] if r.get("gate")}
    assert gated, "no requirement names a gate any more — F3 removed the rule's only user"

    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    prereqs = set(
        re.search(r"^review-round:((?:[^\n]*\\\n)*[^\n]*)", makefile, re.M)
        .group(1).replace("\\", " ").split())
    invoked = set()
    wf_dir = REPO / ".github/workflows"
    for wf in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        invoked.update(re.findall(r"\bmake\s+(?:-[A-Za-z-]+\s+)*([A-Za-z0-9_.-]+)",
                                  wf.read_text(encoding="utf-8")))
    for req_id, gate in sorted(gated.items()):
        assert gate in prereqs, (
            f"{req_id}: gate {gate!r} is not a review-round prerequisite ({sorted(prereqs)})")
        assert gate in invoked, (
            f"{req_id}: gate {gate!r} is invoked by no workflow ({sorted(invoked)})")


# ── F6: markers inside a test class ─────────────────────────────────────────

CLASS_MARKED_TEST = '''\
import pytest


class TestCoverage:
    @pytest.mark.req("FIX-CLASS")
    def test_in_a_class(self):
        assert True

    class TestNested:
        @pytest.mark.req("FIX-NESTED")
        def test_deeper(self):
            assert True


@pytest.mark.req("FIX-MODULE")
def test_at_module_level():
    assert True
'''


def test_issue_f6_marked_tests_inside_a_class_are_matched_to_their_nodeid(tmp_path):
    """`path::func` never matches pytest's `path::Class::func` (round-5 F6).

    `collect_markers()` built its nodeid from the file and the function name with no
    class ancestry, so a marked method on a test class was reported `not-collected`
    however green it ran. Latent on this tree — every suite here is function-style — but
    it is an unfixable red for whoever writes the first class-based test: the marker is
    right, the test passes, and the gate says the marker is dead.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-CLASS"), _req("FIX-NESTED"), _req("FIX-MODULE")],
        tests_src={"tests/test_klass.py": CLASS_MARKED_TEST},
        outcomes={
            "tests/test_klass.py::TestCoverage::test_in_a_class": "passed",
            "tests/test_klass.py::TestCoverage::TestNested::test_deeper": "passed",
            "tests/test_klass.py::test_at_module_level": "passed",
        },
    )
    res = run_check(root)
    assert res.returncode == 0, (
        f"a passing marked test inside a class was reported as a dead marker:\n"
        f"{res.stdout}{res.stderr}")
    for req_id in ("FIX-CLASS", "FIX-NESTED", "FIX-MODULE"):
        assert status_of(root, req_id) == "verified", (
            f"{req_id} is {status_of(root, req_id)}, not verified:\n{res.stdout}")

    entry = matrix(root)["requirements"]["FIX-CLASS"]
    assert entry["tests"] == ["tests/test_klass.py::TestCoverage::test_in_a_class"], (
        f"the AST nodeid must carry the class ancestry pytest reports: {entry['tests']}")

    # And the detector it doubles as still works: a class-based marker pytest never
    # collected is still not-collected, not silently forgiven.
    dead = write_repo(
        tmp_path / "dead",
        reqs=[_req("FIX-CLASS")],
        tests_src={"tests/test_klass.py":
                   'import pytest\n\n\nclass TestCoverage:\n'
                   '    @pytest.mark.req("FIX-CLASS")\n'
                   '    def test_in_a_class(self):\n        assert True\n'},
        outcomes={"tests/test_klass.py::TestCoverage::test_renamed": "passed"},
    )
    res2 = run_check(dead)
    assert res2.returncode != 0, f"a dead class-based marker passed:\n{res2.stdout}"
    assert status_of(dead, "FIX-CLASS") == "not-collected"


# ── F5: an unpinned or unresolvable text_hash must be visible ───────────────

def test_issue_f5_unpinned_or_unresolvable_text_hash_warns(tmp_path):
    """No pin, no output: the check silently covered whatever it happened to cover.

    Round-5 F5. `text_hash` only ran for requirements that carried one, so the five
    registry entries with no pin — and the sources that cannot be resolved to a section
    at all — produced not one line of output. A reader of a green run could not tell the
    difference between "this requirement's source text is pinned and unchanged" and
    "nothing checks this requirement's source text". Unpinned is a warning, on the same
    channel as the demo-artifact fallback: visible, not fatal.
    """
    files = {"docs/plan/probe-doc.md": PROBE_DOC}
    root = write_repo(
        tmp_path,
        reqs=[
            _req("FIX-PINNED", source="probe-doc.md §A1", text_hash="sha256:" + "0" * 64),
            _req("FIX-UNPINNED", source="probe-doc.md §A1"),
            _req("FIX-NODOC", source="nowhere-at-all.md §A1"),
            _req("FIX-NOSECTION", source="probe-doc.md §Z9"),
        ],
        tests_src={"tests/test_fixture.py":
                   "".join(MARKED_TEST.format(rid=rid, name=f"test_{n}")
                           for n, rid in enumerate(
                               ["FIX-PINNED", "FIX-UNPINNED", "FIX-NODOC", "FIX-NOSECTION"]))},
        outcomes={f"tests/test_fixture.py::test_{n}": "passed" for n in range(4)},
        files=files,
    )
    # The pinned-but-wrong hash is the pre-existing hard failure; --print-text-hashes
    # would drown here, so re-pin it and look only at the warnings.
    res = run_check(root)
    warnings = [line for line in res.stdout.splitlines() if line.startswith("warning:")]
    blob = "\n".join(warnings)

    assert any("FIX-UNPINNED" in w for w in warnings), (
        f"a requirement with no text_hash produced no warning:\n{res.stdout}")
    assert any("FIX-NODOC" in w for w in warnings), (
        f"a requirement whose source doc does not exist produced no warning:\n{res.stdout}")
    assert any("FIX-NOSECTION" in w for w in warnings), (
        f"a requirement whose source section cannot be anchored produced no warning:\n"
        f"{res.stdout}")
    assert not any("FIX-PINNED" in w for w in warnings), (
        f"a pinned, resolvable requirement must stay quiet:\n{blob}")
    for req_id in ("FIX-NODOC", "FIX-NOSECTION"):
        assert any(req_id in w and "source" in w for w in warnings), (
            f"the warning for {req_id} must say the source is what could not be "
            f"resolved:\n{blob}")

    # Warnings are warnings: with every pin correct, an unpinned req does not go red.
    good = write_repo(
        tmp_path / "good",
        reqs=[_req("FIX-UNPINNED", source="probe-doc.md §A1")],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-UNPINNED", name="test_u")},
        outcomes={"tests/test_fixture.py::test_u": "passed"},
        files=files,
    )
    res2 = run_check(good)
    assert res2.returncode == 0, (
        f"an unpinned text_hash was treated as a failure, not a warning:\n"
        f"{res2.stdout}{res2.stderr}")
    assert any(line.startswith("warning:") and "FIX-UNPINNED" in line
               for line in res2.stdout.splitlines()), res2.stdout


# ── F7: what counts as a full run ───────────────────────────────────────────

def test_issue_f7_run_report_without_a_full_run_key_is_red(tmp_path):
    """An absent `full_run` key was read as a full run (round-5 F7).

    `if report.get("full_run") is False:` — so a report from a writer that predates the
    key, or one hand-assembled by anything at all, was accepted as covering the whole
    suite. Absent is not a claim of completeness; it is the absence of one, and the whole
    point of rule 1 is that the gate does not infer good news it was not told.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-NOFLAG")],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-NOFLAG", name="test_a")},
        report={"schema_version": 1, "sha": head_sha(),
                "tree": gates.tree_fingerprint(REPO),
                "generated_at": "2026-08-11T00:00:00Z", "pytest_exitstatus": 0,
                "outcomes": {"tests/test_fixture.py::test_a": "passed"}},
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"a run report with no full_run key was accepted as a full run:\n{res.stdout}")
    assert "run-report" in res.stdout and "full_run" in res.stdout, (
        f"the failure must name the missing key so it is fixable:\n{res.stdout}")
    assert "not-collected" not in res.stdout, (
        f"an unusable report must fail once, not once per requirement:\n{res.stdout}")

    # A report that says so is still accepted.
    ok = write_repo(
        tmp_path / "ok",
        reqs=[_req("FIX-NOFLAG")],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-NOFLAG", name="test_a")},
        outcomes={"tests/test_fixture.py::test_a": "passed"},
    )
    assert run_check(ok).returncode == 0


# The plugin under test lives in tests/conftest.py. Driving it means running a real
# pytest session, so these spawn one in a scratch rootdir whose conftest re-exports the
# repo's hooks — CONFORMANCE_RUN_REPORT points the child at a tmp file, so it can never
# touch the report of the session we are inside.
CHILD_CONFTEST = '''\
import importlib.util, pathlib, sys

sys.path.insert(0, {repo!r})
spec = importlib.util.spec_from_file_location(
    "hub_conftest", pathlib.Path({repo!r}) / "tests" / "conftest.py")
hub_conftest = importlib.util.module_from_spec(spec)
sys.modules["hub_conftest"] = hub_conftest
spec.loader.exec_module(hub_conftest)

pytest_runtest_logreport = hub_conftest.pytest_runtest_logreport
pytest_sessionfinish = hub_conftest.pytest_sessionfinish
pytest_deselected = hub_conftest.pytest_deselected
'''

CHILD_TESTS = '''\
def test_alpha():
    assert True


def test_beta():
    assert True


def test_gamma():
    assert True
'''


def run_child_pytest(tmp_path, *args, addopts=None):
    """Run a pytest session in a scratch dir under the repo's run-report plugin."""
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "conftest.py").write_text(CHILD_CONFTEST.format(repo=str(REPO)))
    (tmp_path / "test_child.py").write_text(CHILD_TESTS)
    report = tmp_path / "child-report.json"
    env = dict(os.environ, CONFORMANCE_RUN_REPORT=str(report), PYTHONPATH=str(REPO))
    env.pop("PYTEST_ADDOPTS", None)
    if addopts is not None:
        env["PYTEST_ADDOPTS"] = addopts
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=tmp_path, capture_output=True, text=True, env=env,
    )
    assert report.exists(), f"the plugin wrote no report:\n{proc.stdout}{proc.stderr}"
    return json.loads(report.read_text()), proc


def test_issue_f7_pytest_addopts_cannot_forge_a_full_run(tmp_path):
    """`full_run` was derived from argv, which is not where pytest's options come from.

    Round-5 F7, reproduced by the reviewer: `PYTEST_ADDOPTS="-k test_smoke" pytest -q`
    wrote `full_run: True` with 5 of 250 outcomes — a report describing 2% of the suite,
    stamped as complete, which the gate then trusted. The flag has to come from the
    options pytest actually parsed, not from the words on the command line.
    """
    full, proc = run_child_pytest(tmp_path / "full")
    assert full["full_run"] is True, (
        f"an unnarrowed run was not recognised as full:\n{proc.stdout}{proc.stderr}")
    assert len(full["outcomes"]) == 3, full["outcomes"]

    narrowed, proc2 = run_child_pytest(tmp_path / "k", addopts="-k alpha")
    assert len(narrowed["outcomes"]) == 1, (
        f"the fixture did not actually narrow the run:\n{proc2.stdout}")
    assert narrowed["full_run"] is False, (
        f'PYTEST_ADDOPTS="-k alpha" produced full_run={narrowed["full_run"]!r} over '
        f'{len(narrowed["outcomes"])} of 3 tests:\n{proc2.stdout}')

    for label, addopts in (("-m", "-m acceptance"),
                           ("--deselect", "--deselect test_child.py::test_beta"),
                           ("-x", "-x"),
                           ("--maxfail", "--maxfail=1")):
        report, child = run_child_pytest(tmp_path / f"opt{abs(hash(label))}",
                                         addopts=addopts)
        assert report["full_run"] is False, (
            f"PYTEST_ADDOPTS={addopts!r} ({label}) still claimed a full run:\n"
            f"{child.stdout}")

    # A positional target on the command line was already caught; keep it caught.
    positional, _ = run_child_pytest(tmp_path / "pos", "test_child.py")
    assert positional["full_run"] is False


def test_issue_r7_registry_text_matches_what_the_declaration_tests_prove():
    """R7 registry correction. `SCAN-DECLARED-TEST-MATERIAL`'s `text:` described declared
    findings as moving to a "third, non-blocking bucket". Round 7's veto made that false
    — they block until the operator accepts the claim — and a registry entry that states
    the pre-veto behaviour is the requirement asserting the very thing the round removed.

    The `text:` is the sentence a reader is handed instead of the code; when it and the
    tests disagree, the tests are what ships. Checked here rather than by eye because the
    registry is not otherwise read by any test."""
    registry = yaml.safe_load(
        (REPO / "conformance/requirements.yaml").read_text(encoding="utf-8"))
    req = {r["id"]: r for r in registry["requirements"]}["SCAN-DECLARED-TEST-MATERIAL"]

    assert "non-blocking" not in req["text"], req["text"]
    assert "third bucket" in req["text"] or "third," in req["text"], req["text"]
    assert "accept" in req["text"], (
        "the requirement does not say that the downgrade waits on the operator's "
        "acceptance, which is the whole of the round-7 correction")
    # And the source citation has to reach the spec that RULED it, or the pinned
    # text_hash watches a section that says the opposite of the requirement.
    assert "spec-r7-enforce-declaration-acceptance.md" in req["source"], req["source"]

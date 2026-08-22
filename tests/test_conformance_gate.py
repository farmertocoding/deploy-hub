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
import pytest
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
            elif isinstance(v, (int, float)):
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


def run_child_pytest(tmp_path, *args, addopts=None, tests=None):
    """Run a pytest session in a scratch dir under the repo's run-report plugin."""
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "conftest.py").write_text(CHILD_CONFTEST.format(repo=str(REPO)))
    (tmp_path / "test_child.py").write_text(tests if tests is not None else CHILD_TESTS)
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
    assert narrowed["outcomes"]["test_child.py::test_alpha"] == "passed"
    assert narrowed["outcomes"]["test_child.py::test_beta"] == "skipped"
    assert narrowed["outcomes"]["test_child.py::test_gamma"] == "skipped"
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


CHILD_T2_TESTS = '''\
import pytest


def test_t1_unit():
    assert True


@pytest.mark.t2
@pytest.mark.req("FIX-T2-LIVE")
def test_t2_live():
    assert True
'''


def test_t2_deselect_is_skipped_and_full_run(tmp_path):
    """`make test` is `pytest -q -m "not t2 and not t3"`. Deselected T2 nodeids
    must be skipped.

    Uncollected req markers are red regardless of phase (R4-9). Recording the
    T2 tests as skipped keeps SEC-68/SEC-B1 out of `not-collected`, and the
    default T1 filter is not a narrowed run.
    """
    report, proc = run_child_pytest(
        tmp_path / "not-t2", addopts='-m "not t2 and not t3"', tests=CHILD_T2_TESTS)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report["outcomes"]["test_child.py::test_t1_unit"] == "passed"
    assert report["outcomes"]["test_child.py::test_t2_live"] == "skipped", (
        f"T2 nodeid missing or not skipped (would be not-collected):\n{report}"
    )
    assert report["full_run"] is True, (
        f"-m 'not t2 and not t3' must still be a full T1 gating run:\n"
        f"full_run={report['full_run']!r} narrowed_by={report.get('narrowed_by')}\n"
        f"{proc.stdout}{proc.stderr}"
    )


def test_issue_r4_9_t2_skipped_sibling_does_not_uncollect(tmp_path):
    """T1 pass + T2 skip on the same req is verified, not not-collected (SEC-68)."""
    t2_src = (
        "import pytest\n\n\n"
        "@pytest.mark.t2\n"
        '@pytest.mark.req("FIX-HOSTKEY")\n'
        "def test_live():\n"
        "    assert True\n"
    )
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-HOSTKEY")],
        tests_src={
            "tests/test_unit.py": MARKED_TEST.format(rid="FIX-HOSTKEY", name="test_unit"),
            "tests/test_live.py": t2_src,
        },
        outcomes={
            "tests/test_unit.py::test_unit": "passed",
            "tests/test_live.py::test_live": "skipped",
        },
    )
    res = run_check(root)
    assert res.returncode == 0, res.stdout
    assert status_of(root, "FIX-HOSTKEY") == "verified"
    assert "not-collected" not in res.stdout


def test_issue_r4_9_t2_only_skipped_is_skipped_only_not_uncollected(tmp_path):
    """A T2-only req recorded as skipped is skipped-only, never not-collected (SEC-B1)."""
    t2_src = (
        "import pytest\n\n\n"
        "@pytest.mark.t2\n"
        '@pytest.mark.req("FIX-OFFHUB")\n'
        "def test_live():\n"
        "    assert True\n"
    )
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-OFFHUB")],
        tests_src={"tests/test_live.py": t2_src},
        outcomes={"tests/test_live.py::test_live": "skipped"},
    )
    res = run_check(root)
    assert status_of(root, "FIX-OFFHUB") == "skipped-only"
    assert "not-collected" not in res.stdout


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


T3_MARKED_TEST = (
    "import pytest\n\n"
    "from tests.harness.multipass import multipass_available\n\n\n"
    "@pytest.mark.t3\n"
    "@pytest.mark.skipif(not multipass_available(), reason='multipass is not available')\n"
    '@pytest.mark.req("{rid}")\n'
    "def {name}():\n"
    "    assert True\n"
)

CHILD_T3_TESTS = '''\
import pytest


def test_t1_unit():
    assert True


@pytest.mark.t2
def test_t2_live():
    assert True


@pytest.mark.t3
def test_t3_live():
    assert True
'''


def test_phase_accepts_two_point_five(tmp_path):
    """`--phase 2.5` must be a legal gate, and write_repo must emit 2.5 as YAML number.

    What would make this fail: argparse `--phase type=int` (rejects 2.5), schema
    `phase must be int`, or write_repo quoting floats so the registry stores a string.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-PHASE", phase=2.5)],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-PHASE", name="test_a")},
        outcomes={"tests/test_fixture.py::test_a": "passed"},
    )
    yaml_text = (root / "conformance" / "requirements.yaml").read_text()
    assert re.search(r"^    phase: 2\.5\s*$", yaml_text, re.M), (
        f"write_repo must emit YAML float 2.5 as a number, not a quoted string:\n"
        f"{yaml_text}"
    )
    res = run_check(root, phase=2.5)
    assert res.returncode == 0, (
        f"--phase 2.5 was rejected:\n{res.stdout}{res.stderr}"
    )
    header = matrix(root)
    assert header["phase"] == 2.5
    assert header["requirements"]["FIX-PHASE"]["due"] is True
    assert status_of(root, "FIX-PHASE") == "verified"

    res2 = run_check(root, phase=2)
    assert res2.returncode == 0, res2.stdout + res2.stderr
    assert matrix(root)["requirements"]["FIX-PHASE"]["due"] is False, (
        "a phase-2.5 req must not be due at --phase 2"
    )


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_t3_tier_req_not_verified_by_t1_sibling(tmp_path):
    """A T1 pass must not verify a `tier: t3` req (D-024). Carrying the id on T1 is red.

    What would make this fail: evaluate_test_req treating any passed sibling as
    verified, including an unmarked T1 test next to a skipped T3 test.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T3-ONLY", tier="t3")],
        tests_src={
            "tests/test_unit.py": MARKED_TEST.format(
                rid="FIX-T3-ONLY", name="test_unit"),
            "tests/test_live.py": T3_MARKED_TEST.format(
                rid="FIX-T3-ONLY", name="test_live"),
        },
        outcomes={
            "tests/test_unit.py::test_unit": "passed",
            "tests/test_live.py::test_live": "skipped",
        },
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"a T1 sibling pass verified a tier:t3 req:\n{res.stdout}"
    )
    assert status_of(root, "FIX-T3-ONLY") != "verified"
    assert "wrong marker" in res.stdout, (
        f"a T1 test carrying a tier:t3 id must be named as wrong marker:\n{res.stdout}"
    )


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_t3_tier_req_skipped_only_when_all_t3_skipped(tmp_path):
    """Every `@pytest.mark.t3` outcome skipped/xfailed is skipped-only, never verified.

    What would make this fail: counting skip/xfail as a pass for `tier: t3`.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T3-SKIP", tier="t3")],
        tests_src={"tests/test_live.py":
                   T3_MARKED_TEST.format(rid="FIX-T3-SKIP", name="test_live")},
        outcomes={"tests/test_live.py::test_live": "skipped"},
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"a skipped-only tier:t3 req went green:\n{res.stdout}"
    )
    assert status_of(root, "FIX-T3-SKIP") == "skipped-only"

    xfail = write_repo(
        tmp_path / "xfail",
        reqs=[_req("FIX-T3-SKIP", tier="t3")],
        tests_src={"tests/test_live.py":
                   T3_MARKED_TEST.format(rid="FIX-T3-SKIP", name="test_live")},
        outcomes={"tests/test_live.py::test_live": "xfailed"},
    )
    assert run_check(xfail).returncode != 0
    assert status_of(xfail, "FIX-T3-SKIP") == "skipped-only"


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_t3_tier_req_verified_only_after_t3_pass(tmp_path):
    """`tier: t3` is verified only when ≥1 `@pytest.mark.t3` test passed and none failed.

    What would make this fail: refusing a genuine t3 pass, or verifying from a
    non-t3 nodeid.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T3-PASS", tier="t3")],
        tests_src={"tests/test_live.py":
                   T3_MARKED_TEST.format(rid="FIX-T3-PASS", name="test_live")},
        outcomes={"tests/test_live.py::test_live": "passed"},
    )
    res = run_check(root)
    assert res.returncode == 0, (
        f"a passed @pytest.mark.t3 test did not verify a tier:t3 req:\n"
        f"{res.stdout}{res.stderr}"
    )
    assert status_of(root, "FIX-T3-PASS") == "verified"


T2_MARKED_TEST = (
    "import pytest\n\n\n"
    "@pytest.mark.t2\n"
    '@pytest.mark.req("{rid}")\n'
    "def {name}():\n"
    "    assert True\n"
)


def test_t2_tier_req_not_verified_by_t1_sibling(tmp_path):
    """A T1 pass must not verify a `tier: t2` req (panel F1 ruling, same teeth
    as D-024's t3 rule). Carrying the id on a non-t2 test is red (wrong marker).

    What would make this fail: marker enforcement special-cased to t3 only, so
    a T1 sibling greens HARNESS-T3-TOXIPROXY without ever touching docker.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T2-ONLY", tier="t2")],
        tests_src={
            "tests/test_unit.py": MARKED_TEST.format(
                rid="FIX-T2-ONLY", name="test_unit"),
            "tests/test_live.py": T2_MARKED_TEST.format(
                rid="FIX-T2-ONLY", name="test_live"),
        },
        outcomes={
            "tests/test_unit.py::test_unit": "passed",
            "tests/test_live.py::test_live": "skipped",
        },
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"a T1 sibling pass verified a tier:t2 req:\n{res.stdout}"
    )
    assert status_of(root, "FIX-T2-ONLY") != "verified"
    assert "wrong marker" in res.stdout, (
        f"a T1 test carrying a tier:t2 id must be named as wrong marker:\n{res.stdout}"
    )


def test_t2_tier_wrong_marker_is_red_even_when_tier_excluded(tmp_path):
    """`--exclude-tier t2` drops the req from the due set, but a wrong marker
    is a defect, not accepted risk — red regardless of the exclusion.

    What would make this fail: gating the wrong-marker check on `due`.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T2-WRONG", tier="t2")],
        tests_src={"tests/test_unit.py":
                   MARKED_TEST.format(rid="FIX-T2-WRONG", name="test_unit")},
        outcomes={"tests/test_unit.py::test_unit": "passed"},
    )
    res = run_check(root, extra=("--exclude-tier", "t2"))
    assert res.returncode != 0, (
        f"--exclude-tier t2 forgave a wrong marker:\n{res.stdout}"
    )
    assert "wrong marker" in res.stdout


def test_t2_tier_req_skipped_only_when_all_t2_skipped(tmp_path):
    """Every `@pytest.mark.t2` outcome skipped/xfailed is skipped-only, never
    verified — a docker-less host does not earn the live green.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T2-SKIP", tier="t2")],
        tests_src={"tests/test_live.py":
                   T2_MARKED_TEST.format(rid="FIX-T2-SKIP", name="test_live")},
        outcomes={"tests/test_live.py::test_live": "skipped"},
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"a skipped-only tier:t2 req went green:\n{res.stdout}"
    )
    assert status_of(root, "FIX-T2-SKIP") == "skipped-only"

    xfail = write_repo(
        tmp_path / "xfail",
        reqs=[_req("FIX-T2-SKIP", tier="t2")],
        tests_src={"tests/test_live.py":
                   T2_MARKED_TEST.format(rid="FIX-T2-SKIP", name="test_live")},
        outcomes={"tests/test_live.py::test_live": "xfailed"},
    )
    assert run_check(xfail).returncode != 0
    assert status_of(xfail, "FIX-T2-SKIP") == "skipped-only"


def test_t2_tier_req_verified_only_after_t2_pass(tmp_path):
    """`tier: t2` is verified when ≥1 `@pytest.mark.t2` test passed, none failed."""
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T2-PASS", tier="t2")],
        tests_src={"tests/test_live.py":
                   T2_MARKED_TEST.format(rid="FIX-T2-PASS", name="test_live")},
        outcomes={"tests/test_live.py::test_live": "passed"},
    )
    res = run_check(root)
    assert res.returncode == 0, (
        f"a passed @pytest.mark.t2 test did not verify a tier:t2 req:\n"
        f"{res.stdout}{res.stderr}"
    )
    assert status_of(root, "FIX-T2-PASS") == "verified"


def test_exclude_tier_t2_omits_t2_reqs_from_due_set(tmp_path):
    """`--exclude-tier t2` drops `tier: t2` reqs from the due set, so
    review-round's T1 report grades them excluded instead of skipped-only red
    (make review-round red-by-construction was panel F1).
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T2-EXCL", tier="t2"), _req("FIX-T1-DUE")],
        tests_src={
            "tests/test_t1.py": MARKED_TEST.format(rid="FIX-T1-DUE", name="test_t1"),
            "tests/test_live.py": T2_MARKED_TEST.format(
                rid="FIX-T2-EXCL", name="test_live"),
        },
        outcomes={
            "tests/test_t1.py::test_t1": "passed",
            "tests/test_live.py::test_live": "skipped",
        },
    )
    res_all = run_check(root)
    assert res_all.returncode != 0, (
        f"a skipped-only tier:t2 req was not due at --phase 1:\n{res_all.stdout}"
    )
    assert status_of(root, "FIX-T2-EXCL") == "skipped-only"

    res = run_check(root, extra=("--exclude-tier", "t2"))
    assert res.returncode == 0, (
        f"--exclude-tier t2 still failed the gate:\n{res.stdout}{res.stderr}"
    )
    assert matrix(root)["requirements"]["FIX-T2-EXCL"]["due"] is False
    assert status_of(root, "FIX-T1-DUE") == "verified"


def test_exclude_tier_t3_omits_t3_reqs_from_due_set(tmp_path):
    """`--exclude-tier t3` drops `tier: t3` reqs from the due set (review-round).

    What would make this fail: exclude-tier ignored, so an uncovered t3 req still
    fails the gate the same way a T1 uncovered req does.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T3-EXCL", tier="t3"), _req("FIX-T1-DUE")],
        tests_src={"tests/test_t1.py":
                   MARKED_TEST.format(rid="FIX-T1-DUE", name="test_t1")},
        outcomes={"tests/test_t1.py::test_t1": "passed"},
    )
    res_all = run_check(root)
    assert res_all.returncode != 0, (
        f"an uncovered tier:t3 req was not due at --phase 1:\n{res_all.stdout}"
    )
    assert status_of(root, "FIX-T3-EXCL") == "uncovered"
    assert matrix(root)["requirements"]["FIX-T3-EXCL"]["due"] is True

    res = run_check(root, extra=("--exclude-tier", "t3"))
    assert res.returncode == 0, (
        f"--exclude-tier t3 still failed the gate:\n{res.stdout}{res.stderr}"
    )
    assert matrix(root)["requirements"]["FIX-T3-EXCL"]["due"] is False
    assert matrix(root)["requirements"]["FIX-T1-DUE"]["due"] is True
    assert status_of(root, "FIX-T1-DUE") == "verified"


def test_t1_default_markexpr_deselects_t3_and_stays_full_run(tmp_path):
    """`make test` is `-m "not t2 and not t3"`. T3 nodeids are skipped; full_run stays.

    What would make this fail: T3 deselection counted as narrowing, or the T3
    nodeid omitted from the report (not-collected).
    """
    report, proc = run_child_pytest(
        tmp_path / "not-t2-t3",
        addopts='-m "not t2 and not t3"',
        tests=CHILD_T3_TESTS,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report["outcomes"]["test_child.py::test_t1_unit"] == "passed"
    assert report["outcomes"]["test_child.py::test_t2_live"] == "skipped", report
    assert report["outcomes"]["test_child.py::test_t3_live"] == "skipped", (
        f"T3 nodeid missing or not skipped (would be not-collected):\n{report}"
    )
    assert report["full_run"] is True, (
        f'-m "not t2 and not t3" must still be a full T1 gating run:\n'
        f"full_run={report['full_run']!r} narrowed_by={report.get('narrowed_by')}\n"
        f"{proc.stdout}{proc.stderr}"
    )


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_t3_tier_req_verified_by_module_pytestmark(tmp_path):
    """Module/class `pytestmark = pytest.mark.t3` (or a list) is an inherited t3 mark.

    What would make this fail: collect_mark_nodeids reading only `@pytest.mark.t3`
    decorators, so a passed test that is t3 only via pytestmark is wrong-marker
    and `make conformance-2.5` stays red after a real t3 pass
    (`tests/test_hub_test_target.py` shape).
    """
    list_src = (
        "import pytest\n\n"
        "from tests.harness.multipass import multipass_available\n\n"
        "pytestmark = [pytest.mark.t3, pytest.mark.skipif("
        "not multipass_available(), reason='x')]\n\n"
        '@pytest.mark.req("FIX-T3-PYTESTMARK")\n'
        "def test_live():\n"
        "    assert True\n"
    )
    root = write_repo(
        tmp_path / "list",
        reqs=[_req("FIX-T3-PYTESTMARK", tier="t3")],
        tests_src={"tests/test_live.py": list_src},
        outcomes={"tests/test_live.py::test_live": "passed"},
    )
    res = run_check(root)
    assert res.returncode == 0, (
        f"a passed test with module pytestmark=[t3, ...] did not verify:\n"
        f"{res.stdout}{res.stderr}"
    )
    assert status_of(root, "FIX-T3-PYTESTMARK") == "verified"
    assert "wrong marker" not in res.stdout

    # A bare (non-list) module pytestmark carrying t3; the derived host gate
    # rides the function decorator — mixed scopes must combine (I1).
    bare = write_repo(
        tmp_path / "bare",
        reqs=[_req("FIX-T3-BARE", tier="t3")],
        tests_src={"tests/test_live.py":
                   "import pytest\n\n"
                   "from tests.harness.multipass import multipass_available\n\n"
                   "pytestmark = pytest.mark.t3\n\n"
                   "@pytest.mark.skipif(not multipass_available(), reason='x')\n"
                   '@pytest.mark.req("FIX-T3-BARE")\n'
                   "def test_live():\n"
                   "    assert True\n"},
        outcomes={"tests/test_live.py::test_live": "passed"},
    )
    res_bare = run_check(bare)
    assert res_bare.returncode == 0, res_bare.stdout + res_bare.stderr
    assert status_of(bare, "FIX-T3-BARE") == "verified"

    klass = write_repo(
        tmp_path / "class",
        reqs=[_req("FIX-T3-CLASS", tier="t3")],
        tests_src={"tests/test_live.py":
                   "import pytest\n\n"
                   "from tests.harness.multipass import multipass_available\n\n"
                   "class TestLive:\n"
                   "    pytestmark = pytest.mark.t3\n\n"
                   "    @pytest.mark.skipif(not multipass_available(), reason='x')\n"
                   "    @pytest.mark.req(\"FIX-T3-CLASS\")\n"
                   "    def test_live(self):\n"
                   "        assert True\n"},
        outcomes={"tests/test_live.py::TestLive::test_live": "passed"},
    )
    res_cls = run_check(klass)
    assert res_cls.returncode == 0, res_cls.stdout + res_cls.stderr
    assert status_of(klass, "FIX-T3-CLASS") == "verified"


# ── Phase 3 Task 0: due set, D-039 conversions, t3 host-gate integrity (I1) ──

# The 18 phase-3 ids design note §3 adds in Task 0 (the other two of the 20 are
# the phase-4 clause-split ids below). Spelled here so a registry edit that
# drops or rephases one goes red with its name.
PHASE_3_NEW_IDS = {
    "SEC-B2-NO-TOKEN-ON-TARGET",
    "UX-F5-T2-T3-FRICTION",
    "DNS-CF-PRODUCT-ADAPTER",
    "DNS-CF-T3-LIVE",
    "TLS-B2-ORIGIN-CERT-PUSH",
    "TLS-V9-CERT-THRESHOLDS",
    "ALERT-M3-PAGER-AUTH",
    "ALERT-RECOVERY-NOTICE",
    "ALERT-DELIVERY-BEHAVIORS",
    "ALERT-PAGER-DRILL",
    "MON-UPTIME-EVENTS",
    "MON-TRAFFIC-INGEST",
    "MON-C7-RETENTION",
    "UX-F1-IA-NAV",
    "UX-F4-FAILURE-IMPACT",
    "MAP-96-GRAPH-V1",
    "PROV-E6-ADOPT-TEMP-SUBDOMAIN",
    "P3-DNS-MONITOR-DEMO",
}

# Registered now, due at phase 4: the unbuilt clause of each split (D-035/D-040).
PHASE_4_SPLIT_IDS = {"TLS-B2-HUB-DNS01-UNPROXIED", "SEC-F5-T1-HARDWARE-TOUCH"}


def _live_registry():
    data = yaml.safe_load(
        (REPO / "conformance/requirements.yaml").read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["requirements"]}


def test_phase_3_due_set_includes_every_phase_3_id(tmp_path):
    """Every Task-0 phase-3 id exists at phase 3 with its exact fields, and
    check.py grades a phase-3 req as due at `--phase 3`.

    What would make this fail: a missing/rephased id, DNS-CF-T3-LIVE without
    tier:t3, TLS-B2-ORIGIN-CERT-PUSH without tier:t2, or P3-DNS-MONITOR-DEMO
    not naming its two demo artifacts.
    """
    reg = _live_registry()
    missing = sorted(PHASE_3_NEW_IDS - set(reg))
    assert missing == [], f"phase-3 ids missing from the registry: {missing}"
    wrong_phase = sorted(
        rid for rid in PHASE_3_NEW_IDS if reg[rid]["phase"] != 3)
    assert wrong_phase == [], (
        f"phase-3 ids not registered at phase 3: "
        f"{[(rid, reg[rid]['phase']) for rid in wrong_phase]}")

    assert reg["DNS-CF-T3-LIVE"].get("tier") == "t3", (
        "DNS-CF-T3-LIVE must carry tier: t3 — a T1 sibling never proves the live leg")
    assert reg["TLS-B2-ORIGIN-CERT-PUSH"].get("tier") == "t2", (
        "TLS-B2-ORIGIN-CERT-PUSH must carry tier: t2")
    demo = reg["P3-DNS-MONITOR-DEMO"]
    assert demo["verify"] == "demo"
    assert demo.get("demo") == [
        "conformance/demos/phase-3.md", "conformance/demos/phase-3/"], (
        f"P3-DNS-MONITOR-DEMO must name both demo artifacts: {demo.get('demo')}")

    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-P3-DUE", phase=3)],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-P3-DUE", name="test_a")},
        outcomes={"tests/test_fixture.py::test_a": "passed"},
    )
    res = run_check(root, phase=3)
    assert res.returncode == 0, res.stdout + res.stderr
    assert matrix(root)["requirements"]["FIX-P3-DUE"]["due"] is True, (
        "a phase-3 req must be due at --phase 3")


def test_phase_4_ids_are_not_due_at_phase_3(tmp_path):
    """The two clause-split phase-4 ids are registered but not due at phase 3.

    What would make this fail: SEC-F5-T1-HARDWARE-TOUCH or
    TLS-B2-HUB-DNS01-UNPROXIED registered at phase 3 (which would demand
    proofs of clauses the phase deliberately does not build — D-035/D-040),
    or check.py grading a phase-4 req as due at --phase 3.
    """
    reg = _live_registry()
    for rid in sorted(PHASE_4_SPLIT_IDS):
        assert rid in reg, f"{rid} is not in the registry"
        assert reg[rid]["phase"] == 4, (
            f"{rid} must be registered at phase 4, got {reg[rid]['phase']}")

    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-P3-DUE", phase=3), _req("FIX-P4-LATER", phase=4)],
        tests_src={"tests/test_fixture.py":
                   MARKED_TEST.format(rid="FIX-P3-DUE", name="test_a")},
        outcomes={"tests/test_fixture.py::test_a": "passed"},
    )
    res = run_check(root, phase=3)
    assert res.returncode == 0, (
        f"an uncovered phase-4 req failed the --phase 3 gate:\n{res.stdout}")
    assert matrix(root)["requirements"]["FIX-P4-LATER"]["due"] is False
    assert matrix(root)["requirements"]["FIX-P3-DUE"]["due"] is True


def test_verify_test_conversion_requires_a_marked_test(tmp_path):
    """D-039: MON-DEADMAN-EXTERNAL and PROV-J7-COMPOSE-AWARE-ADOPT convert
    `verify: checklist` → `verify: test` — neither has an honest gate to name
    and R4-9 forbids inventing one. The conversion has teeth: a verify:test
    phase-3 req with no marked test is uncovered red at --phase 3, where a
    checklist req naming some Makefile target could ride green.
    """
    reg = _live_registry()
    for rid in ("MON-DEADMAN-EXTERNAL", "PROV-J7-COMPOSE-AWARE-ADOPT"):
        assert reg[rid]["verify"] == "test", (
            f"{rid} must be verify: test (D-039), got {reg[rid]['verify']!r}")
        assert "gate" not in reg[rid], (
            f"{rid} converted to verify: test must not keep a gate: key")

    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-CONVERTED", phase=3)],
        outcomes={},
    )
    res = run_check(root, phase=3)
    assert res.returncode != 0, (
        f"a verify:test req with no marked test passed the phase-3 gate:\n{res.stdout}")
    assert status_of(root, "FIX-CONVERTED") == "uncovered"
    assert "no @pytest.mark.req marker" in res.stdout


UNGATED_T3_TEST = (
    "import pytest\n\n\n"
    "@pytest.mark.t3\n"
    "def test_live():\n"
    "    assert True\n"
)


def test_self_declared_t3_mark_without_host_gate_is_red(tmp_path):
    """2.5 panel I1: a `@pytest.mark.t3` test with no skipif host gate is red.

    A self-declared t3 mark with no gate collects everywhere — on a host
    without Multipass it fails or hangs instead of skipping, and the mark
    stops meaning "runs only on the T3 host of record".
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-DUE")],
        tests_src={
            "tests/test_ok.py": MARKED_TEST.format(rid="FIX-DUE", name="test_a"),
            "tests/test_ungated.py": UNGATED_T3_TEST,
        },
        outcomes={"tests/test_ok.py::test_a": "passed",
                  "tests/test_ungated.py::test_live": "skipped"},
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"an ungated @pytest.mark.t3 test passed the gate:\n{res.stdout}")
    assert "tests/test_ungated.py::test_live" in res.stdout, (
        f"the failure must name the ungated nodeid:\n{res.stdout}")
    assert "multipass_available" in res.stdout, (
        f"the failure must say what the gate has to derive from:\n{res.stdout}")


def test_t3_gate_not_derived_from_multipass_available_is_red(tmp_path):
    """A skipif on any condition but `multipass_available()` is not a host gate.

    2.5 panel I1: `skipif(False, ...)` is vacuous, an env var is operator
    opinion, and a module constant is a value nobody recomputes — none of them
    is the host truth. The gate must derive from `multipass_available()`.
    """
    cases = {
        "bare-false": "pytest.mark.skipif(False, reason='vacuous')",
        "env-var": ("pytest.mark.skipif('HAVE_MULTIPASS' not in os.environ, "
                    "reason='env opinion')"),
        "module-constant": "pytest.mark.skipif(not HAVE_MULTIPASS, reason='constant')",
    }
    for label, gate in cases.items():
        src = (
            "import os\n\n"
            "import pytest\n\n"
            "HAVE_MULTIPASS = False\n\n"
            f"pytestmark = [pytest.mark.t3, {gate}]\n\n\n"
            "def test_live():\n"
            "    assert True\n"
        )
        root = write_repo(
            tmp_path / label,
            reqs=[_req("FIX-DUE")],
            tests_src={
                "tests/test_ok.py": MARKED_TEST.format(rid="FIX-DUE", name="test_a"),
                "tests/test_wrong_gate.py": src,
            },
            outcomes={"tests/test_ok.py::test_a": "passed",
                      "tests/test_wrong_gate.py::test_live": "skipped"},
        )
        res = run_check(root)
        assert res.returncode != 0, (
            f"{label}: a t3 gate not derived from multipass_available() passed:\n"
            f"{res.stdout}")
        assert "tests/test_wrong_gate.py::test_live" in res.stdout, (label, res.stdout)
        assert "multipass_available" in res.stdout, (label, res.stdout)


def test_host_gated_t3_mark_is_accepted(tmp_path):
    """The honest shapes stay green: a decorator skipif derived from
    `multipass_available()`, and the same gate carried by module pytestmark.
    """
    decorator_src = (
        "import pytest\n\n"
        "from tests.harness.multipass import multipass_available\n\n\n"
        "@pytest.mark.t3\n"
        "@pytest.mark.skipif(not multipass_available(), "
        "reason='multipass is not available')\n"
        "def test_live():\n"
        "    assert True\n"
    )
    pytestmark_src = (
        "import pytest\n\n"
        "from tests.harness.multipass import multipass_available\n\n"
        "pytestmark = [\n"
        "    pytest.mark.t3,\n"
        "    pytest.mark.skipif(not multipass_available(), "
        "reason='multipass is not available'),\n"
        "]\n\n\n"
        "def test_live():\n"
        "    assert True\n"
    )
    for label, src in (("decorator", decorator_src), ("pytestmark", pytestmark_src)):
        root = write_repo(
            tmp_path / label,
            reqs=[_req("FIX-DUE")],
            tests_src={
                "tests/test_ok.py": MARKED_TEST.format(rid="FIX-DUE", name="test_a"),
                "tests/test_gated.py": src,
            },
            outcomes={"tests/test_ok.py::test_a": "passed",
                      "tests/test_gated.py::test_live": "skipped"},
        )
        res = run_check(root)
        assert res.returncode == 0, (
            f"{label}: a multipass_available()-gated t3 mark was refused:\n"
            f"{res.stdout}{res.stderr}")

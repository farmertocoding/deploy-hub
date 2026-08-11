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
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CHECK = REPO / "conformance" / "check.py"


def head_sha():
    out = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def write_repo(root, *, reqs, tests_src=None, report="auto", waivers="",
               makefile=None, files=None, outcomes=None):
    """Build a throwaway repo tree for check.py to run against.

    reqs      : list of dicts -> conformance/requirements.yaml
    tests_src : {"tests/test_x.py": "<source>"}
    report    : dict written verbatim, None to write no file at all, or "auto"
                to build a fresh report from `outcomes` with the real HEAD sha.
    files     : {"path": "content"} arbitrary extra files (demos, docs, ...)
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
            "generated_at": "2026-08-11T00:00:00Z",
            "outcomes": outcomes or {},
        }
    if report is not None:
        (root / "conformance" / "run-report.json").write_text(json.dumps(report, indent=2))

    (root / "WAIVERS.md").write_text(waivers)
    (root / "Makefile").write_text(
        makefile if makefile is not None else DEFAULT_MAKEFILE)

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
    # read from the Makefile as it stands, never hard-coded.
    real = write_repo(
        tmp_path / "real",
        reqs=[_req("FIX-CHECKLIST", verify="static-gate", gate="invented-later")],
        makefile=".PHONY: test invented-later\ntest:\n\tpytest -q\n\n"
                 "invented-later:\n\t@echo gated\n",
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

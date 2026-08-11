#!/usr/bin/env python3
"""conformance-check (review3 §Q2/§Q3/§Q4/§Q5; rebuilt for R4-9).

Round 4 (SPEC-gate-integrity §3) found that this script measured *marker
presence*: `status = "covered" if tests else "uncovered"`, where `tests` came
from an AST walk.  A marked test could fail, be skipped, or live in a file
pytest never collects and the gate still exited 0, while `build-process.md` §2-④
claimed it required every phase-due requirement to be *verified* (its tests
green in the gating CI run).

What it does now, by SPEC-gate-integrity §3.2 rule number:

  rule 1  Outcomes come from `conformance/run-report.json`, written by the
          pytest plugin in tests/conftest.py.  The report is mandatory and its
          `sha` must equal `git rev-parse HEAD`; absent or stale is red.  The
          AST walk survives as the source of the `not-collected` check.
  rule 2  skipped/xfailed outcomes never count toward `verified`.
  rule 3  `verify: demo` reqs name their artifacts in a `demo:` key; each named
          path must exist and be non-empty (a directory must hold >=1 non-empty
          file).  Falling back to `conformance/demos/phase-N.md` warns.
  rule 4  `verify: checklist` / `static-gate` reqs name their enforcing gate in
          a `gate:` key; the gate must be a real target in the Makefile or a
          named step in a workflow, else the req is `uncovered`.
  rule 5  A marker on a `status: retired` id is red, naming the replacement
          from `retired_reason`.
  rule 6  `text_hash:` pins sha256 of the req's source section body in
          docs/plan/; a mismatch is red and prints the linked test ids.
  rule 7  matrix.json carries the real status plus a `sha` / `verified_at`
          header.

Status vocabulary (§3.2):
  verified      >=1 collected marked test ran and passed, none failed   -> pass
  failed        >=1 marked test ran and did not pass                    -> red
  uncovered     no marked test / no artifact / no gate      -> red unless waived
  not-collected marker exists in tests/** but pytest never collected it -> red
  skipped-only  every marked test was skipped or xfailed    -> red unless waived

`failed` and `not-collected` are red regardless of phase and regardless of a
waiver: a failing test and a dead marker are defects, not accepted risk.

Exits non-zero on any violation.  Emits conformance/matrix.json.
"""
import argparse
import ast
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys

import yaml

# The checkout that owns this script.  `--repo` may point the *content* checks
# at another tree (the gate's own tests do exactly that), but HEAD is always
# this checkout's HEAD — that is the sha a run report has to match.
SELF_REPO = pathlib.Path(__file__).resolve().parent.parent

ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
TEXT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VERIFY_KINDS = {"test", "demo", "checklist", "static-gate"}
ALLOWED_KEYS = {
    "id", "phase", "verify", "source", "text", "kind", "status", "retired_reason",
    # R4-9 additions (§3.2 rules 3, 4, 6)
    "demo", "gate", "text_hash",
}
PASSING_OUTCOMES = {"passed", "xpassed"}
INCONCLUSIVE_OUTCOMES = {"skipped", "xfailed"}


# ── registry ────────────────────────────────────────────────────────────────

def load_registry(root):
    """Load + schema-validate (conformance/schema.json is the JSON-Schema statement
    of these rules; validated here dependency-free so CI needs no extra package)."""
    data = yaml.safe_load((root / "conformance/requirements.yaml").read_text())
    problems = []
    seen = set()
    for r in data.get("requirements", []):
        rid = r.get("id", "<missing id>")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            problems.append(f"bad id: {rid!r}")
        if rid in seen:
            problems.append(f"duplicate id: {rid}")
        seen.add(rid)
        missing = {"id", "phase", "verify", "source", "text"} - set(r)
        if missing:
            problems.append(f"{rid}: missing keys {sorted(missing)}")
        if not isinstance(r.get("phase"), int) or not 0 <= r.get("phase", -1) <= 7:
            problems.append(f"{rid}: phase must be int 0-7")
        if r.get("verify") not in VERIFY_KINDS:
            problems.append(f"{rid}: verify must be one of {sorted(VERIFY_KINDS)}")
        extra = set(r) - ALLOWED_KEYS
        if extra:
            problems.append(f"{rid}: unknown keys {sorted(extra)}")
        demo = r.get("demo")
        if demo is not None and not (
            isinstance(demo, str)
            or (isinstance(demo, list) and demo and all(isinstance(d, str) for d in demo))
        ):
            problems.append(f"{rid}: demo must be a path or a non-empty list of paths")
        if "gate" in r and not (isinstance(r["gate"], str) and r["gate"].strip()):
            problems.append(f"{rid}: gate must be a non-empty string")
        th = r.get("text_hash")
        if th is not None and not (isinstance(th, str) and TEXT_HASH_RE.match(th)):
            problems.append(f"{rid}: text_hash must look like sha256:<64 hex>")
    if problems:
        print("registry schema validation FAILED:")
        for pr in problems:
            print(f"  - {pr}")
        sys.exit(1)
    return {r["id"]: r for r in data["requirements"]}


# ── AST marker walk (kept: it is the not-collected detector, rule 1) ────────

def _req_ids_from_decorators(node):
    """String args of @pytest.mark.req(...) decorators on a function def."""
    ids = []
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        # match pytest.mark.req / mark.req
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
        if parts and parts[0] == "req" and "mark" in parts:
            for arg in dec.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    ids.append(arg.value)
    return ids


def collect_markers(root):
    """Map req id -> [test node ids] by AST walk (round-1 finding: a text grep
    counted markers in comments/docstrings/dead code as coverage, and silently
    ignored malformed ids). Only decorators attached to test functions count;
    ANY string arg is captured so typos are flagged, not skipped."""
    found = {}
    for py in sorted((root / "tests").rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test"):
                    continue
                for req_id in _req_ids_from_decorators(node):
                    found.setdefault(req_id, []).append(
                        f"{py.relative_to(root)}::{node.name}")
    return found


# ── run report (rule 1) ─────────────────────────────────────────────────────

def git_head():
    try:
        out = subprocess.run(
            ["git", "-C", str(SELF_REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def load_run_report(path):
    """Return (report, [problems]).  A missing, malformed or stale report is a
    hard failure: a stale report must never be mistaken for a green run."""
    rel = path
    if not path.exists():
        return None, [
            f"run-report missing: {rel} — the conformance gate reads test outcomes "
            f"from the run report written by pytest. Run the suite first "
            f"(`make test`), then re-run the gate."
        ]
    try:
        report = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"run-report unreadable: {rel} ({exc})"]
    if not isinstance(report.get("outcomes"), dict):
        return None, [f"run-report malformed: {rel} has no 'outcomes' object"]
    head = git_head()
    sha = report.get("sha") or "<none>"
    if not head:
        return None, [f"run-report freshness cannot be checked: git rev-parse HEAD failed ({rel})"]
    if sha != head:
        return None, [
            f"run-report stale: {rel} was written at sha {sha}, HEAD is {head} — "
            f"re-run the suite (`make test`) so outcomes describe this tree."
        ]
    # A report from `pytest -k ...`, a single file, or a run cut short by -x
    # describes a subset. Refusing it here is one honest line; accepting it turns
    # every marker outside the subset into a bogus `not-collected`.
    if report.get("full_run") is False:
        return None, [
            f"run-report partial: {rel} came from a narrowed pytest run "
            f"(args: {report.get('invocation_args')}, exitstatus "
            f"{report.get('pytest_exitstatus')}). The conformance gate needs a "
            f"full-suite report — run `make test`, then re-run the gate."
        ]
    return report, []


def outcomes_for(ast_nodeid, outcomes):
    """Outcomes for one AST-discovered nodeid, including its parametrised cases."""
    hits = {}
    for nodeid, outcome in outcomes.items():
        if nodeid == ast_nodeid or nodeid.startswith(ast_nodeid + "["):
            hits[nodeid] = outcome
    return hits


# ── demo artifacts (rule 3) ─────────────────────────────────────────────────

def check_demo_paths(root, paths):
    """Return list of problem strings for the named demo artifacts."""
    problems = []
    for rel in paths:
        p = (root / rel.rstrip("/"))
        if not p.exists():
            problems.append(f"demo artifact missing: {rel}")
        elif p.is_dir():
            files = [f for f in p.rglob("*") if f.is_file()]
            if not files:
                problems.append(f"demo artifact directory is empty: {rel}")
            elif not any(f.stat().st_size > 0 for f in files):
                problems.append(f"demo artifact directory holds only empty files: {rel}")
        elif p.stat().st_size == 0:
            problems.append(f"demo artifact is empty (0 bytes): {rel}")
    return problems


# ── gates (rule 4) ──────────────────────────────────────────────────────────

def makefile_targets(root):
    """Targets declared in the Makefile, read from the file as it stands.

    Deliberately not a hard-coded list: a concurrently-added target (log-scrub)
    must be recognised the moment it lands."""
    mk = root / "Makefile"
    if not mk.exists():
        return set()
    targets = set()
    for line in mk.read_text().splitlines():
        if not line or line.startswith(("\t", " ", "#")):
            continue
        m = re.match(r"^([^:#=]+):(?!=)", line)
        if not m:
            continue
        for name in m.group(1).split():
            if not name.startswith("."):  # .PHONY / .DEFAULT_GOAL are not gates
                targets.add(name)
    return targets


def workflow_step_names(root):
    """`name:` of every step in every workflow (a gate may be a CI step)."""
    names = set()
    wf_dir = root / ".github/workflows"
    if not wf_dir.is_dir():
        return names
    for wf in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(wf.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        for job in (doc.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("name"), str):
                    names.add(step["name"])
    return names


# ── text_hash (rule 6) ──────────────────────────────────────────────────────

# Only the frozen build copies under docs/ are hashable: docs/plan/README.md is
# explicit that the text_hash discipline rides those copies, and a doc that is
# not checked in there cannot be pinned (see the four UNRESOLVED sources listed
# by --print-text-hashes).
DOC_ROOTS = ("docs/plan", "docs")
BOLD_LEAD = re.compile(r"^\*\*([A-Za-z]?[A-Za-z0-9]*[0-9](?:\.[0-9]+)*)[.)\s]")


def _find_doc(root, source):
    m = re.search(r"([\w./-]+\.md)", source)
    if not m:
        return None, None
    ref = m.group(1)
    # Only the primary citation counts: `A.md §R3 / review3 §V1` is section R3 of
    # A.md, not section V1 of some other doc.
    rest = source[m.end():].split("/")[0].strip()
    name = pathlib.PurePosixPath(ref).name
    for base in DOC_ROOTS:
        for cand in ((root / base / name), (root / base / ref)):
            if cand.is_file():
                return cand, rest
    return None, rest


def _anchor_of(rest):
    if not rest:
        return None
    m = re.search(r"§\s*([A-Za-z]?[\w.]*[\w])", rest)
    if m:
        return m.group(1).rstrip(".")
    m = re.match(r"([A-Za-z]?[\w.]*[\w])", rest)
    return m.group(1).rstrip(".") if m else None


def source_section_body(root, source):
    """Resolve `<doc>.md §<anchor>` to the text of that section.

    Two section shapes exist in the frozen plan copies: a markdown heading
    (`## 4.5 Validation`) and a bold-lead paragraph (`**A1. Decision.** ...`).
    Returns (docpath, body) or (docpath|None, None) when it cannot be resolved.
    """
    doc, rest = _find_doc(root, source)
    if doc is None:
        return None, None
    anchor = _anchor_of(rest)
    if not anchor:
        return doc, None
    lines = doc.read_text(encoding="utf-8").splitlines()
    esc = re.escape(anchor)
    bold_re = re.compile(rf"^\*\*{esc}[.)\s]")
    head_re = re.compile(rf"^(#{{1,6}})\s*§?\s*{esc}[.)\s:]")
    head_ref_re = re.compile(rf"^(#{{1,6}})\s.*§\s*{esc}\b")

    start, level, kind = None, None, None
    for i, line in enumerate(lines):
        if bold_re.match(line):
            start, kind = i, "bold"
            break
        m = head_re.match(line) or head_ref_re.match(line)
        if m:
            start, level, kind = i, len(m.group(1)), "head"
            break
    if start is None:
        return doc, None

    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if kind == "bold":
            if BOLD_LEAD.match(line) or line.startswith("#") or line.strip() == "---":
                end = j
                break
        else:
            m = re.match(r"^(#{1,6})\s", line)
            if m and len(m.group(1)) <= level:
                end = j
                break
    body = "\n".join(ln.rstrip() for ln in lines[start:end]).strip()
    return doc, (body or None)


def text_hash_of(body):
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


# ── waivers ─────────────────────────────────────────────────────────────────

def waived_ids(root):
    """Only structured `WAIVED: <id> — reason (date)` lines count (round-1 finding:
    a bare word-boundary regex let prose mentioning an id silently waive it)."""
    waivers = root / "WAIVERS.md"
    if not waivers.exists():
        return set()
    out = set()
    for line in waivers.read_text().splitlines():
        m = re.match(r"^WAIVED:\s*(\S+)\s+—\s+\S.*\(\d{4}-\d{2}-\d{2}\)", line.strip())
        if m:
            out.add(m.group(1))
    return out


# ── main ────────────────────────────────────────────────────────────────────

def evaluate_test_req(req_id, ast_ids, outcomes):
    """Status + detail lines for a `verify: test` requirement (rules 1 and 2)."""
    details = []
    if not ast_ids:
        return "uncovered", [f"{req_id} (test) has no @pytest.mark.req marker"], {}

    seen, missing, failed, passed, inconclusive = {}, [], [], [], []
    for ast_id in ast_ids:
        hits = outcomes_for(ast_id, outcomes)
        if not hits:
            missing.append(ast_id)
            continue
        seen.update(hits)
        for nodeid, outcome in sorted(hits.items()):
            if outcome in PASSING_OUTCOMES:
                passed.append(nodeid)
            elif outcome in INCONCLUSIVE_OUTCOMES:
                inconclusive.append(f"{nodeid} ({outcome})")
            else:
                failed.append(f"{nodeid} ({outcome})")

    if failed:
        details.append(f"{req_id} (test) failed: " + ", ".join(failed))
        status = "failed"
    elif missing:
        details.append(
            f"{req_id} (test) not-collected: marker present in tests/** but pytest "
            f"collected no such nodeid: " + ", ".join(missing))
        status = "not-collected"
    elif passed:
        status = "verified"
    else:
        details.append(
            f"{req_id} (test) skipped-only: every marked test was skipped/xfailed: "
            + ", ".join(inconclusive))
        status = "skipped-only"
    # A dead marker alongside real coverage is still a dead marker.
    if missing and status == "failed":
        details.append(
            f"{req_id} (test) also has uncollected markers: " + ", ".join(missing))
    return status, details, seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, default=None)
    parser.add_argument("--repo", default=None,
                        help="tree to evaluate (default: this checkout)")
    parser.add_argument("--run-report", default=None,
                        help="pytest run report "
                             "(default: <repo>/conformance/run-report.json)")
    parser.add_argument("--matrix-out", default=None,
                        help="path for matrix.json (default: <repo>/conformance/matrix.json)")
    parser.add_argument("--print-text-hashes", action="store_true",
                        help="print the recomputed text_hash for every requirement and exit; "
                             "pinning a new value into the registry stays a human edit")
    args = parser.parse_args()

    root = pathlib.Path(args.repo).resolve() if args.repo else SELF_REPO
    report_path = (pathlib.Path(args.run_report) if args.run_report
                   else root / "conformance/run-report.json")
    matrix_path = (pathlib.Path(args.matrix_out) if args.matrix_out
                   else root / "conformance/matrix.json")

    registry = load_registry(root)

    if args.print_text_hashes:
        for req_id, req in registry.items():
            doc, body = source_section_body(root, req["source"])
            if body is None:
                print(f"{req_id}: UNRESOLVED source {req['source']!r} "
                      f"(doc={'-' if doc is None else doc.relative_to(root)})")
            else:
                print(f"{req_id}: {text_hash_of(body)}  # {doc.relative_to(root)} "
                      f"— {req['source']}")
        return 0

    markers = collect_markers(root)
    waived = waived_ids(root)
    failures = []
    warnings = []

    report, report_problems = load_run_report(report_path)
    if report_problems:
        print("conformance-check FAILED:")
        for p in report_problems:
            print(f"  - {p}")
        return 1
    outcomes = report["outcomes"]

    # Markers must resolve to a live registry id (rule 5 covers the retired case).
    for req_id, tests in sorted(markers.items()):
        req = registry.get(req_id)
        if req is None:
            failures.append(f"unknown req id in tests: {req_id} ({tests})")
        elif req.get("status") == "retired":
            reason = req.get("retired_reason")
            tail = f" — {reason}" if reason else " (no retired_reason given)"
            failures.append(
                f"marker on retired req {req_id}{tail}; update or delete: {tests}")

    targets = makefile_targets(root)
    step_names = workflow_step_names(root)

    matrix = {}
    for req_id, req in registry.items():
        phase = req["phase"]
        kind = req["verify"]
        ast_ids = markers.get(req_id, [])
        due = (args.phase is None or phase <= args.phase) and req.get("status") != "retired"
        entry = {"phase": phase, "verify": kind, "tests": ast_ids, "due": due}
        details = []

        if req.get("status") == "retired":
            status = "retired"
        elif kind == "test":
            status, details, seen = evaluate_test_req(req_id, ast_ids, outcomes)
            entry["outcomes"] = seen
        elif kind == "demo":
            paths = req.get("demo")
            if paths is None:
                paths = [f"conformance/demos/phase-{phase}.md"]
                warnings.append(
                    f"{req_id} (demo) has no demo: key — falling back to "
                    f"{paths[0]}; name the artifact(s) in the registry")
            elif isinstance(paths, str):
                paths = [paths]
            entry["demo"] = list(paths)
            problems = check_demo_paths(root, paths)
            details = [f"{req_id} (demo) {p}" for p in problems]
            status = "uncovered" if problems else "verified"
        else:  # checklist / static-gate
            gate = req.get("gate")
            entry["gate"] = gate
            if not gate:
                status = "uncovered"
                details = [f"{req_id} ({kind}) names no gate: — add a gate: key naming the "
                           f"Makefile target or CI step that enforces it, or waive it"]
            elif gate in targets or gate in step_names:
                status = "verified"
            else:
                status = "uncovered"
                details = [f"{req_id} ({kind}) gate {gate!r} is neither a Makefile target "
                           f"nor a named workflow step"]

        entry["status"] = status
        entry["notes"] = details
        matrix[req_id] = entry

        # `failed` and `not-collected` are defects, not accepted risk: red whatever
        # the phase and whatever WAIVERS.md says.
        if status in {"failed", "not-collected"}:
            failures.extend(details)
        elif due and status in {"uncovered", "skipped-only"} and req_id not in waived:
            failures.extend(details or [f"{req_id} ({kind}) {status} and not waived"])

        # rule 6 — text_hash freshness.
        pinned = req.get("text_hash")
        if pinned:
            doc, body = source_section_body(root, req["source"])
            if body is None:
                failures.append(
                    f"{req_id}: text_hash pinned but its source section could not be "
                    f"resolved: {req['source']!r}")
            else:
                actual = text_hash_of(body)
                entry["text_hash_actual"] = actual
                if actual != pinned:
                    failures.append(
                        f"{req_id}: text_hash stale — source {req['source']!r} "
                        f"({doc.relative_to(root)}) changed since it was pinned")
                    failures.append(f"    recomputed: {actual}")
                    failures.append(f"    pinned:     {pinned}")
                    failures.append(
                        "    re-review these tests: "
                        + (", ".join(ast_ids) if ast_ids else "(none linked)"))

    header = {
        "schema_version": 2,
        "sha": report.get("sha", ""),
        "verified_at": report.get("generated_at", ""),
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase": args.phase,
        "requirements": dict(sorted(matrix.items())),
    }
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.write_text(json.dumps(header, indent=2) + "\n")

    # Flake-quarantine cap (PROC-FLAKE-CAP): red at >5 quarantined tests.
    # Decorator-anchored (round-1 finding: string mentions counted toward the cap).
    flaky_re = re.compile(r"^\s*@pytest\.mark\.flaky_quarantine\b", re.M)
    count = sum(len(flaky_re.findall(py.read_text(encoding="utf-8")))
                for py in (root / "tests").rglob("*.py"))
    if count > 5:
        failures.append(f"flake quarantine cap exceeded: {count} > 5")

    for w in warnings:
        print(f"warning: {w}")

    if failures:
        print("conformance-check FAILED:")
        for f in failures:
            print(f"  - {f}" if not f.startswith("    ") else f)
        return 1

    counts = {}
    for entry in matrix.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"conformance-check ok — {len(registry)} reqs ({summary}); "
          f"run report {report.get('sha', '')[:12]} @ {report.get('generated_at', '')}; "
          f"matrix.json written")
    return 0


if __name__ == "__main__":
    sys.exit(main())

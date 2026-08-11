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
          path must exist and hold content (a directory must hold >=1 file with
          content).  Round-5 F4: "content" means non-whitespace, not non-zero
          bytes — a record truncated to a newline recorded nothing.  Falling
          back to `conformance/demos/phase-N.md` warns.
  rule 4  `verify: checklist` / `static-gate` reqs name their enforcing gate in
          a `gate:` key.  Round-5 F3 tightened what resolves: the gate must be a
          Makefile *target*, listed as a prerequisite of `review-round` (a review
          round runs it) and invoked by at least one workflow step (CI runs it).
          A workflow step *name* is no longer a gate value — `noop-gate:\t@true`
          and a step called `noop-gate` that only echoes both used to pass.
  rule 5  A marker on a `status: retired` id is red, naming the replacement
          from `retired_reason`.
  rule 6  `text_hash:` pins sha256 of the req's source section body in
          docs/plan/; a mismatch is red and prints the linked test ids.
          Round-5 F5: a req with *no* pin, or whose `source:` will not resolve
          to a section, warns — silence used to be indistinguishable from a
          check that had run and found nothing wrong.
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
import sys

import yaml

# The checkout that owns this script.  `--repo` may point the *content* checks
# at another tree (the gate's own tests do exactly that), but HEAD is always
# this checkout's HEAD — that is the sha a run report has to match.
SELF_REPO = pathlib.Path(__file__).resolve().parent.parent

# Makefile/workflow/WAIVERS parsing and the working-tree fingerprint live in
# gates.py, imported by this script and by tests/test_gate_parity.py alike (N1).
# Round 5 left two implementations of "does CI invoke this gate", of differing
# strictness, which is the R4-8 defect reproduced inside the machinery built to
# kill it: a step carrying `continue-on-error: true` was neutered to the parity
# test and a working gate to this script.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gates  # noqa: E402 — the path insert above is its prerequisite

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


def _collect_from(node, relpath, classes, found):
    """Recurse module/class bodies, recording `path::Class::...::func` nodeids.

    Round-5 F6: this used `ast.walk` and built `path::func`, with no class ancestry,
    while pytest reports `path::Class::func` — so a marked method on a test class was
    always `not-collected`, however green it ran. Descent stops at a function body:
    pytest does not collect defs nested inside a test, so a marker there is not a
    nodeid either way."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            _collect_from(child, relpath, classes + [child.name], found)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not child.name.startswith("test"):
                continue
            nodeid = "::".join([relpath, *classes, child.name])
            for req_id in _req_ids_from_decorators(child):
                found.setdefault(req_id, []).append(nodeid)


def collect_markers(root):
    """Map req id -> [test node ids] by AST walk (round-1 finding: a text grep
    counted markers in comments/docstrings/dead code as coverage, and silently
    ignored malformed ids). Only decorators attached to test functions count;
    ANY string arg is captured so typos are flagged, not skipped."""
    found = {}
    for py in sorted((root / "tests").rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        _collect_from(tree, str(py.relative_to(root)), [], found)
    return found


# ── run report (rule 1) ─────────────────────────────────────────────────────

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
    head = gates.git_head(SELF_REPO)
    sha = report.get("sha") or "<none>"
    if not head:
        return None, [f"run-report freshness cannot be checked: git rev-parse HEAD failed ({rel})"]
    if sha != head:
        return None, [
            f"run-report stale: {rel} was written at sha {sha}, HEAD is {head} — "
            f"re-run the suite (`make test`) so outcomes describe this tree."
        ]
    # Round-5 deferral: HEAD alone does not move when a file is edited, so the report
    # stayed "fresh" across any uncommitted change made after the run.  That is exactly
    # the dangerous window — watch a requirement go red, edit the code, re-run the gate
    # (which reads the *working tree*) and it grades a tree the tests never saw.
    tree = gates.tree_fingerprint(SELF_REPO)
    if not tree:
        return None, [
            f"run-report freshness cannot be checked: the working-tree fingerprint of "
            f"{SELF_REPO} could not be computed (is this a git checkout?) ({rel})"
        ]
    if "tree" not in report:
        return None, [
            f"run-report has no 'tree' fingerprint: {rel} predates the working-tree "
            f"binding, and an absent binding is not a claim that the tree is unchanged "
            f"— it is no claim at all. Re-run the suite (`make test`)."
        ]
    if report["tree"] != tree:
        return None, [
            f"run-report stale: {rel} describes a different working tree "
            f"(report {report['tree'][:19]}…, tree now {tree[:19]}…) — files have "
            f"changed since the suite ran, so its outcomes do not describe the tree "
            f"this gate is grading. Re-run the suite (`make test`), then re-run the gate."
        ]
    # A report from `pytest -k ...`, a single file, or a run cut short by -x
    # describes a subset. Refusing it here is one honest line; accepting it turns
    # every marker outside the subset into a bogus `not-collected`.
    #
    # Round-5 F7: the test was `is False`, so an *absent* full_run key read as a full
    # run. Absent is not a claim of completeness, it is the absence of one — and this
    # gate exists precisely so that it stops inferring good news nobody told it.
    if report.get("full_run") is not True:
        missing = "full_run" not in report
        why = ("has no 'full_run' key, so it makes no claim to cover the suite"
               if missing else
               f"came from a narrowed pytest run (narrowed by: "
               f"{report.get('narrowed_by') or 'unrecorded'})")
        return None, [
            f"run-report partial: {rel} {why} "
            f"(args: {report.get('invocation_args')}, exitstatus "
            f"{report.get('pytest_exitstatus')}). The conformance gate needs a "
            f"full-suite report with full_run: true — run `make test`, then re-run "
            f"the gate."
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

def _has_content(path):
    """True if the file holds anything but whitespace.

    Round-5 F4: emptiness used to be `st_size == 0`, so a demo record truncated to a
    newline — or a blank template nobody filled in — counted as a recorded demo. Read as
    bytes: these artifacts include PNGs, and `bytes.strip()` needs no decoding."""
    try:
        return bool(path.read_bytes().strip())
    except OSError:
        return False


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
            elif not any(_has_content(f) for f in files):
                problems.append(
                    f"demo artifact directory holds no file with content: {rel} "
                    f"({len(files)} file(s), all empty or whitespace-only)")
        elif not _has_content(p):
            size = p.stat().st_size
            problems.append(
                f"demo artifact is empty: {rel} "
                f"({'0 bytes' if size == 0 else f'{size} bytes of whitespace'})")
    return problems


# ── gates (rule 4) ──────────────────────────────────────────────────────────

# Makefile targets, `review-round`'s prerequisite list, PR_ONLY_GATES and "which
# targets does CI honestly invoke" are all `gates.<...>` now — see the import note at
# the top of this file (N1).

# ── text_hash (rule 6) ──────────────────────────────────────────────────────

# Only the frozen build copies under docs/ are hashable: docs/plan/README.md is
# explicit that the text_hash discipline rides those copies, and a doc that is
# not checked in there cannot be pinned (see the four UNRESOLVED sources listed
# by --print-text-hashes).
DOC_ROOTS = ("docs/plan", "docs")
BOLD_LEAD = re.compile(r"^\*\*([A-Za-z]?[A-Za-z0-9]*[0-9](?:\.[0-9]+)*)[.)\s]")

# Shorthands the registry uses for a frozen copy under docs/plan/. `review3 §N2` is a
# citation of a real section of a real doc; without this it resolved to nothing and the
# section went unpinned.
DOC_ALIASES = {
    "review3": "plan-addendum-2026-08-02-review3.md",
    "addendum": "plan-addendum-2026-07-30.md",
    "scanner-node-ts": "plan-addendum-2026-08-02-scanner-node-ts.md",
}

# A `source:` may cite more than one section: `§A1/§D7`, `§F8 / review3 §N2`,
# `§1.5 P3 / §D2`.  Split on a `/` that separates citations — one directly before a `§`,
# or one surrounded by spaces — and never on a `/` inside a path (`conformance/paths.yaml`).
CITATION_SPLIT_RE = re.compile(r"\s*/\s*(?=§)|\s+/\s+")


def source_citations(source):
    return [part.strip() for part in CITATION_SPLIT_RE.split(source) if part.strip()]


def _resolve_doc(root, ref):
    name = pathlib.PurePosixPath(ref).name
    for base in DOC_ROOTS:
        for cand in ((root / base / name), (root / base / ref)):
            if cand.is_file():
                return cand
    return None


def _find_doc(root, citation, fallback=None):
    """(doc, rest) for one citation — the doc it names, or `fallback` if it names none."""
    m = re.search(r"([\w./-]+\.md)", citation)
    if m:
        return _resolve_doc(root, m.group(1)), citation[m.end():].strip()
    for alias, filename in DOC_ALIASES.items():
        # Round-6 F9: `\b` let `addendum` match the prefix of `addendum-2026-08-02`, so
        # a future citation would silently resolve against the wrong frozen copy. The
        # alias has to be the whole word: followed by whitespace, a §, or end of string.
        am = re.match(rf"{re.escape(alias)}(?=\s|§|$)", citation)
        if am:
            return _resolve_doc(root, filename), citation[am.end():].strip()
    return fallback, citation


def _anchor_of(rest):
    if not rest:
        return None
    m = re.search(r"§\s*([A-Za-z]?[\w.]*[\w])", rest)
    if m:
        return m.group(1).rstrip(".")
    m = re.match(r"([A-Za-z]?[\w.]*[\w])", rest)
    return m.group(1).rstrip(".") if m else None


def section_body(doc, anchor):
    """The text of one section of one doc, or None.

    Two section shapes exist in the frozen plan copies: a markdown heading
    (`## 4.5 Validation`) and a bold-lead paragraph (`**A1. Decision.** ...`).
    """
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
        return None

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
    return body or None


def resolve_source(root, source):
    """Resolve every citation in a `source:` — `(resolved, unresolved)`.

    Round-5 deferral: `text_hash` pinned only the *first* `§` of a multi-section
    source, so `P0-AUTHZ-TOPIC`'s §D7 (the topic vocabulary its §A1 obligation is
    authorised against) could be rewritten with the pin still green.  A requirement
    cites two sections because both carry the obligation; the pin has to cover both.

    `resolved` is `[(doc, anchor, body)]` in citation order; `unresolved` is the
    citations that named no reachable section, so the caller can *say so* rather than
    hash what it found and call the requirement pinned.
    """
    resolved, unresolved, doc = [], [], None
    for index, citation in enumerate(source_citations(source)):
        # A later citation inherits the running document only when it is nothing but a
        # section reference (`§D7`). Round-6 F9: anything else names its own document,
        # and if that name does not resolve the citation is unresolved — inheriting
        # would silently pin a same-numbered section of the wrong doc.
        inherit = doc if (index > 0 and citation.startswith("§")) else None
        doc, rest = _find_doc(root, citation, fallback=inherit)
        # Only the first citation may name its section by a bare leading token
        # (`server-hardening.md R3`, `... Quick start`). A later one has to carry an
        # explicit §, or `build-process.md §5 / conformance/paths.yaml` would go looking
        # for a section called "conformance".
        anchor = _anchor_of(rest) if (index == 0 or "§" in rest) else None
        body = section_body(doc, anchor) if (doc is not None and anchor) else None
        if body is None:
            unresolved.append(citation)
        else:
            resolved.append((doc, anchor, body))
    return resolved, unresolved


def text_hash_of(bodies):
    """sha256 of one section body, or of the cited bodies joined in citation order.

    A single-citation source hashes to exactly what it hashed before this change, so
    the 60-odd live single-section pins do not all churn at once — which matters,
    because a diff in which every hash moved is a diff nobody can review.
    """
    if isinstance(bodies, str):
        bodies = [bodies]
    joined = "\n\n".join(bodies)
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


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
            resolved, unresolved = resolve_source(root, req["source"])
            if not resolved:
                print(f"{req_id}: UNRESOLVED source {req['source']!r}")
                continue
            where = ", ".join(f"{doc.relative_to(root)} §{anchor}"
                              for doc, anchor, _ in resolved)
            tail = f"; UNRESOLVED: {', '.join(unresolved)}" if unresolved else ""
            print(f"{req_id}: {text_hash_of([b for _, _, b in resolved])}  "
                  f"# {where} — {req['source']}{tail}")
        return 0

    markers = collect_markers(root)
    waived, waiver_problems = gates.parse_waivers(root)
    failures = []
    warnings = []

    # D-010 follow-up item 2: a `WAIVED:` line that does not parse waives nothing, and
    # used to do so in silence — so did a line naming a requirement id that is not in
    # the registry. Both read to a human as a waiver in force.
    failures.extend(waiver_problems)
    for fingerprint in sorted(waived):
        # Round-6 F4: `ID_RE` alone left the near-misses silent — an em dash *inside*
        # the id (the very transcription slip the parser's own hint anticipates for the
        # separator), or a lowercased id, is not requirement-shaped, so it escaped the
        # registry check and went on reading to a human as a waiver in force.
        if fingerprint in registry:
            continue
        normalized = re.sub(r"[—–]", "-", fingerprint).upper()
        if not ID_RE.match(normalized):
            continue  # a path, an artifact tree: not the registry's business
        if normalized in registry:
            failures.append(
                f"WAIVERS.md waives {fingerprint}, which is not spelled the way the "
                f"registry spells {normalized} — waivers are matched exactly, so this "
                f"line waives nothing. Fix the spelling (dash or case).")
        else:
            failures.append(
                f"WAIVERS.md waives {fingerprint}, which is not a requirement id in "
                f"conformance/requirements.yaml — a typo'd id waives nothing, forever. "
                f"(Fingerprints that are not requirement-shaped — paths, artifact trees "
                f"— are not held to the registry.)")

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

    targets = gates.makefile_targets(root)
    round_gates = gates.review_round_prerequisites(root)
    pr_only = gates.pr_only_gates(root)
    ci_invoked, ci_rejected = gates.ci_gate_invocations(root, round_gates, pr_only)
    failures.extend(gates.pr_only_declaration_problems(root))

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
                           f"Makefile target that enforces it, or waive it"]
            else:
                # rule 4, tightened by round-5 F3: a gate is a Makefile target that a
                # review round runs (review-round prerequisite) and that CI runs
                # (invoked by a workflow step). A name alone proves neither.
                gaps = []
                if gate not in targets:
                    gaps.append("it is not a target in the Makefile")
                else:
                    if gate not in round_gates:
                        gaps.append("it is not a prerequisite of `review-round`, so no "
                                    "review round runs it")
                    if gate not in ci_invoked:
                        gaps.append("no workflow step invokes `make " + gate + "` in a "
                                    "way that lets it decide the build, so CI does not "
                                    "run it")
                if gaps:
                    status = "uncovered"
                    details = [f"{req_id} ({kind}) gate {gate!r} is not a gate: "
                               + "; ".join(gaps)
                               + f". review-round runs {sorted(round_gates)}; CI invokes "
                               f"{sorted(ci_invoked)}"]
                    # N1: say *why* an invocation did not count. The reviewer should not
                    # have to diff this against tests/test_gate_parity.py to find out.
                    details += [f"    rejected: {why}" for why in ci_rejected.get(gate, [])]
                else:
                    status = "verified"

        entry["status"] = status
        entry["notes"] = details
        matrix[req_id] = entry

        # `failed` and `not-collected` are defects, not accepted risk: red whatever
        # the phase and whatever WAIVERS.md says.
        if status in {"failed", "not-collected"}:
            failures.extend(details)
        elif due and status in {"uncovered", "skipped-only"} and req_id not in waived:
            failures.extend(details or [f"{req_id} ({kind}) {status} and not waived"])

        # rule 6 — text_hash freshness, over every section the source cites.
        # Round-6 F2: `resolved` was bound only on the non-retired path while the
        # `if pinned:` block below ran unconditionally, so a retired requirement that
        # kept its `text_hash` — the natural way to retire one — crashed the gate with
        # UnboundLocalError, or silently compared its pin against the *previous*
        # requirement's sections. There are no retired reqs today, which is why nothing
        # caught it. Bind per iteration, and let a retired req skip the check outright:
        # its text is no longer an obligation, so nothing hangs on the pin being fresh.
        pinned = req.get("text_hash") if status != "retired" else None
        resolved, unresolved = [], []
        if status != "retired":
            resolved, unresolved = resolve_source(root, req["source"])
            entry["text_hash_sections"] = [
                f"{doc.relative_to(root)} §{anchor}" for doc, anchor, _ in resolved]
            if unresolved:
                entry["text_hash_unresolved"] = unresolved
                if resolved:
                    warnings.append(
                        f"{req_id}: {len(resolved)} of "
                        f"{len(resolved) + len(unresolved)} cited section(s) are "
                        f"covered by text_hash; nothing watches "
                        f"{', '.join(repr(u) for u in unresolved)} in "
                        f"{req['source']!r} — re-word the citation to a heading or "
                        f"bold-lead in a frozen docs/plan/ copy, or accept that it is "
                        f"unanchorable")
        if not pinned and status != "retired":
            # Round-5 F5: no pin used to mean no output at all, so a green run could not
            # be told apart from an unchecked one. Say which requirements the source-text
            # check is not covering, and why — warning, not failure: the source may be a
            # doc that is not a frozen copy under docs/plan/, or a section that cannot be
            # anchored, and neither is a defect in this run. (A *pinned* req whose source
            # will not resolve is already a hard failure below.)
            entry["text_hash_resolved"] = bool(resolved)
            if resolved:
                warnings.append(
                    f"{req_id} has no text_hash — its source {req['source']!r} resolves "
                    f"to {', '.join(entry['text_hash_sections'])} and could be pinned; "
                    f"unpinned means a silent edit to that text never re-opens review "
                    f"(re-pin with `python conformance/check.py --print-text-hashes`)")
            else:
                warnings.append(
                    f"{req_id} has no text_hash and its source {req['source']!r} does not "
                    f"resolve to a section — nothing checks this "
                    f"requirement's source text; re-word the source: citation to a "
                    f"heading or bold-lead in a frozen docs/plan/ copy, or accept that it "
                    f"is unanchorable")

        if pinned:
            if not resolved:
                failures.append(
                    f"{req_id}: text_hash pinned but its source section could not be "
                    f"resolved: {req['source']!r}")
            else:
                actual = text_hash_of([body for _, _, body in resolved])
                entry["text_hash_actual"] = actual
                if actual != pinned:
                    failures.append(
                        f"{req_id}: text_hash stale — source {req['source']!r} "
                        f"({', '.join(entry['text_hash_sections'])}) changed since it "
                        f"was pinned")
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

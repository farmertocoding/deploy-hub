#!/usr/bin/env python3
"""conformance-check (review3 §Q2/§Q4/§Q5) — minimal working v0.

Checks:
  1. Every phase-due `verify: test` req has >=1 collected test carrying its marker.
  2. Every @pytest.mark.req(...) id in the suite resolves to a live registry id.
  3. `verify: demo` reqs need conformance/demos/phase-N.md to exist.
  4. --phase N: reqs due at phase N must be covered or waived in WAIVERS.md.

Emits conformance/matrix.json. Exits non-zero on any violation.
"""
import argparse
import ast
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent


def load_registry():
    data = yaml.safe_load((REPO / "conformance/requirements.yaml").read_text())
    return {r["id"]: r for r in data["requirements"]}


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


def collect_markers():
    """Map req id -> [test node ids] by AST walk (round-1 finding: a text grep
    counted markers in comments/docstrings/dead code as coverage, and silently
    ignored malformed ids). Only decorators attached to test functions count;
    ANY string arg is captured so typos are flagged, not skipped."""
    found = {}
    for py in (REPO / "tests").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test"):
                    continue
                for req_id in _req_ids_from_decorators(node):
                    found.setdefault(req_id, []).append(
                        f"{py.relative_to(REPO)}::{node.name}")
    return found


def waived_ids():
    """Only structured `WAIVED: <id> — reason (date)` lines count (round-1 finding:
    a bare word-boundary regex let prose mentioning an id silently waive it)."""
    waivers = REPO / "WAIVERS.md"
    if not waivers.exists():
        return set()
    out = set()
    for line in waivers.read_text().splitlines():
        m = re.match(r"^WAIVED:\s*(\S+)\s+—\s+\S.*\(\d{4}-\d{2}-\d{2}\)", line.strip())
        if m:
            out.add(m.group(1))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, default=None)
    args = parser.parse_args()

    registry = load_registry()
    markers = collect_markers()
    waived = waived_ids()
    failures = []

    # Unknown markers are red.
    for req_id, tests in markers.items():
        if req_id not in registry:
            failures.append(f"unknown req id in tests: {req_id} ({tests})")

    matrix = {}
    for req_id, req in registry.items():
        tests = markers.get(req_id, [])
        due = args.phase is None or req["phase"] <= args.phase
        status = "unverified"
        if req["verify"] == "test":
            status = "covered" if tests else "uncovered"
        elif req["verify"] == "demo":
            demo = REPO / f"conformance/demos/phase-{req['phase']}.md"
            status = "covered" if demo.exists() else "uncovered"
        if due and status == "uncovered" and req_id not in waived:
            failures.append(f"{req_id} ({req['verify']}) uncovered and not waived")
        matrix[req_id] = {"tests": tests, "status": status, "phase": req["phase"]}

    (REPO / "conformance/matrix.json").write_text(json.dumps(matrix, indent=2))

    # Flake-quarantine cap (PROC-FLAKE-CAP): red at >5 quarantined tests.
    # Decorator-anchored (round-1 finding: string mentions counted toward the cap).
    flaky_re = re.compile(r"^\s*@pytest\.mark\.flaky_quarantine\b", re.M)
    count = sum(len(flaky_re.findall(py.read_text(encoding="utf-8")))
                for py in (REPO / "tests").rglob("*.py"))
    if count > 5:
        failures.append(f"flake quarantine cap exceeded: {count} > 5")

    if failures:
        print("conformance-check FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"conformance-check ok — {len(registry)} reqs, matrix.json written")
    return 0


if __name__ == "__main__":
    sys.exit(main())

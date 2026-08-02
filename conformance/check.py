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
import json
import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent


def load_registry():
    data = yaml.safe_load((REPO / "conformance/requirements.yaml").read_text())
    return {r["id"]: r for r in data["requirements"]}


def collect_markers():
    """Map req id -> [test ids] by scanning test files (cheap and dependency-free)."""
    marker_re = re.compile(r"@pytest\.mark\.req\(\s*[\"']([A-Z0-9-]+)[\"']\s*\)")
    found = {}
    for py in (REPO / "tests").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in marker_re.finditer(text):
            found.setdefault(m.group(1), []).append(str(py.relative_to(REPO)))
    return found


def waived_ids():
    waivers = REPO / "WAIVERS.md"
    if not waivers.exists():
        return set()
    return set(re.findall(r"\b([A-Z][A-Z0-9]+-[A-Z0-9-]+)\b", waivers.read_text()))


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

    if failures:
        print("conformance-check FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"conformance-check ok — {len(registry)} reqs, matrix.json written")
    # Flake-quarantine cap (PROC-FLAKE-CAP): red at >5 quarantined tests.
    flaky = subprocess.run(
        ["grep", "-rc", "@pytest.mark.flaky_quarantine", str(REPO / "tests")],
        capture_output=True, text=True,
    )
    count = sum(int(line.rsplit(":", 1)[1]) for line in flaky.stdout.splitlines() if ":" in line)
    if count > 5:
        print(f"flake quarantine cap exceeded: {count} > 5")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

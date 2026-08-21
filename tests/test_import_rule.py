"""§D4's one hard rule, enforced: cloud/DNS SDK imports only under providers/.

This is what makes "Phase 5 is only provisioning + DNS code" verifiable.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = re.compile(r"^\s*(import|from)\s+(boto3|botocore|azure|cloudflare|CloudFlare)\b", re.M)
# tests/, scripts_dev/ and conformance/ are scanned too (round-1 finding): an SDK
# import hiding in test or process code still violates the seam.
APPS = ["core", "vault", "catalog", "scanner", "provision", "deploys",
        "reconcile", "monitor", "scaling", "realtime", "hub", "wizard",
        "tests", "scripts_dev", "conformance"]


@pytest.mark.req("P0-IMPORT-RULE")
@pytest.mark.req("ARCH-D4-IMPORT-RULE")
def test_cloud_sdk_imports_only_under_providers():
    assert "wizard" in APPS, "wizard/ is a first-party app; an SDK import there is the seam"
    violations = []
    for app in APPS:
        for py in (REPO / app).rglob("*.py"):
            if FORBIDDEN.search(py.read_text(encoding="utf-8")):
                violations.append(str(py.relative_to(REPO)))
    assert violations == [], f"Cloud SDK imports outside providers/: {violations}"


def _direct_imports(package):
    """First-party packages imported anywhere under `package`."""
    edges = set()
    pattern = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_][\w]*)", re.M)
    for py in (REPO / package).rglob("*.py"):
        for name in pattern.findall(py.read_text(encoding="utf-8")):
            if (REPO / name).is_dir() and name != package:
                edges.add(name)
    return edges


def _reaches(start, target):
    """Walk the first-party import graph from `start`, looking for `target`.

    Returns the path as a list, or None. Depth-first over a graph this small is
    plenty; the point is to follow edges at all, not to do it cleverly.
    """
    stack, seen = [(start, [start])], {start}
    while stack:
        node, path = stack.pop()
        for edge in sorted(_direct_imports(node)):
            if edge == target:
                return path + [edge]
            if edge not in seen:
                seen.add(edge)
                stack.append((edge, path + [edge]))
    return None


@pytest.mark.req("ARCH-V6-DEPLOYS-NO-SCANNER-IMPORT")
def test_deploys_never_imports_scanner():
    """§V6: deploys/ reads only the stored manifest — the wizard materializes
    module outputs; a deploys→scanner import edge may never appear.

    TRANSITIVE, deliberately (2026-08-09 design debate). The original version grepped
    deploys/ for a direct `import scanner` line. That would have stayed green if the
    wizard had been placed in core/, because everything imports core — `deploys →
    core → scanner` satisfies a direct-import grep while completely destroying the
    invariant. A gate that can be satisfied by moving the violation one file away is
    not a gate.
    """
    path = _reaches("deploys", "scanner")
    assert path is None, "deploys reaches scanner via: " + " -> ".join(path or [])


@pytest.mark.req("ARCH-V6-DEPLOYS-NO-SCANNER-IMPORT")
def test_transitive_detector_actually_detects():
    """The test above passes trivially if the graph walk is broken. This asserts the
    detector finds a path that genuinely exists (wizard is allowed to import scanner —
    it is the component that materializes module outputs)."""
    assert _reaches("wizard", "scanner") is not None


@pytest.mark.req("ARCH-V6-DEPLOYS-NO-SCANNER-IMPORT")
def test_core_stays_free_of_scanner():
    """core is the shared kernel: a scanner dependency here becomes a scanner
    dependency in every app, which is the exact mechanism the test above guards."""
    path = _reaches("core", "scanner")
    assert path is None, "core reaches scanner via: " + " -> ".join(path or [])


@pytest.mark.req("ARCH-V6-DEPLOYS-NO-SCANNER-IMPORT")
def test_reconcile_never_imports_scanner():
    """Reconciler shares deploys.steps; it must not grow a scanner edge either."""
    path = _reaches("reconcile", "scanner")
    assert path is None, "reconcile reaches scanner via: " + " -> ".join(path or [])


@pytest.mark.req("ARCH-V6-DEPLOYS-NO-SCANNER-IMPORT")
def test_monitor_never_imports_scanner():
    """Collector JSON lives in monitor/; it must not grow a scanner edge either."""
    path = _reaches("monitor", "scanner")
    assert path is None, "monitor reaches scanner via: " + " -> ".join(path or [])

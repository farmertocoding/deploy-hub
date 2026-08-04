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
        "reconcile", "monitor", "scaling", "realtime", "hub",
        "tests", "scripts_dev", "conformance"]


@pytest.mark.req("P0-IMPORT-RULE")
@pytest.mark.req("ARCH-D4-IMPORT-RULE")
def test_cloud_sdk_imports_only_under_providers():
    violations = []
    for app in APPS:
        for py in (REPO / app).rglob("*.py"):
            if FORBIDDEN.search(py.read_text(encoding="utf-8")):
                violations.append(str(py.relative_to(REPO)))
    assert violations == [], f"Cloud SDK imports outside providers/: {violations}"


@pytest.mark.req("ARCH-V6-DEPLOYS-NO-SCANNER-IMPORT")
def test_deploys_never_imports_scanner():
    """§V6: deploys/ reads only the stored manifest — the wizard materializes
    module outputs; a deploys→scanner import edge may never appear."""
    violations = []
    for py in (REPO / "deploys").rglob("*.py"):
        if re.search(r"^\s*(import|from)\s+scanner\b",
                     py.read_text(encoding="utf-8"), re.M):
            violations.append(str(py.relative_to(REPO)))
    assert violations == [], violations

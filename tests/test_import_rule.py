"""§D4's one hard rule, enforced: cloud/DNS SDK imports only under providers/.

This is what makes "Phase 5 is only provisioning + DNS code" verifiable.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = re.compile(r"^\s*(import|from)\s+(boto3|botocore|azure|cloudflare|CloudFlare)\b", re.M)
APPS = ["core", "vault", "catalog", "scanner", "provision", "deploys",
        "reconcile", "monitor", "scaling", "realtime", "hub"]


@pytest.mark.req("P0-IMPORT-RULE")
def test_cloud_sdk_imports_only_under_providers():
    violations = []
    for app in APPS:
        for py in (REPO / app).rglob("*.py"):
            if FORBIDDEN.search(py.read_text(encoding="utf-8")):
                violations.append(str(py.relative_to(REPO)))
    assert violations == [], f"Cloud SDK imports outside providers/: {violations}"

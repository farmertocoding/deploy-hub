"""D-017: parked D-012 reqs are not due at phase 2.

Joseph parked declared-test-material out of Phase 1 pending a threat model.
The Architect ruled D-017: bump SCAN-DECLARED-TEST-MATERIAL and
SCAN-DECLARED-GUARDS from phase 2 to phase 4 so check.py --phase 2 is not
blocked by parked scanner work. Do not re-land D-012. Do not retire the ids.
Markers on tests/test_scanner_declarations.py stay.
"""
from pathlib import Path

import check

REPO = Path(__file__).resolve().parent.parent
DECLARED_IDS = ("SCAN-DECLARED-TEST-MATERIAL", "SCAN-DECLARED-GUARDS")


def test_scan_declared_ids_are_phase_4():
    """Load the registry; both parked D-012 ids are phase 4; markers still collect.

    What would make this fail: putting either id back on phase 2 (or 1), retiring
    them, or stripping the markers from tests/test_scanner_declarations.py.
    """
    registry = check.load_registry(REPO)
    markers = check.collect_markers(REPO)
    for rid in DECLARED_IDS:
        req = registry[rid]
        assert req["phase"] == 4, f"{rid} phase={req['phase']!r}, want 4 (D-017)"
        assert req.get("status") != "retired", f"{rid} was retired; D-017 keeps it live"
        nodeids = markers.get(rid) or []
        assert nodeids, f"{rid} has no collected @pytest.mark.req markers"
        on_parked = [
            nid for nid in nodeids
            if nid.startswith("tests/test_scanner_declarations.py::")
        ]
        assert on_parked, (
            f"{rid} markers left tests/test_scanner_declarations.py: {nodeids}"
        )

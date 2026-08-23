"""D-017 / SCAN-M4: parked D-012 reqs stay phase 4; parser tests do not verify them.

Joseph parked declared-test-material out of Phase 1 pending a threat model.
D-017 bumped SCAN-DECLARED-TEST-MATERIAL and SCAN-DECLARED-GUARDS to phase 4
so earlier gates were not blocked by parked scanner work. Task 0 SCAN-M4
strips the full-text markers from tests/test_scanner_declarations.py: parser
tests keep running unmarked; full-text ids stay uncovered until Task 3 E2E.
Ids are not retired. text: is unchanged.
"""
from pathlib import Path

import check

REPO = Path(__file__).resolve().parent.parent
DECLARED_IDS = ("SCAN-DECLARED-TEST-MATERIAL", "SCAN-DECLARED-GUARDS")


def test_scan_declared_ids_are_phase_4():
    """Load the registry; both parked D-012 ids are phase 4 and not retired.

    What would make this fail: putting either id back on phase 2 (or 1), or
    retiring them. Parser-file markers are not required (SCAN-M4).
    """
    registry = check.load_registry(REPO)
    for rid in DECLARED_IDS:
        req = registry[rid]
        assert req["phase"] == 4, f"{rid} phase={req['phase']!r}, want 4 (D-017)"
        assert req.get("status") != "retired", f"{rid} was retired; D-017 keeps it live"


def test_scan_declared_full_text_is_not_verified_by_parser_only_tests():
    """SCAN-M4: parked parser tests must not carry full-text SCAN-DECLARED-* markers.

    What would make this fail: leaving @pytest.mark.req(SCAN-DECLARED-TEST-MATERIAL)
    or SCAN-DECLARED-GUARDS on tests/test_scanner_declarations.py once --phase 4
    is due. Parser-only proofs do not prove the live path (D-055).
    """
    markers = check.collect_markers(REPO)
    parser_prefix = "tests/test_scanner_declarations.py::"
    for rid in DECLARED_IDS:
        nodeids = markers.get(rid) or []
        on_parser = [n for n in nodeids if n.startswith(parser_prefix)]
        assert not on_parser, (
            f"{rid} is still marked on parser-only tests — SCAN-M4 forbids "
            f"parser tests verifying the full text: {on_parser}"
        )
        assert not nodeids, (
            f"{rid} must carry no marker until Task 3 live-path E2E: {nodeids}"
        )

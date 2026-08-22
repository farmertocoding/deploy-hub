"""SEC-B2 / UX-F5 clause split (D-035 / D-040, SCAN-M4 precedent).

The full-text ids stay in the registry untouched and carry NO marker while one
of their clauses is unbuilt: a marker would claim the whole text, and the whole
text is not true this phase. The buildable clauses live under their own new
ids; the unbuilt clauses are registered at phase 4. These tests are the ratchet
that keeps the shape from eroding — the moment somebody puts a marker back on a
full-text id, or rephases a split id, this file goes red by name.
"""
import pathlib

import check
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent

FULL_TEXT_SEC_B2 = "SEC-B2-NO-DNS-TOKENS-ON-TARGETS"
FULL_TEXT_UX_F5 = "UX-F5-ACTION-TIERS"

# id -> the phase its clause is buildable at (design note §3, D-035/D-040)
SPLIT_CLAUSE_PHASES = {
    "SEC-B2-NO-TOKEN-ON-TARGET": 3,
    "TLS-B2-HUB-DNS01-UNPROXIED": 4,
    "UX-F5-T2-T3-FRICTION": 3,
    "SEC-F5-T1-HARDWARE-TOUCH": 4,
}


def _suite_markers():
    """req-id -> [nodeids], from the same AST walk the conformance gate runs.

    Decorator-anchored (check.collect_markers): an id mentioned in a string,
    a comment, or this file never counts as a marker.
    """
    return check.collect_markers(REPO)


def _registry():
    data = yaml.safe_load(
        (REPO / "conformance" / "requirements.yaml").read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["requirements"]}


def test_sec_b2_full_text_id_carries_no_marker():
    """A marker on SEC-B2-NO-DNS-TOKENS-ON-TARGETS claims both clauses, and the
    Hub-central-DNS-01 clause is unbuilt until phase 4 (D-035). The exfiltration
    clause is proven under SEC-B2-NO-TOKEN-ON-TARGET; the full-text id sits
    uncovered behind Task 19's clause-scoped waiver, never behind a marker.
    """
    markers = _suite_markers()
    assert FULL_TEXT_SEC_B2 not in markers, (
        f"{FULL_TEXT_SEC_B2} must carry no marker while its DNS-01 clause is "
        f"unbuilt — found: {markers.get(FULL_TEXT_SEC_B2)}")


def test_ux_f5_full_text_id_carries_no_marker():
    """Same shape for UX-F5-ACTION-TIERS: the T1 hardware-touch clause is
    phase 4 (D-040), so the full text cannot be claimed by any test this phase.
    The buildable T2/T3 clauses are proven under UX-F5-T2-T3-FRICTION.
    """
    markers = _suite_markers()
    assert FULL_TEXT_UX_F5 not in markers, (
        f"{FULL_TEXT_UX_F5} must carry no marker while its hardware clause is "
        f"unbuilt — found: {markers.get(FULL_TEXT_UX_F5)}")


def test_split_clause_ids_exist_and_name_their_phase():
    """Each clause id exists at exactly the phase its clause is buildable, and
    the full-text ids stay at phase 3 untouched (the split is expressed by the
    NEW ids, never by narrowing a hashed text).
    """
    reg = _registry()
    for rid, phase in sorted(SPLIT_CLAUSE_PHASES.items()):
        assert rid in reg, f"clause id missing from the registry: {rid}"
        assert reg[rid]["phase"] == phase, (
            f"{rid} must be phase {phase}, got {reg[rid]['phase']}")
        assert reg[rid]["verify"] == "test", (
            f"{rid} must be verify: test, got {reg[rid]['verify']!r}")
    for full_text in (FULL_TEXT_SEC_B2, FULL_TEXT_UX_F5):
        assert reg[full_text]["phase"] == 3, (
            f"{full_text} stays due at phase 3 — the split never rephases it")

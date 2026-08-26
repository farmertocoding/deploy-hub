"""SEC-B2 / UX-F5 clause split (D-035 / D-040, SCAN-M4 precedent).

The full-text ids stay in the registry untouched. A marker claims the whole
text, so it goes on only after every clause holds. Both SEC-B2 clauses and
both UX-F5 clauses have landed; the split ids stay at their registered
phases. These tests are the ratchet that keeps the shape from eroding.
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


def test_sec_b2_full_text_id_is_marked_now_that_dns01_lands():
    """D-035 retirement: TLS-B2-HUB-DNS01-UNPROXIED is marked, so the full-text
    SEC-B2-NO-DNS-TOKENS-ON-TARGETS marker goes back on.
    """
    markers = _suite_markers()
    assert FULL_TEXT_SEC_B2 in markers, (
        f"{FULL_TEXT_SEC_B2} must be marked now that the DNS-01 clause landed")


def test_ux_f5_full_text_id_is_marked_now_that_hardware_lands():
    """D-040 retirement: SEC-F5-T1-HARDWARE-TOUCH is marked, so the full-text
    UX-F5-ACTION-TIERS marker goes back on.
    """
    markers = _suite_markers()
    assert FULL_TEXT_UX_F5 in markers, (
        f"{FULL_TEXT_UX_F5} must be marked now that the hardware clause landed")


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


def _acceptance_fn(name: str) -> str:
    src = (REPO / "tests" / "acceptance" / "test_phase_3.py").read_text(
        encoding="utf-8")
    needle = f"def {name}("
    start = src.index(needle)
    after = src[start:]
    nxt = after.find("\ndef ", 1)
    return after[:nxt] if nxt != -1 else after


def test_sec_b2_marked_acceptance_covers_celery_kwargs():
    """The sole function-level SEC-B2-NO-TOKEN-ON-TARGET marker must scan
    Celery task kwargs. The registry names that surface; the source file is
    module-pytestmark only, so collect_markers never sees
    tests/test_no_token_exfiltration.py::test_no_dns_token_in_celery_task_kwargs.
    Do not put @pytest.mark.req on the full-text SEC-B2 id.
    """
    body = _acceptance_fn("test_no_dns_token_reaches_any_target_bound_surface")
    assert "celery" in body.lower(), (
        "the marked SEC-B2 acceptance body must cover Celery kwargs"
    )
    assert "run_deploy" in body or "CELERY_BEAT_SCHEDULE" in body, (
        "transcribe tests/test_no_token_exfiltration.py::"
        "test_no_dns_token_in_celery_task_kwargs, not a comment"
    )
    src = (REPO / "tests" / "acceptance" / "test_phase_3.py").read_text(
        encoding="utf-8")
    assert '@pytest.mark.req("SEC-B2-NO-DNS-TOKENS-ON-TARGETS")' not in src

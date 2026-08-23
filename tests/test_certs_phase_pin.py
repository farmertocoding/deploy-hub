"""Phase pin for Hub-central DNS-01 copy (design note §1.2 / Task 0).

Unproxied refusal stays. The honest horizon is phase 4, not Phase 3b.
Do not invent HUB_TEST_CF_TOKEN. Do not mark the full-text SEC-B2 id.
"""
import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
CERTS = REPO / "deploys" / "certs.py"
ACME = REPO / "tests" / "test_no_token_exfiltration.py"


def _unproxied_class_docstring():
    tree = ast.parse(CERTS.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "UnproxiedCertUnsupported":
            return ast.get_docstring(node) or ""
    raise AssertionError("UnproxiedCertUnsupported is missing from deploys/certs.py")


def _unproxied_fix_action():
    src = CERTS.read_text(encoding="utf-8")
    start = src.index("def _refuse_unproxied")
    chunk = src[start:]
    end = chunk.find("\ndef ", 1)
    return chunk if end == -1 else chunk[:end]


def _acme_docstring():
    tree = ast.parse(ACME.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and (
                node.name == "test_no_acme_dns_challenge_block_is_ever_generated"):
            return ast.get_docstring(node) or ""
    raise AssertionError(
        "test_no_acme_dns_challenge_block_is_ever_generated is missing")


def test_unproxied_cert_copy_names_phase_4_not_phase_3b():
    """What would make this fail: UnproxiedCertUnsupported or the Finding
    fix_action still naming Phase 3b as the DNS-01 horizon.
    """
    doc = _unproxied_class_docstring()
    assert "phase 4" in doc.lower(), doc
    assert "3b" not in doc.lower(), doc

    fix = _unproxied_fix_action()
    assert "phase 4" in fix.lower(), fix
    assert "3b" not in fix.lower(), fix
    assert "fix_action" in fix


def test_acme_scan_docstring_names_phase_4_not_phase_3b():
    """What would make this fail: the ACME-scan docstring still saying
    Hub-central DNS-01 is Phase 3b.
    """
    doc = _acme_docstring()
    assert "phase 4" in doc.lower(), doc
    assert "3b" not in doc.lower(), doc
    src = ACME.read_text(encoding="utf-8")
    assert "SEC-B2-NO-DNS-TOKENS-ON-TARGETS" not in src

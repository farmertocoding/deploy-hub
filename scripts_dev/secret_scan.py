"""Repository secret scan. Narrow fixture allowlists, no tree-wide omits."""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIR_NAMES = {
    ".git", "node_modules", ".venv", "mutants", "__pycache__", "dist", "build",
    ".pytest_cache", "coverage", ".worktrees",
}
ALLOW_PATH_PARTS = {"docs", "research", "phase-"}
FAKE_MARKERS = (
    "t1-", "hubk_test_", "whsec_test", "VAULT-TEST-", "PIPELINE-ENV-SNAPSHOT",
    "wizard-test-", "pw-1234567890", "a-long-dev-password", "changeme",
    "not-a-credential", "EXAMPLE", "example.com", "dummy", "fixture",
    "REALPASSWORD", "log-scrub: allow",
)
ASSIGNMENT = re.compile(r"SECRET_KEY\s*=\s*['\"][^'\"]+['\"]")
PEM = re.compile(r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----")
AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def _iter_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".woff", ".woff2", ".sqlite3", ".lock"}:
            continue
        if path.name in {".env", "pnpm-lock.yaml", "package-lock.json"}:
            continue
        yield path


def _allowed(text, rel):
    if "settings" in rel:
        return True
    if any(marker in text for marker in FAKE_MARKERS):
        return True
    if rel.endswith(".md"):
        return True
    return False


def scan():
    hits = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if not (ASSIGNMENT.search(text) or PEM.search(text) or AWS_KEY.search(text)):
            continue
        if _allowed(text, rel):
            continue
        hits.append(rel)
    return hits


def main():
    hits = scan()
    if hits:
        print("possible secret in:")
        for hit in hits:
            print(hit)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

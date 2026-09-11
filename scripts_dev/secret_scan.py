"""Repository secret scan. Line-level fixture allowlists, git-tracked files."""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIR_NAMES = {
    ".git", "node_modules", ".venv", "mutants", "__pycache__", "dist", "build",
    ".pytest_cache", "coverage", ".worktrees",
}
ALLOW_PATH_PREFIXES = ("tests/", "scripts_dev/", "conformance/", "docs/", "research/")
FAKE_MARKERS = (
    "t1-", "hubk_test_", "whsec_test", "VAULT-TEST-", "PIPELINE-ENV-SNAPSHOT",
    "wizard-test-", "pw-1234567890", "a-long-dev-password", "changeme",
    "not-a-credential", "EXAMPLE", "example.com", "dummy", "fixture",
    "REALPASSWORD", "log-scrub: allow", "django-insecure",
    "AKIAABCDEFGHIJKLMNOP",
)
ASSIGNMENT = re.compile(r"SECRET_KEY\s*=\s*['\"][^'\"]+['\"]")
PEM = re.compile(
    r"-----BEGIN (RSA |OPENSSH |EC |ENCRYPTED |DSA |PGP )?PRIVATE KEY-----"
)
AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def _git_files(root: pathlib.Path):
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    names = [name for name in result.stdout.decode("utf-8", "replace").split("\0") if name]
    return [root / name for name in names]


def _iter_files(root: pathlib.Path | None = None):
    root = root or ROOT
    tracked = _git_files(root)
    if tracked is not None:
        for path in tracked:
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix in {".pyc", ".png", ".jpg", ".woff", ".woff2", ".sqlite3", ".lock"}:
                continue
            if path.name in {"pnpm-lock.yaml", "package-lock.json"}:
                continue
            yield path
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".woff", ".woff2", ".sqlite3", ".lock"}:
            continue
        if path.name in {"pnpm-lock.yaml", "package-lock.json"}:
            continue
        yield path


def _line_allowed(line: str, rel: str) -> bool:
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return True
    if rel.endswith(".md") or any(rel.startswith(prefix) for prefix in ALLOW_PATH_PREFIXES):
        return True
    if any(marker in line for marker in FAKE_MARKERS):
        return True
    return False


def _hits_in_text(text: str, rel: str):
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not (ASSIGNMENT.search(line) or PEM.search(line) or AWS_KEY.search(line)):
            continue
        if _line_allowed(line, rel):
            continue
        hits.append(f"{rel}:{lineno}")
    return hits


def scan(*, root: pathlib.Path | None = None, paths=None):
    root = root or ROOT
    hits = []
    files = list(paths) if paths is not None else list(_iter_files(root))
    for path in files:
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = pathlib.Path(path).resolve().relative_to(root.resolve()).as_posix()
        hits.extend(_hits_in_text(text, rel))
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

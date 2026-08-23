"""One digest-pinned partner T1 fixture. Not catalog/ and not a Hub table.

T1 ships via docker load / Fake registry of this image only. Partners cannot
supply a Dockerfile, build step, git URL, or unconstrained image.
"""
import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO / "images" / "partner-t1-static"
DIGEST_PATH = REPO / "conformance" / "fixtures" / "partner-t1-template.digest"
TEMPLATE_REF = "partner-t1-static"


def compute_source_digest():
    digest = hashlib.sha256()
    for path in sorted(p for p in SOURCE_DIR.rglob("*") if p.is_file()):
        if path.name == "README.md":
            continue
        digest.update(path.relative_to(SOURCE_DIR).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def fixture_archive():
    return (SOURCE_DIR / "index.html").read_bytes()


def load_pinned_digest():
    return DIGEST_PATH.read_text(encoding="utf-8").strip()


FIXTURE_DIGEST = load_pinned_digest()

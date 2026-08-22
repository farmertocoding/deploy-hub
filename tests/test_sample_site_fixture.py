"""sample-site/ on-disk contract (D-030)."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAMPLE_SITE = REPO / "sample-site"


def test_sample_site_healthz_contract_on_disk():
    """A GET handler or urls.py declares pinned /healthz JSON {live, ready, checks}.

    What would make this fail: missing sample-site/, or a healthz that only
    returns status=ok without the three contract keys.
    """
    assert SAMPLE_SITE.is_dir(), "sample-site/ must exist (D-030)"
    sources = []
    for path in SAMPLE_SITE.rglob("*.py"):
        if any(part in {".venv", "__pycache__"} for part in path.parts):
            continue
        sources.append(path.read_text(encoding="utf-8"))
    blob = "\n".join(sources)
    assert "/healthz" in blob
    assert '"live"' in blob or "'live'" in blob
    assert '"ready"' in blob or "'ready'" in blob
    assert '"checks"' in blob or "'checks'" in blob


def test_sample_site_dockerfile_uses_npm_ci_or_hashed_pip():
    """Dockerfile pins installs: npm ci, hashed pip, or uv sync --frozen.

    What would make this fail: npm install, pip without --require-hashes, or
    an unlocked uv sync.
    """
    path = SAMPLE_SITE / "Dockerfile"
    assert path.is_file(), "sample-site/Dockerfile must exist (D-030)"
    dockerfile = path.read_text(encoding="utf-8")
    hashed = "pip install --require-hashes" in dockerfile
    npm_ci = "npm ci" in dockerfile
    uv_frozen = "uv sync --frozen" in dockerfile
    assert hashed or npm_ci or uv_frozen
    assert "npm install" not in dockerfile
    if "pip install" in dockerfile:
        assert "--require-hashes" in dockerfile

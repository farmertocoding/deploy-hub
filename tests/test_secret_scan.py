"""Line-level secret-scan allowlist. Whole-file fake markers must not hide a leak."""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _scan_mod():
    path = REPO / "scripts_dev" / "secret_scan.py"
    spec = importlib.util.spec_from_file_location("secret_scan", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_secret_scan_flags_quoted_secret_even_when_file_mentions_example_com(tmp_path):
    scan = _scan_mod()
    leaked = tmp_path / "app.py"
    leaked.write_text('SECRET_KEY = "live-operator-secret"\n# example.com\n', encoding="utf-8")
    hits = scan.scan(root=tmp_path, paths=[leaked])
    assert hits == ["app.py:1"]


def test_secret_scan_allows_same_line_fixture_marker(tmp_path):
    scan = _scan_mod()
    ok = tmp_path / "ok.py"
    ok.write_text('SECRET_KEY = "t1-not-a-credential"\n', encoding="utf-8")
    assert scan.scan(root=tmp_path, paths=[ok]) == []


def test_secret_scan_does_not_skip_tracked_env_by_filename(tmp_path):
    scan = _scan_mod()
    env = tmp_path / ".env"
    env.write_text('SECRET_KEY = "live-from-env-file"\n', encoding="utf-8")
    hits = scan.scan(root=tmp_path, paths=[env])
    assert hits == [".env:1"]

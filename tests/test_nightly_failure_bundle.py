"""Local nightly failure bundle: write a scrubbed note, optionally open a gh issue."""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent


VAULT_PLAINTEXT = "vault-plaintext-must-not-appear-in-the-bundle"
SECRET_LINE = f"SECRET_KEY={VAULT_PLAINTEXT}"


def _fnf():
    sys.path.insert(0, str(REPO / "scripts_dev"))
    import file_nightly_failure as fnf

    return fnf


def _write_log(tmp_path, extra=""):
    log = tmp_path / "nightly.log"
    log.write_text(
        "============================= test session starts ==============================\n"
        "FAILED tests/test_example.py::test_boom - assert False\n"
        f"{SECRET_LINE}\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_example.py::test_boom - assert False\n"
        "======================== 1 failed, 3 passed in 0.12s =========================\n"
        f"{extra}",
        encoding="utf-8",
    )
    return log


def _run(tmp_path, exit_code, log, monkeypatch):
    fnf = _fnf()
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    return fnf.main(
        [
            "--exit-code",
            str(exit_code),
            "--log",
            str(log),
            "--repo-root",
            str(tmp_path),
        ]
    )


def test_bundle_written_on_nonzero(tmp_path, monkeypatch):
    """What would make this fail: a non-zero nightly that writes nothing under
    conformance/demos/phase-2.5/failures/, or that omits the pytest summary /
    run-report sha when the report is present.
    """
    log = _write_log(tmp_path)
    report = tmp_path / "conformance" / "run-report.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"schema_version": 1, "sha": "abc123deadbeef"}\n', encoding="utf-8")

    rc = _run(tmp_path, 2, log, monkeypatch)
    assert rc != 0

    failures = tmp_path / "conformance" / "demos" / "phase-2.5" / "failures"
    written = sorted(failures.glob("*.md"))
    assert written, f"no bundle written under {failures}"
    body = written[0].read_text(encoding="utf-8")
    assert "1 failed, 3 passed" in body
    assert "FAILED tests/test_example.py::test_boom" in body
    assert "abc123deadbeef" in body or "run-report.json" in body
    assert "Hub host" not in body or "does not run on the Hub host" in body


def test_bundle_contains_no_vault_plaintext(tmp_path, monkeypatch):
    """What would make this fail: copying SECRET/KEY assignment values from the
    nightly log into the filed bundle.
    """
    log = _write_log(tmp_path)
    rc = _run(tmp_path, 1, log, monkeypatch)
    assert rc != 0

    failures = tmp_path / "conformance" / "demos" / "phase-2.5" / "failures"
    body = next(failures.glob("*.md")).read_text(encoding="utf-8")
    assert VAULT_PLAINTEXT not in body
    assert SECRET_LINE not in body


def test_gh_issue_is_optional_when_token_absent(tmp_path, monkeypatch, capsys):
    """What would make this fail: requiring `gh` / GITHUB_TOKEN, or claiming the
    script runs on the Hub host when the token is missing.
    """
    log = _write_log(tmp_path)
    fnf = _fnf()
    calls = []

    def _forbid_gh(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("gh must not run when GITHUB_TOKEN is absent")

    monkeypatch.setattr(fnf.subprocess, "run", _forbid_gh)
    monkeypatch.setattr(fnf.shutil, "which", lambda cmd: "/usr/bin/gh" if cmd == "gh" else None)

    rc = _run(tmp_path, 1, log, monkeypatch)
    assert rc != 0
    assert calls == []

    captured = capsys.readouterr()
    failures = tmp_path / "conformance" / "demos" / "phase-2.5" / "failures"
    written = next(failures.glob("*.md"))
    assert str(written) in captured.out
    assert "Hub host" not in captured.out

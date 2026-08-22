"""File a local bundle when `make nightly` exits non-zero.

D-023: the host of record is local Multipass + `make nightly`. This script
runs on an operator workstation after that target fails. It does not run on
the Hub host.

Usage:
    python scripts_dev/file_nightly_failure.py --exit-code N --log PATH

Writes `conformance/demos/phase-2.5/failures/<utc>.md` with the pytest
summary and the sha of `conformance/run-report.json` when that file exists.
Obvious SECRET/KEY assignment values are redacted. If `GITHUB_TOKEN` (or
`GH_TOKEN`) and `gh` are both present, opens an issue with the bundle;
otherwise prints the path.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# Identifier containing SECRET or KEY, then `=` or `:`, then a value.
_SECRETISH = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:SECRET|KEY)[A-Za-z0-9_]*)\s*[:=]\s*\S+"
)


def scrub(text):
    return _SECRETISH.sub(lambda m: f"{m.group(1)}=<redacted>", text)


def pytest_summary(log_text):
    lines = log_text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if "short test summary info" in line.lower():
            start = index
            break
    if start is not None:
        return "\n".join(lines[start:]).strip() or "(empty pytest summary)"
    failed = [line for line in lines if line.startswith("FAILED ")]
    banners = [line for line in lines if line.startswith("=") and line.endswith("=")]
    parts = failed[-20:]
    if banners:
        parts.append(banners[-1])
    return "\n".join(parts) if parts else "(no pytest summary in log)"


def report_sha_line(repo):
    path = pathlib.Path(repo) / "conformance" / "run-report.json"
    if not path.is_file():
        return "(run-report.json absent)"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    inner = ""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        inner = data.get("sha") or data.get("tree") or ""
    if inner:
        return f"sha256:{digest} (report sha: {inner})"
    return f"sha256:{digest}"


def failures_dir(repo):
    return pathlib.Path(repo) / "conformance" / "demos" / "phase-2.5" / "failures"


def write_bundle(repo, exit_code, log_path, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H%M%SZ")
    dest_dir = failures_dir(repo)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stamp}.md"

    log_path = pathlib.Path(log_path)
    if log_path.is_file():
        raw_log = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        raw_log = f"(log not found: {log_path})"
    cleaned = scrub(raw_log)

    body = (
        f"# nightly failure {stamp}\n"
        "\n"
        "This bundle was filed from a local/operator `make nightly` run.\n"
        "It does not run on the Hub host.\n"
        "\n"
        f"Exit code: {exit_code}\n"
        "\n"
        "## pytest summary\n"
        "\n"
        f"{pytest_summary(cleaned)}\n"
        "\n"
        "## run-report.json\n"
        "\n"
        f"{report_sha_line(repo)}\n"
        "\n"
        "## log (scrubbed)\n"
        "\n"
        "```\n"
        f"{cleaned}\n"
        "```\n"
    )
    dest.write_text(body, encoding="utf-8")
    return dest


def _token_present():
    return bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))


def maybe_create_issue(bundle_path):
    if not _token_present() or shutil.which("gh") is None:
        print(bundle_path)
        return None
    title = f"nightly failed {pathlib.Path(bundle_path).stem}"
    subprocess.run(
        ["gh", "issue", "create", "--title", title, "--body-file", str(bundle_path)],
        check=False,
    )
    print(bundle_path)
    return bundle_path


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--log", type=pathlib.Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=None,
        help="Repo root to write under (tests). Defaults to the tree that contains this script.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.exit_code == 0:
        return 0
    repo = args.repo_root if args.repo_root is not None else REPO
    bundle = write_bundle(repo, args.exit_code, args.log)
    maybe_create_issue(bundle)
    return args.exit_code


if __name__ == "__main__":
    sys.exit(main())

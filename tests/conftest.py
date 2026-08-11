import os
import sys

# Fail loud with the FIX in the message, not a tomllib traceback three modules deep.
# (Round-3 finding, found by Joseph running the suite on a 3.10 venv, 2026-08-09.)
if sys.version_info < (3, 11):
    raise SystemExit(
        f"deploy-hub requires Python >= 3.11 (you have {sys.version.split()[0]}: "
        f"{sys.executable}). Recreate the venv: rm -rf .venv && "
        f"python3.12 -m venv .venv && source .venv/bin/activate && "
        f"pip install -r requirements-dev.txt"
    )

import datetime
import json
import pathlib
import subprocess

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
django.setup()


# ── conformance run report (SPEC-gate-integrity §3.2 rule 1) ────────────────
# check.py used to infer coverage from an AST walk, so a marked test could fail,
# be skipped, or sit in a file pytest never collects and the gate still went
# green (round-4 R4-9 probes a/b/c).  This plugin records what the run actually
# did.  No new dependency: it is plain pytest hooks.
#
# Set CONFORMANCE_RUN_REPORT to a path to redirect the report, or to "off" to
# suppress it entirely — that is what a nested pytest invocation (a test that
# shells out to pytest, or to check.py) must do so it cannot clobber the report
# of the run it is executing inside.

REPO = pathlib.Path(__file__).resolve().parent.parent
_OUTCOMES: dict[str, str] = {}


def _run_report_path():
    override = os.environ.get("CONFORMANCE_RUN_REPORT")
    if override is None:
        return REPO / "conformance" / "run-report.json"
    if override.strip().lower() in {"off", "0", "none", ""}:
        return None
    return pathlib.Path(override)


def _git_head():
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - a report with no sha is red downstream, by design
        return ""


def pytest_runtest_logreport(report):
    """Record one outcome per nodeid: passed/failed/error/skipped/xfailed/xpassed."""
    if report.when == "call":
        if hasattr(report, "wasxfail"):
            _OUTCOMES[report.nodeid] = "xfailed" if report.skipped else "xpassed"
        else:
            _OUTCOMES[report.nodeid] = report.outcome
    elif report.failed:  # setup/teardown error — never counts as a pass
        _OUTCOMES[report.nodeid] = "error"
    elif report.when == "setup" and report.skipped:
        _OUTCOMES.setdefault(
            report.nodeid, "xfailed" if hasattr(report, "wasxfail") else "skipped")


# Anything that narrows or truncates the run makes the report describe less than
# the suite. check.py must refuse such a report outright, otherwise every marker
# outside the selection reads as `not-collected` and the real signal drowns.
#
# Round-5 F7: this used to scan `config.invocation_params.args` — the words on the
# command line — so narrowing that arrived any other way was invisible. The reviewer
# reproduced `PYTEST_ADDOPTS="-k test_smoke" pytest -q` writing `full_run: True` over 5
# of 250 outcomes: argv was clean, the selection came from the environment. Read the
# options pytest actually parsed, plus the count of anything deselected during
# collection, so ini `addopts`, PYTEST_ADDOPTS, a plugin and a conftest hook are all
# caught by the same rule.
_DESELECTED = 0


def pytest_deselected(items):
    """Anything removed during collection narrows the run, whoever removed it."""
    global _DESELECTED
    _DESELECTED += len(items)


def _narrowing_reasons(config, exitstatus):
    """Human-readable reasons this session covered less than the whole suite."""
    option = config.option
    reasons = []

    def flag(name, label):
        if getattr(option, name, None):
            reasons.append(label)

    if (getattr(option, "keyword", "") or "").strip():
        reasons.append(f"-k {option.keyword!r}")
    if (getattr(option, "markexpr", "") or "").strip():
        reasons.append(f"-m {option.markexpr!r}")
    if getattr(option, "deselect", None):
        reasons.append(f"--deselect {list(option.deselect)}")
    if getattr(option, "file_or_dir", None):
        reasons.append(f"positional target(s) {list(option.file_or_dir)}")
    if getattr(option, "ignore", None):
        reasons.append(f"--ignore {list(option.ignore)}")
    flag("exitfirst", "-x/--exitfirst")
    flag("last_failed", "--lf/--last-failed")
    flag("failed_first", "--ff/--failed-first")
    flag("stepwise", "--sw/--stepwise")
    flag("collectonly", "--collect-only")
    if int(getattr(option, "maxfail", 0) or 0):
        reasons.append(f"--maxfail={option.maxfail}")
    if _DESELECTED:
        reasons.append(f"{_DESELECTED} test(s) deselected during collection")
    # 0 = all passed, 1 = tests failed; anything else means the session was cut short.
    if int(exitstatus) not in (0, 1):
        reasons.append(f"session ended with exitstatus {int(exitstatus)}")
    return reasons


def pytest_sessionfinish(session, exitstatus):
    path = _run_report_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    reasons = _narrowing_reasons(session.config, exitstatus)
    payload = {
        "schema_version": 1,
        "sha": _git_head(),
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pytest_exitstatus": int(exitstatus),
        "full_run": not reasons,
        "narrowed_by": reasons,
        "invocation_args": [str(a) for a in session.config.invocation_params.args],
        "outcomes": dict(sorted(_OUTCOMES.items())),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")

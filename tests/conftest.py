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
SELECTIVE_OPTS = ("-k", "-m", "--deselect", "-x", "--exitfirst", "--maxfail",
                  "--last-failed", "--lf", "--failed-first", "--ff", "--stepwise", "--sw")


def _is_full_run(config, exitstatus):
    args = [str(a) for a in config.invocation_params.args]
    for arg in args:
        if arg.startswith("-"):
            if any(arg == o or arg.startswith(o + "=") for o in SELECTIVE_OPTS):
                return False
        else:
            return False  # a positional target (path or nodeid) is a selection
    # 0 = all passed, 1 = tests failed; anything else means the session was cut short.
    return int(exitstatus) in (0, 1)


def pytest_sessionfinish(session, exitstatus):
    path = _run_report_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "sha": _git_head(),
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pytest_exitstatus": int(exitstatus),
        "full_run": _is_full_run(session.config, exitstatus),
        "invocation_args": [str(a) for a in session.config.invocation_params.args],
        "outcomes": dict(sorted(_OUTCOMES.items())),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")

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


def pytest_ignore_collect(collection_path, config):
    """T2 live image tests are collected only when explicitly targeted.

    `make test` / lint-and-unit stay the T1 suite. `make test-t2` and
    `pytest tests/test_hub_test_target.py` still collect them. This is
    collection, not a skip: when docker is present and the file is targeted,
    the live tests run.
    """
    path = pathlib.Path(collection_path)
    if path.name != "test_hub_test_target.py":
        return None
    args = [str(a) for a in config.invocation_params.args]
    targeted = any("test_hub_test_target" in pathlib.Path(a).as_posix() for a in args)
    return not targeted

# conformance/gates.py owns the gate machinery this plugin and the gate tests both read
# (N1). `conformance/` deliberately has no __init__.py — it is not an importable package,
# and giving it one would silently add it to the Makefile's $(PY_ROOTS) and so to the
# bandit and log-scrub scan scope. So its directory goes on the path instead, once, here.
if str(REPO / "conformance") not in sys.path:
    sys.path.insert(0, str(REPO / "conformance"))

# And `tests/` itself, so one test module can import another's fixture harness rather
# than growing a second copy of it — `write_repo`/`run_check` in test_conformance_gate.py
# is the throwaway-tree builder every gate test needs.
if str(REPO / "tests") not in sys.path:
    sys.path.insert(0, str(REPO / "tests"))

import gates  # noqa: E402 — the path insert above is its prerequisite

_OUTCOMES: dict[str, str] = {}


def _run_report_path():
    override = os.environ.get("CONFORMANCE_RUN_REPORT")
    if override is None:
        return REPO / "conformance" / "run-report.json"
    if override.strip().lower() in {"off", "0", "none", ""}:
        return None
    return pathlib.Path(override)


# HEAD *and* a fingerprint of the working tree. HEAD alone does not move when a file is
# edited, so a report written before an uncommitted change went on looking fresh to the
# gate, which reads the working tree — round-5 recorded that as a deliberate deferral.


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
        "sha": gates.git_head(REPO),
        "tree": gates.tree_fingerprint(REPO),
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pytest_exitstatus": int(exitstatus),
        "full_run": not reasons,
        "narrowed_by": reasons,
        "invocation_args": [str(a) for a in session.config.invocation_params.args],
        "outcomes": dict(sorted(_OUTCOMES.items())),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")

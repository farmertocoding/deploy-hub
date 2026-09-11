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
import importlib.util
import json
import pathlib

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hub.settings.dev")
django.setup()

# H2: EnrollmentRequiredMiddleware requires this-session OTP (`is_verified()`)
# after a confirmed device exists. T1 tests historically used Client.login /
# force_login after creating a TOTP row, which never wrote otp_device_id.
# Stamp it when a confirmed device is already present so those tests still
# drive the enrolled+verified path. Tests that assert the unverified hole
# pop otp_device_id themselves.
from django.test.client import Client as _DjangoClient  # noqa: E402
from django_otp import DEVICE_ID_SESSION_KEY  # noqa: E402


def _stamp_otp_device(client, user):
    from django_otp import devices_for_user

    if user is None:
        return
    device = next(devices_for_user(user, confirmed=True), None)
    if device is None:
        return
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()


_orig_client_login = _DjangoClient.login
_orig_client_force_login = _DjangoClient.force_login
_GRANT_DEFAULT_MEMBERSHIP = True


def _ensure_test_owner_membership(user):
    """Give logged-in test users an explicit default-workspace owner row.

    Production never auto-grants; tests that assert the zero-membership
    refuse path opt out with ``pytest.mark.no_default_membership``.
    """
    if not _GRANT_DEFAULT_MEMBERSHIP or user is None or not getattr(user, "pk", None):
        return
    from core.models import WorkspaceMembership, default_workspace

    if WorkspaceMembership.objects.filter(user=user).exists():
        return
    WorkspaceMembership.objects.get_or_create(
        workspace=default_workspace(),
        user=user,
        defaults={"role": "owner"},
    )


def _client_login(self, **credentials):
    ok = _orig_client_login(self, **credentials)
    if ok:
        from django.contrib.auth.models import User

        username = credentials.get("username")
        if username:
            user = User.objects.filter(username=username).first()
            _ensure_test_owner_membership(user)
            _stamp_otp_device(self, user)
    return ok


def _client_force_login(self, user, backend=None):
    _ensure_test_owner_membership(user)
    _orig_client_force_login(self, user, backend=backend)
    _stamp_otp_device(self, user)


_DjangoClient.login = _client_login
_DjangoClient.force_login = _client_force_login


def t1_ready_session(client, user):
    """Two confirmed passkeys + hardware_touch_at for RequireRecentTouch tests."""
    import os

    from django.utils import timezone
    from django_otp_webauthn.models import WebAuthnCredential

    for name in ("yk-a", "yk-b"):
        if not WebAuthnCredential.objects.filter(user=user, name=name, confirmed=True).exists():
            WebAuthnCredential.objects.create(
                user=user,
                name=name,
                confirmed=True,
                credential_id=os.urandom(16),
                public_key=os.urandom(32),
                aaguid="00000000-0000-0000-0000-000000000000",
                transports=["usb"],
            )
    session = client.session
    session["hardware_touch_at"] = timezone.now().isoformat()
    session.save()


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

@pytest.fixture(autouse=True)
def _ensure_default_workspace(request):
    """Create the default workspace inside the test transaction.

    Session-scoped setup is truncated by TransactionTestCase, leaving
    DnsAccount.workspace_id=1 without a row. Keep this in-test.
    """
    global _GRANT_DEFAULT_MEMBERSHIP
    previous = _GRANT_DEFAULT_MEMBERSHIP
    _GRANT_DEFAULT_MEMBERSHIP = (
        request.node.get_closest_marker("no_default_membership") is None
    )
    if request.node.get_closest_marker("django_db") is not None:
        request.getfixturevalue("db")
        from core.models import default_workspace

        default_workspace()
    try:
        yield
    finally:
        _GRANT_DEFAULT_MEMBERSHIP = previous


@pytest.fixture(autouse=True)
def _local_source_root_for_t1():
    """Archive/adopt always require a configured root. Tests use tmp_path and the repo."""
    from django.conf import settings

    previous = getattr(settings, "HUB_LOCAL_SOURCE_ROOT", "")
    if settings.configured and not str(previous or "").strip():
        settings.HUB_LOCAL_SOURCE_ROOT = "/"
    yield
    if settings.configured:
        settings.HUB_LOCAL_SOURCE_ROOT = previous


@pytest.fixture(autouse=True)
def _reset_partner_api_enabled_setting():
    """PartnerApiFlag.set_on assigns django.conf.settings, which is process-global.

    mutmut's clean run is a second in-process pytest.main(); a leaked True
    makes test_beat_interval_is_10s_on_probes fail after kill-switch tests.
    """
    from django.conf import settings

    if not settings.configured:
        yield
        return
    settings.PARTNER_API_ENABLED = False
    try:
        yield
    finally:
        if settings.configured:
            settings.PARTNER_API_ENABLED = False


REPO = pathlib.Path(__file__).resolve().parent.parent

# `make test` is `pytest -q -m "not t2 and not t3"`. That deselects live-container
# and Multipass tests so lint-and-unit stays T1-fast, but the nodeids still exist
# in the suite: the plugin records them as skipped so check.py never sees
# `not-collected` (R4-9). The filter is the default T1 gate, not a narrowed run.
_T2_DEFAULT_MARKEXPR = "not t2 and not t3"

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

# SEC-69 exhaust gate (D-061 / C9): captured pytest stdout/stderr/log and
# Celery kwargs, not `make log-scrub`. Loaded from scripts_dev so the
# scanner is not a first-party package under PY_ROOTS.
_EXHAUST_SPEC = importlib.util.spec_from_file_location(
    "hub_exhaust", REPO / "scripts_dev" / "exhaust.py"
)
_EXHAUST = importlib.util.module_from_spec(_EXHAUST_SPEC)
sys.modules["hub_exhaust"] = _EXHAUST
_EXHAUST_SPEC.loader.exec_module(_EXHAUST)
_EXHAUST.install_celery_wrap()


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_makereport(item, call):
    """Fail a test whose captured exhaust carries the vault plaintext marker."""
    report = yield
    if call.when == "call":
        hits = _EXHAUST.scan_report_captures(report)
        if hits:
            report.outcome = "failed"
            report.longrepr = (
                "SEC-69 exhaust: vault plaintext marker in captured "
                + ", ".join(hits)
            )
    return report


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
_DESELECTED_T2 = 0
_DESELECTED_T3 = 0


def pytest_deselected(items):
    """Record not-run collected items as skipped; count leftover narrowing."""
    global _DESELECTED, _DESELECTED_T2, _DESELECTED_T3
    _DESELECTED += len(items)
    for item in items:
        _OUTCOMES.setdefault(item.nodeid, "skipped")
        if item.get_closest_marker("t2"):
            _DESELECTED_T2 += 1
        if item.get_closest_marker("t3"):
            _DESELECTED_T3 += 1


def _normalized_markexpr(option):
    return " ".join((getattr(option, "markexpr", "") or "").split())


def _narrowing_reasons(config, exitstatus):
    """Human-readable reasons this session covered less than the whole suite."""
    option = config.option
    reasons = []

    def flag(name, label):
        if getattr(option, name, None):
            reasons.append(label)

    if (getattr(option, "keyword", "") or "").strip():
        reasons.append(f"-k {option.keyword!r}")
    markexpr = _normalized_markexpr(option)
    if markexpr and markexpr != _T2_DEFAULT_MARKEXPR:
        reasons.append(f"-m {markexpr!r}")
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
    extra_deselected = _DESELECTED
    if markexpr == _T2_DEFAULT_MARKEXPR:
        extra_deselected -= _DESELECTED_T2
        extra_deselected -= _DESELECTED_T3
    if extra_deselected > 0:
        reasons.append(f"{extra_deselected} test(s) deselected during collection")
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

"""Django scanner module: fleet-norm (uv+ASGI+sidecars), legacy blockers, pip/WSGI."""
import os
import pathlib
import shutil

import pytest

from scanner import core
from scanner.modules import django as dj

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "django"
UV_ASGI = FIXTURES / "uv_asgi"
LEGACY_BAD = FIXTURES / "legacy_bad"
PIP_WSGI = FIXTURES / "pip_wsgi"


def _by_id(results):
    return {c.id: c for c in results}


@pytest.mark.req("SCAN-DJANGO-UV")
def test_uv_asgi_detected_and_manifest_source_recorded_as_uv():
    """J7: pyproject.toml + uv.lock is the fleet norm — recognized, recorded,
    and never mistaken for a missing dependency manifest."""
    assert dj.module.detect(UV_ASGI) is True
    checks = _by_id(dj.module.checks(UV_ASGI))
    dep = checks["django.dependency-manifest"]
    assert dep.tier == "ok"
    assert "uv" in dep.detail
    blockers = [c.id for c in checks.values() if c.tier == "blocker"]
    assert blockers == [], f"fleet-norm fixture must not fire blockers: {blockers}"
    # uv.lock counts as pinning — no unpinned-requirements warning either.
    assert checks["django.deps-pinned"].tier == "ok"
    assert checks["django.runtime-versions"].tier == "ok"


@pytest.mark.req("SCAN-DJANGO-ASGI")
def test_uv_asgi_service_command_is_asgi_and_sidecars_become_jobs():
    """J7: ASGI-only serving is universal — the manifest command must stay
    daphne/uvicorn (never a gunicorn default), and compose sidecars (celery
    worker/beat, one-shot migrate) must land as components.jobs entries."""
    report = core.scan(UV_ASGI)
    assert "django" in report["modules"]
    svc = report["manifest_draft"]["components"]["service"]
    assert svc["kind"] == "django"
    assert svc["port"] == 8000
    assert svc["command"][0] in ("daphne", "uvicorn")
    assert "gunicorn" not in " ".join(svc["command"])
    jobs = {j["name"]: j for j in report["manifest_draft"]["components"]["jobs"]}
    assert {"worker", "beat", "migrate"} <= set(jobs)
    assert jobs["worker"]["kind"] == "long_running"
    assert jobs["beat"]["kind"] == "long_running"
    assert jobs["migrate"]["kind"] == "one_shot"
    assert "redis" not in jobs  # infra images are not project jobs
    mode = next(c for c in report["checks"] if c["id"] == "django.server-mode")
    assert mode["tier"] == "ok" and "ASGI" in mode["detail"]
    sidecars = next(c for c in report["checks"] if c["id"] == "django.sidecars")
    assert sidecars["tier"] == "ok"


# ── R4-11 WI-7: the version window's edges, not just its interior ──────────────
#
# SCAN-DJANGO-UV claims tolerance of "Python 3.12–3.14 and Django 5.2–6". The only
# assertion was `django.runtime-versions == ok` on the uv_asgi fixture, which declares
# 3.12 / 5.2 — one interior point. Widening the window to accept every version left
# that test green, so nothing pinned where the window ends.

def _uv_project(tmp_path, requires_python, django_spec):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "manage.py").write_text("#!/usr/bin/env python\n")
    (root / "uv.lock").write_text("version = 1\n")
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"x\"\n"
        f"requires-python = \">={requires_python}\"\n"
        f"dependencies = [\"django>={django_spec}\"]\n")
    return root


@pytest.mark.req("SCAN-DJANGO-UV")
@pytest.mark.parametrize("python_v,django_v", [
    ("3.12", "5.2"),   # both lower edges
    ("3.14", "5.2"),   # upper Python edge
    ("3.12", "6.0"),   # Django 6, the top of the stated range
    ("3.14", "6.9"),   # both upper edges
])
def test_issue_r4_11_versions_inside_the_window_tier_ok(tmp_path, python_v, django_v):
    root = _uv_project(tmp_path, python_v, django_v)
    check = _by_id(dj.module.checks(root))["django.runtime-versions"]
    assert check.tier == "ok", f"{python_v}/{django_v}: {check.detail}"


@pytest.mark.req("SCAN-DJANGO-UV")
@pytest.mark.parametrize("python_v,django_v", [
    ("3.11", "5.2"),   # below the Python floor
    ("3.15", "5.2"),   # above the Python ceiling
    ("3.12", "5.1"),   # below the Django floor
    ("3.12", "7.0"),   # above the Django ceiling — "5.2–6" ends before 7
])
def test_issue_r4_11_versions_outside_the_window_tier_advice(tmp_path, python_v,
                                                             django_v):
    root = _uv_project(tmp_path, python_v, django_v)
    check = _by_id(dj.module.checks(root))["django.runtime-versions"]
    assert check.tier == "advice", f"{python_v}/{django_v}: {check.detail}"
    assert "3.12" in check.fix_hint and "5.2" in check.fix_hint


# ── R4-11 WI-1: ASGI inferred from DEPENDENCIES, not copied from a compose argv ──

def _asgi_by_deps_project(tmp_path, deps, compose_command=None):
    """A Django project that is ASGI by its dependency manifest alone.

    Deliberately ships NO explicit daphne/uvicorn `command:` in compose — the real
    fleet shape when the server lives in the image default or a Dockerfile CMD.
    `_server_shape` returns a compose argv before it ever reaches the
    dependency-based branch, so a fixture with an explicit command proves only
    passthrough (R4-11 WI-2: disabling the whole synthesis branch left the two
    SCAN-DJANGO-ASGI-marked tests, and the phase-1 acceptance module, green).
    """
    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "manage.py").write_text("#!/usr/bin/env python\n")
    (root / "config" / "__init__.py").write_text("")
    (root / "config" / "asgi.py").write_text(
        "import os\nfrom django.core.asgi import get_asgi_application\n"
        "application = get_asgi_application()\n")
    (root / "config" / "wsgi.py").write_text(
        "from django.core.wsgi import get_wsgi_application\n"
        "application = get_wsgi_application()\n")
    (root / "config" / "settings.py").write_text(
        "import os\nSECRET_KEY = os.environ['DJANGO_SECRET_KEY']\n")
    (root / "requirements.txt").write_text(deps)
    web = "  web:\n    image: app\n"
    if compose_command:
        web += f"    command: {compose_command}\n"
    (root / "docker-compose.yml").write_text("services:\n" + web)
    return root


@pytest.mark.req("SCAN-DJANGO-ASGI")
def test_issue_r4_11_channels_deps_alone_synthesize_a_daphne_command(tmp_path):
    """Channels/daphne in the dependency manifest, no server argv anywhere: the
    manifest command must still be ASGI, never a gunicorn default."""
    root = _asgi_by_deps_project(
        tmp_path, "Django==5.2.4\nchannels==4.1.0\ndaphne==4.1.2\n")
    frag = dj.module.manifest_fragment(root)
    command = frag["components"]["service"]["command"]
    assert command[0] == "daphne", command
    assert "gunicorn" not in " ".join(command)
    assert "config.asgi:application" in command
    mode = _by_id(dj.module.checks(root))["django.server-mode"]
    assert mode.detail.startswith("ASGI"), mode.detail


@pytest.mark.req("SCAN-DJANGO-ASGI")
def test_issue_r4_11_uvicorn_without_daphne_synthesizes_a_uvicorn_command(tmp_path):
    """The uvicorn-only sub-branch: uvicorn in deps, no daphne, no compose argv."""
    root = _asgi_by_deps_project(tmp_path, "Django==5.2.4\nuvicorn==0.30.6\n")
    command = dj.module.manifest_fragment(root)["components"]["service"]["command"]
    assert command[0] == "uvicorn", command
    assert "gunicorn" not in " ".join(command)
    assert "config.asgi:application" in command


@pytest.mark.req("SCAN-DJANGO-ASGI")
def test_issue_r4_11_channels_without_a_named_server_still_serves_asgi(tmp_path):
    """Channels alone (no daphne/uvicorn pin) is still an ASGI project — the
    `channels` half of the disjunction, which no test exercised either."""
    root = _asgi_by_deps_project(tmp_path, "Django==5.2.4\nchannels==4.1.0\n")
    command = dj.module.manifest_fragment(root)["components"]["service"]["command"]
    assert command[0] == "daphne", command
    assert "gunicorn" not in " ".join(command)


@pytest.mark.req("SCAN-DJANGO-ASGI")
def test_issue_r4_11_a_wsgi_only_project_is_not_pushed_onto_asgi(tmp_path):
    """Negative case, so the tests above cannot be satisfied by hardcoding ASGI:
    no Channels, no daphne, no uvicorn ⇒ the classic gunicorn shape."""
    root = _asgi_by_deps_project(tmp_path, "Django==5.2.4\ngunicorn==22.0.0\n")
    command = dj.module.manifest_fragment(root)["components"]["service"]["command"]
    assert command[0] == "gunicorn", command
    assert "config.wsgi:application" in command


def test_legacy_bad_fires_debug_secret_and_runserver_blockers():
    checks = {c.id: c.tier for c in dj.module.checks(LEGACY_BAD)}
    assert checks["django.debug-hardcoded"] == "blocker"
    assert checks["django.secret-key-literal"] == "blocker"
    assert checks["django.runserver"] == "blocker"


def test_legacy_bad_fires_the_warnings():
    checks = {c.id: c.tier for c in dj.module.checks(LEGACY_BAD)}
    for cid in ("django.settings-shape", "django.allowed-hosts", "django.db-engine",
                "django.static-root", "django.security-settings", "django.deps-pinned"):
        assert checks[cid] == "warning", f"{cid} should be a warning, got {checks[cid]}"
    # requirements.txt exists, so the manifest-source blocker must NOT fire.
    assert checks["django.dependency-manifest"] == "ok"


def test_pip_wsgi_passes_and_gets_a_gunicorn_command():
    checks = dj.module.checks(PIP_WSGI)
    blockers = [c.id for c in checks if c.tier == "blocker"]
    warnings = [c.id for c in checks if c.tier == "warning"]
    assert blockers == []
    assert warnings == []
    frag = dj.module.manifest_fragment(PIP_WSGI)
    assert frag["components"]["service"]["command"][0] == "gunicorn"
    assert "config.wsgi:application" in frag["components"]["service"]["command"]
    assert frag["dependency_source"] == "requirements"
    assert frag["components"]["jobs"] == []


def test_detect_is_false_on_an_empty_tree(tmp_path):
    assert dj.module.detect(tmp_path) is False
    assert "django" not in [m.name for m in core.detect_modules(tmp_path)]


# ── J7 remaining shape checks (ecommerce + fb-group-poster, 2026-08-20) ────────
#
# Joseph 2026-08-09: both are not deploy candidates, so §V12 clause (a) only —
# framework, serving process, which scanner module. The folders were not
# connected when the first four inventory rows were written. Connected, they
# are: a leftover venv, and a startproject WSGI app. Neither is a third
# framework. These tests pin that the module list still matches that reality.


def test_j7_a_venv_with_django_installed_is_not_a_django_project(tmp_path):
    """ecommerce: pyvenv.cfg + site-packages/django, no manage.py, no
    dependency manifest. Installed Django is not a project — detect must
    stay false even though the skip set names `.venv`/`venv`, not this
    directory, and the walk is free to open `lib/`."""
    root = tmp_path / "ecommerce"
    (root / "bin").mkdir(parents=True)
    (root / "include").mkdir()
    sp = root / "lib" / "python3.10" / "site-packages" / "django"
    sp.mkdir(parents=True)
    (sp / "__init__.py").write_text("# installed Django, not a project\n")
    (root / "pyvenv.cfg").write_text(
        "home = /usr/bin\ninclude-system-site-packages = false\nversion = 3.10.6\n"
    )
    (root / "bin" / "django-admin").write_text("")
    assert dj.module.detect(root) is False
    assert core.detect_modules(root) == []


@pytest.mark.req("SCAN-DJANGO-ASGI")
def test_j7_startproject_asgi_py_without_channels_stays_wsgi(tmp_path):
    """fb-group-poster: `django-admin startproject` writes asgi.py with
    `get_asgi_application()` and no ProtocolTypeRouter, no Channels, no
    requirements.txt, no compose. That is WSGI. The existing negative
    case lists gunicorn in requirements and ships a compose file — this
    one does not, so a "gunicorn in deps ⇒ WSGI" rewrite cannot hide
    here."""
    root = tmp_path / "fbposter"
    (root / "fbposter").mkdir(parents=True)
    (root / "manage.py").write_text("#!/usr/bin/env python\n")
    (root / "fbposter" / "__init__.py").write_text("")
    (root / "fbposter" / "asgi.py").write_text(
        "import os\nfrom django.core.asgi import get_asgi_application\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fbposter.settings')\n"
        "application = get_asgi_application()\n"
    )
    (root / "fbposter" / "wsgi.py").write_text(
        "import os\nfrom django.core.wsgi import get_wsgi_application\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fbposter.settings')\n"
        "application = get_wsgi_application()\n"
    )
    (root / "fbposter" / "settings.py").write_text(
        "SECRET_KEY = 'x'\nDEBUG = True\n"
        "WSGI_APPLICATION = 'fbposter.wsgi.application'\n"
    )
    assert dj.module.detect(root) is True
    command = dj.module.manifest_fragment(root)["components"]["service"]["command"]
    assert command[0] == "gunicorn", command
    assert "fbposter.wsgi:application" in command
    assert "gunicorn" in " ".join(command)
    mode = _by_id(dj.module.checks(root))["django.server-mode"]
    assert "WSGI" in mode.detail, mode.detail


@pytest.mark.req("SEC-SCAN-NOEXEC")
def test_sandbox_checks_are_emitted_as_specs_not_run():
    specs = {s.id: s for s in dj.module.sandbox_checks(UV_ASGI)}
    assert set(specs) == {"django.check-deploy", "django.migrations-check",
                          "django.collectstatic"}
    for spec in specs.values():
        assert isinstance(spec, core.SandboxSpec)
        assert spec.command[:2] == ["python", "manage.py"]
        assert spec.as_result().tier == "pending_sandbox"


def test_wizard_questions_cover_domain_exposure_db_and_env_secrets():
    qs = {q.id: q for q in dj.module.wizard_questions(UV_ASGI)}
    assert qs["django.domain"].kind == "text"
    assert set(qs["django.exposure"].choices) == {"public", "mesh_only"}
    assert qs["django.db"].kind == "choice"
    assert qs["django.env.DJANGO_SECRET_KEY"].kind == "secret"
    assert qs["django.env.POSTGRES_PASSWORD"].kind == "secret"
    assert qs["django.env.DJANGO_ALLOWED_HOSTS"].kind == "text"
    assert "django.env.DJANGO_SETTINGS_MODULE" not in qs


def test_healthz_route_maps_to_liveness_path():
    assert dj.module.manifest_fragment(UV_ASGI)["healthz"]["liveness_path"] == "/healthz"
    assert dj.module.manifest_fragment(LEGACY_BAD)["healthz"]["liveness_path"] is None


def test_csrf_trusted_origins_advice_fires_on_spa_without_the_setting(tmp_path):
    (tmp_path / "manage.py").write_text("# manage\n")
    (tmp_path / "requirements.txt").write_text("Django==5.2.4\ndjango-cors-headers==4.4.0\n")
    (tmp_path / "settings.py").write_text(
        "import os\nSECRET_KEY = os.environ['KEY']\nSTATIC_ROOT = '/srv/static'\n")
    checks = _by_id(dj.module.checks(tmp_path))
    assert checks["django.csrf-trusted-origins"].tier == "advice"


@pytest.mark.req("SCAN-DJANGO-ASGI")
def test_nested_project_root_with_repo_root_compose(tmp_path):
    """Live-demo finding (2026-08-04 real-repo scans): manage.py nests in backend/
    while compose lives at the repo root — all four J7 projects. Detection must
    find the nested root AND sidecar discovery must still see the root compose."""
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "manage.py").write_text("#!/usr/bin/env python\n")
    (tmp_path / "backend" / "settings.py").write_text(
        "import os\nDEBUG = os.environ.get('DEBUG') == '1'\n")
    (tmp_path / "docker-compose.prod.yml").write_text(
        "services:\n"
        "  web:\n    image: app\n    command: daphne -b 0.0.0.0 config.asgi:application\n"
        "  worker:\n    image: app\n    command: celery -A config worker\n"
        "  migrate:\n    image: app\n    command: python manage.py migrate\n"
        "    restart: \"no\"\n")
    from scanner.modules.django import module

    assert module.detect(tmp_path)
    assert module.project_root(tmp_path).name == "backend"
    frag = module.manifest_fragment(tmp_path)
    jobs = {j["name"] for j in frag["components"]["jobs"]}
    assert "worker" in jobs and "migrate" in jobs


def test_decouple_config_counts_as_env_driven(tmp_path):
    """Live-demo finding: SATURDAYS uses python-decouple — a single settings.py
    reading config() is env-driven, not 'hardcoded'."""
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    (tmp_path / "settings.py").write_text(
        "from decouple import config\nSECRET_KEY = config('SECRET_KEY')\n"
        "DEBUG = config('DEBUG', default=False, cast=bool)\n")
    from scanner.modules.django import module

    results = {c.id: c for c in module.checks(tmp_path)}
    shape = results["django.settings-shape"]
    assert shape.tier != "warning", shape.detail


# ── D-008: dev-fallback secrets that prod provably rejects (Joseph, 2026-08-09) ──

def _proj(tmp_path, base_body, prod_body):
    root = tmp_path / "proj"
    settings = root / "config" / "settings"
    settings.mkdir(parents=True)
    (root / "manage.py").write_text("#!/usr/bin/env python\n")
    (root / "requirements.txt").write_text("Django==5.2\n")
    (settings / "__init__.py").write_text("")
    (settings / "base.py").write_text(base_body)
    (settings / "prod.py").write_text(prod_body)
    return root


def _tiers(root):
    return {c.id: c for c in dj.module.checks(root)}


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_d008_dev_fallback_with_prod_hard_fail_is_a_warning(tmp_path):
    """The E-invoice shape: a high-entropy dev key committed in base.py, and prod
    reassigning the same NAME from os.environ[...] subscript — a boot failure without
    the real value. Blocker means "will not deploy correctly"; this deploys correctly,
    so it tiers as warning-with-context (D-008, chosen over Blocker and
    proof-dependent tiers)."""
    root = _proj(
        tmp_path,
        base_body=(
            "FIELD_ENCRYPTION_KEYS = "
            "['aXb9Qz3kLm8Rt2Yw6Fh1Jd4Ns7Pv0Cg5Ke9Ub3Xq2Wz8Ma6=']\n"
        ),
        prod_body=(
            "import os\nfrom .base import *  # noqa\n"
            "FIELD_ENCRYPTION_KEYS = os.environ['FIELD_ENCRYPTION_KEYS'].split(',')\n"
        ),
    )
    checks = _tiers(root)
    assert "django.secret-key-literal" not in checks or \
        checks["django.secret-key-literal"].tier != "blocker"
    fallback = checks["django.secret-dev-fallback"]
    assert fallback.tier == "warning"
    assert "FIELD_ENCRYPTION_KEYS" in fallback.detail
    assert "rotate" in fallback.fix_hint
    assert "git history" in fallback.fix_hint


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_d008_literal_without_prod_guard_stays_a_blocker(tmp_path):
    """The downgrade requires the evidence. No hard-fail reassignment, no mercy."""
    root = _proj(
        tmp_path,
        base_body="SECRET_KEY = 'committed-and-actually-used-in-prod'\n",
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "blocker"
    assert "django.secret-dev-fallback" not in checks


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_d008_env_get_with_default_is_not_hard_fail(tmp_path):
    """`os.environ.get('X', literal)` boots happily WITH the literal — the exact
    opposite of the evidence D-008 requires. Must stay a blocker."""
    root = _proj(
        tmp_path,
        base_body="SECRET_KEY = 'dev-only-fallback-key-value'\n",
        prod_body=(
            "import os\nfrom .base import *  # noqa\n"
            "SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-only-fallback-key-value')\n"
        ),
    )
    assert _tiers(root)["django.secret-key-literal"].tier == "blocker"


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_d008_mixed_project_reports_both(tmp_path):
    """One guarded name and one unguarded name: the project honestly carries the
    blocker AND the warning — the downgrade is per-offender, not per-project."""
    root = _proj(
        tmp_path,
        base_body=(
            "FIELD_ENCRYPTION_KEYS = "
            "['aXb9Qz3kLm8Rt2Yw6Fh1Jd4Ns7Pv0Cg5Ke9Ub3Xq2Wz8Ma6=']\n"
            "API_SIGNING_TOKEN = 'this-one-nobody-guards'\n"
        ),
        prod_body=(
            "import os\nfrom .base import *  # noqa\n"
            "FIELD_ENCRYPTION_KEYS = os.environ['FIELD_ENCRYPTION_KEYS'].split(',')\n"
        ),
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "blocker"
    assert "API_SIGNING_TOKEN" in checks["django.secret-key-literal"].detail
    assert checks["django.secret-dev-fallback"].tier == "warning"
    assert "FIELD_ENCRYPTION_KEYS" in checks["django.secret-dev-fallback"].detail


# ── D-010: the common core suite reaches Django scan reports ───────────────────
#
# Everything below is REPORT-level (`core.scan`), never `module.checks()`: after
# D-010 the core suite is composed by the registry, so a module's own `checks()` is
# deliberately core-free. The module-level tests above stay as they are.
#
# The defect (SPEC-django-common-checks.md): django's `checks()` never called
# `common_checks`, and nothing composed it either, so a Django scan report carried
# none of the seven `core.*` checks. Every project in the fleet is Django.


def _report_by_id(root):
    return {c["id"]: c for c in core.scan(root)["checks"]}


def test_committed_env_secret_blocks_a_django_scan(tmp_path):
    """The headline defect, verbatim: a Django project with a committed `.env`
    holding an AWS access key scanned CLEAN, while the byte-identical Node repo got
    a `core.secret-scan` blocker. Blocker-tier evidence, silently absent.

    The `.env` is materialized at test time rather than shipped as a fixture — the
    repo's own .gitignore ignores `.env` everywhere (same pattern as the
    `secret_tree` fixture in test_scanner_fallbacks.py).
    """
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    (tmp_path / "requirements.txt").write_text("Django==5.2\n")
    (tmp_path / "settings.py").write_text(
        "import os\nSECRET_KEY = os.environ['DJANGO_SECRET_KEY']\n")
    (tmp_path / ".env").write_text("AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\n")

    report = core.scan(tmp_path)
    assert "django" in report["modules"]
    secret = _report_by_id(tmp_path)["core.secret-scan"]
    assert secret["tier"] == "blocker", secret
    # N7 reworded the evidence line — the scan reads a tree and cannot see git, so it
    # reports the file's presence rather than asserting it is committed.
    assert ".env file present in the scan tree" in secret["detail"]
    assert report["summary"]["blocker"] >= 1


def test_a_django_scan_surfaces_the_exposure_auth_check(tmp_path):
    """SCAN-M4-EXPOSURE-AUTH's warning clause, on the django side. Named in the
    amended waiver as the proof that retires clause (b). Deliberately unmarked
    while the blocker-escalation clause of that requirement stays unbuilt.

    The silencing half used to be asserted against UV_ASGI, which carries no
    authentication whatsoever — it passed on the substring `session` inside
    `SESSION_COOKIE_SECURE = True` (D-010 follow-up item 7). It now takes a tree that
    actually authenticates someone.
    """
    res = _report_by_id(LEGACY_BAD)["core.exposure-auth"]
    assert res["tier"] == "warning"
    assert "no authentication detected" in res["detail"]

    authed = tmp_path / "authed"
    shutil.copytree(UV_ASGI, authed)
    (authed / "config" / "views.py").write_text(
        "from django.contrib.auth.decorators import login_required\n\n\n"
        "@login_required\ndef dashboard(request):\n    return request.user\n",
        encoding="utf-8")
    checks = {c["id"]: c for c in core.scan(authed)["checks"]}
    assert checks["core.exposure-auth"]["tier"] == "ok", (
        "a login_required view did not register as an authentication indicator")


def test_uv_asgi_scan_carries_the_core_suite_with_one_honest_warning():
    """The fleet-norm fixture: every core check passes except the one that should not.

    The `.gitignore` and `tests/smoke.py` here are stub-artifact fixes — all four
    inventoried fleet repos ship both, so their absence was fixture noise, not a
    finding. `core.exposure-auth` is different: this project installs only
    `staticfiles` and `channels`, has no `django.contrib.auth`, no
    `AuthenticationMiddleware` and no login view, so "no authentication detected" is
    simply true. It read `ok` until D-010 follow-up item 7 because the auth-indicator
    regex matched the substring `session` in `SESSION_COOKIE_SECURE = True` — which
    means every project that passed `django.security-settings` passed this check for
    free, whatever its actual auth.

    The fixture is deliberately NOT given an auth stub to make this green: inventing
    evidence so a check passes is the failure mode this whole check exists to catch.
    """
    checks = _report_by_id(UV_ASGI)
    core_tiers = {i: c["tier"] for i, c in checks.items() if i.startswith("core.")}
    assert core_tiers == {
        "core.secret-scan": "ok", "core.lockfile": "ok", "core.gitignore": "ok",
        "core.tests-exist": "ok", "core.healthz": "ok", "core.digest-pins": "ok",
        "core.exposure-auth": "warning",
    }
    assert "SESSION_COOKIE_SECURE" in (
        (UV_ASGI / "config" / "settings" / "prod.py").read_text(encoding="utf-8")), (
        "the fixture no longer carries the setting whose substring produced the old "
        "false `ok` — this test's whole point is that it no longer suffices")


def test_legacy_bad_scan_surfaces_the_core_findings():
    """The deliberately-bad fixture: every one of these is a GENUINE finding the
    report used to be silent about. The fixture is untouched — its gaps are the
    point."""
    checks = _report_by_id(LEGACY_BAD)
    core_tiers = {i: c["tier"] for i, c in checks.items() if i.startswith("core.")}
    assert core_tiers == {
        "core.secret-scan": "blocker", "core.lockfile": "ok",
        "core.gitignore": "warning", "core.tests-exist": "advice",
        "core.healthz": "advice", "core.digest-pins": "warning",
        "core.exposure-auth": "warning",
    }
    assert "python:3.11-slim" in checks["core.digest-pins"]["detail"]
    # `core.secret-scan` read `ok` here until D-010 follow-up item 5, on a fixture whose
    # settings.py carries a real committed Django SECRET_KEY: the value contains the
    # marker `insecure`, and a marker used to excuse a value outright. `django-insecure-`
    # is the prefix Django's own startproject writes, so the marker was hiding the single
    # most common real finding there is. In this fixture `django.secret-key-literal`
    # caught it anyway; in any file that is not a settings module, nothing did.
    assert "settings.py:5" in checks["core.secret-scan"]["detail"]


def test_pip_wsgi_scan_is_clean_apart_from_the_auth_warning():
    """The classic pip/WSGI fixture passes at report level too. `core.healthz` is
    `advice` and stays that way: a classic project with no health route earns
    exactly the §E9 advice — a genuine finding, not a fixture gap."""
    report = core.scan(PIP_WSGI)
    loud = [c["id"] for c in report["checks"] if c["tier"] in ("blocker", "warning")]
    # core.exposure-auth is the one warning, and it is earned: like uv_asgi, this
    # fixture has no authentication at all and used to pass on the substring `session`
    # inside SESSION_COOKIE_SECURE (D-010 follow-up item 7).
    assert loud == ["core.exposure-auth"]
    checks = {c["id"]: c for c in report["checks"]}
    assert {i for i in checks if i.startswith("core.")} == {
        "core.secret-scan", "core.lockfile", "core.gitignore", "core.tests-exist",
        "core.healthz", "core.digest-pins", "core.exposure-auth",
    }
    assert checks["core.healthz"]["tier"] == "advice"


# ── N5: dotted-path settings lists read as committed secret material ───────────
#
# Found by the R4-10 demo re-record (2026-08-11), the first run of the widened
# checks against the real fleet. `django.secret-key-literal` fired a BLOCKER on
# `INSTALLED_APPS` and `MIDDLEWARE` in all three production repos, and on
# `PASSWORD_HASHERS` in one. Two independent causes, both in `_check_secret_key`:
#
#   1. `_string_literal` JOINS a list's elements (added for D-008's real shape,
#      `FIELD_ENCRYPTION_KEYS = ["<fernet>"]`), so entropy is judged on the
#      concatenation. A 12-app INSTALLED_APPS joins to ~300 chars of mixed
#      lowercase and dots — over the 24-char floor and over 4.0 bits — and is
#      indistinguishable from key material by that measure.
#   2. The `secretish` axis matches a NAME substring and accepts ANY non-empty
#      string value, so `PASSWORD_HASHERS` (contains `PASS`) and
#      `_WEAK_SECRET_KEYS` (contains `SECRET`) qualify on the name alone.
#
# Why it matters more than its size: this is a blocker-tier false positive on
# every Django project that exists, i.e. the whole fleet, and a blocker the
# operator learns to click past is the exact mechanism D-011r named as the reason
# to reconsider the heuristic tier. A finding that is always wrong trains bypass.
#
# The fix must not undo D-008: a single-element list holding one real Fernet key
# is the case the joining was written for and still has to block.


def _fleet_settings_body():
    """A settings module in the shape all three real repos share."""
    return (
        "INSTALLED_APPS = [\n"
        "    'django.contrib.admin',\n"
        "    'django.contrib.auth',\n"
        "    'django.contrib.contenttypes',\n"
        "    'django.contrib.sessions',\n"
        "    'django.contrib.messages',\n"
        "    'django.contrib.staticfiles',\n"
        "    'rest_framework',\n"
        "    'corsheaders',\n"
        "    'django_celery_beat',\n"
        "    'apps.tenants',\n"
        "    'apps.billing',\n"
        "    'apps.webhooks',\n"
        "]\n"
        "MIDDLEWARE = [\n"
        "    'django.middleware.security.SecurityMiddleware',\n"
        "    'corsheaders.middleware.CorsMiddleware',\n"
        "    'django.contrib.sessions.middleware.SessionMiddleware',\n"
        "    'django.middleware.common.CommonMiddleware',\n"
        "    'django.middleware.csrf.CsrfViewMiddleware',\n"
        "    'django.contrib.auth.middleware.AuthenticationMiddleware',\n"
        "]\n"
        "AUTHENTICATION_BACKENDS = [\n"
        "    'django.contrib.auth.backends.ModelBackend',\n"
        "    'apps.tenants.backends.TenantBackend',\n"
        "]\n"
        "PASSWORD_HASHERS = [\n"
        "    'django.contrib.auth.hashers.Argon2PasswordHasher',\n"
        "    'django.contrib.auth.hashers.PBKDF2PasswordHasher',\n"
        "]\n"
    )


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n5_dotted_path_settings_lists_are_not_secret_material(tmp_path):
    """A settings module holding nothing but Django's own dotted-path lists is
    clean. No blocker, no dev-fallback warning, and no mention of the four names."""
    root = _proj(
        tmp_path,
        base_body=(
            "import os\n"
            + _fleet_settings_body()
            + "SECRET_KEY = os.environ['DJANGO_SECRET_KEY']\n"
        ),
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    blockers = [c.id for c in checks.values() if c.tier == "blocker"]
    assert blockers == [], f"dotted-path settings must not block: {blockers}"
    assert "django.secret-dev-fallback" not in checks
    assert checks["django.secret-key-literal"].tier == "ok"


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n5_a_weak_secret_keys_denylist_is_not_committed_material(tmp_path):
    """E-invoice prod.py, verbatim shape: `_WEAK_SECRET_KEYS = {"dev-insecure-
    key-change-me", "change-me", ""}` is a membership denylist of known-weak
    placeholders, not a credential. N5's neighbouring test named the identifier
    in a docstring and assigned PASSWORD_HASHERS instead; the 2026-08-20 demo
    still blocked because SECRET is a substring and the name axis accepted any
    non-empty literal."""
    root = _proj(
        tmp_path,
        base_body="import os\nSECRET_KEY = os.environ['DJANGO_SECRET_KEY']\n",
        prod_body=(
            "import os\nfrom .base import *  # noqa\n"
            "SECRET_KEY = os.environ['DJANGO_SECRET_KEY']\n"
            "_WEAK_SECRET_KEYS = {'dev-insecure-key-change-me', 'change-me', ''}\n"
        ),
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "ok", \
        checks["django.secret-key-literal"].detail


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n5_a_weak_named_scalar_password_still_blocks(tmp_path):
    """The denylist skip is the collection shape, not the substring `WEAK`.

    `WEAK_PASSWORD = "hunter2"` is a credential slot the name axis exists to
    catch. `"WEAK" in name` excused it because the skip did not require a
    list/set/tuple of low-entropy members.
    """
    root = _proj(
        tmp_path,
        base_body="WEAK_PASSWORD = 'hunter2'\n",
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "blocker"
    assert "WEAK_PASSWORD" in checks["django.secret-key-literal"].detail


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n5_weak_as_a_substring_of_a_real_secret_name_still_blocks(tmp_path):
    """`UNWEAKENED_SECRET` contains the letters WEAK and the token SECRET."""
    root = _proj(
        tmp_path,
        base_body="UNWEAKENED_SECRET = 'admin123'\n",
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "blocker"
    assert "UNWEAKENED_SECRET" in checks["django.secret-key-literal"].detail


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n5_a_high_entropy_literal_on_a_weak_named_setting_still_blocks(tmp_path):
    """The denylist skip is not a free pass: a WEAK_* name holding a Fernet
    string is committed key material."""
    root = _proj(
        tmp_path,
        base_body=(
            "_WEAK_SECRET_KEYS = "
            "['aXb9Qz3kLm8Rt2Yw6Fh1Jd4Ns7Pv0Cg5Ke9Ub3Xq2Wz8Ma6=']\n"
        ),
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "blocker"
    assert "_WEAK_SECRET_KEYS" in checks["django.secret-key-literal"].detail


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n5_pass_and_secret_named_settings_are_judged_on_their_value(tmp_path):
    """`PASSWORD_HASHERS` matches the `PASS` substring and `_WEAK_SECRET_KEYS`
    matches `SECRET`, but neither holds credential material. The name axis must
    still look at what was assigned."""
    root = _proj(
        tmp_path,
        base_body=(
            "PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher']\n"
        ),
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "ok", \
        checks["django.secret-key-literal"].detail


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n5_one_real_key_among_dotted_paths_still_blocks(tmp_path):
    """The over-correction guard, and the D-008 shape that motivated the joining:
    a single-element list holding one Fernet key blocks, and it blocks even when
    the same module is full of dotted-path lists that must be ignored."""
    root = _proj(
        tmp_path,
        base_body=(
            _fleet_settings_body()
            + "FIELD_ENCRYPTION_KEYS = "
            "['aXb9Qz3kLm8Rt2Yw6Fh1Jd4Ns7Pv0Cg5Ke9Ub3Xq2Wz8Ma6=']\n"
        ),
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    key = checks["django.secret-key-literal"]
    assert key.tier == "blocker"
    assert "FIELD_ENCRYPTION_KEYS" in key.detail
    assert "INSTALLED_APPS" not in key.detail
    assert "MIDDLEWARE" not in key.detail
    assert "PASSWORD_HASHERS" not in key.detail


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n5_short_low_entropy_password_still_blocks(tmp_path):
    """The name axis exists to catch exactly this: a weak value no entropy test
    would ever flag, under a name that says what it is."""
    root = _proj(
        tmp_path,
        base_body="ADMIN_PASSWORD = 'hunter2'\n",
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "blocker"
    assert "ADMIN_PASSWORD" in checks["django.secret-key-literal"].detail


# ── N7: the same exclusion, tightened, and now shared with the core axis ───────
#
# N5's rule shipped here and stopped here; N7 ported it to `fallbacks._check_secret_scan`
# and the adversarial pass on that port found the rule excuses more than import paths.
# A Doppler service token is `dp.st.<config>.<blob>` — dot-STRUCTURED — and was excused
# on BOTH sides, including this one. There is now ONE implementation
# (`fallbacks._is_dotted_identifier_path`) so a hole found on either axis is closed on
# both; `_looks_like_import_path` delegates to it and keeps N5's name and reasoning.

_N7_DOPPLER_TOKEN = "dp.st.prod.aXbYcZdEfGhIjKlMnOpQrStUvWxYzAbCdEfGh"


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n7_a_dot_structured_token_in_a_settings_literal_still_blocks(tmp_path):
    """A Doppler token committed as a settings literal was excused by N5's rule: it
    matches `^ident(\\.ident)+$` exactly, so the shape test dropped it before either
    axis could look. Shape is not provenance."""
    root = _proj(
        tmp_path,
        base_body=f"DOPPLER_TOKEN = '{_N7_DOPPLER_TOKEN}'\n",
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    assert checks["django.secret-key-literal"].tier == "blocker", (
        "a dot-structured credential was excused as an import path")
    assert "DOPPLER_TOKEN" in checks["django.secret-key-literal"].detail


@pytest.mark.req("SCAN-D008-DEV-FALLBACK-TIER")
def test_n7_guard_the_tightened_rule_still_excuses_djangos_own_paths(tmp_path):
    """The over-correction guard for the shared predicate, measured against the two
    tightest real values rather than invented ones.

    `django.contrib.auth.hashers.BCryptSHA256PasswordHasher` is the highest-entropy
    import path found in the fleet — 4.489 bits against the rule's 4.5 ceiling, an
    0.011-bit margin — and its class name is 26 characters against a 28-character
    segment ceiling. If a threshold ever moves, N5's false positive comes back here
    first, on `PASSWORD_HASHERS`, which is where it was found in the first place.
    """
    root = _proj(
        tmp_path,
        base_body=(
            "import os\n"
            + _fleet_settings_body()
            + "PASSWORD_HASHERS = [\n"
              "    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',\n"
              "    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',\n"
              "]\n"
              "AUTH_PASSWORD_VALIDATORS = [\n"
              "    {'NAME': 'django.contrib.auth.password_validation."
              "UserAttributeSimilarityValidator'},\n"
              "    {'NAME': 'django.contrib.auth.password_validation."
              "MinimumLengthValidator'},\n"
              "]\n"
              "SECRET_KEY = os.environ['DJANGO_SECRET_KEY']\n"
        ),
        prod_body="from .base import *  # noqa\nDEBUG = False\n",
    )
    checks = _tiers(root)
    blockers = [c.id for c in checks.values() if c.tier == "blocker"]
    assert blockers == [], f"the tightened rule blocked on Django's own paths: {blockers}"
    assert checks["django.secret-key-literal"].tier == "ok"


# ── R8-6: the walk that ran before every check, for every project ──────────────

# Above CPython 3.11's default recursion limit measured against this code path: 980
# directories deep was fine and 1000 crashed, so the fixture is built past both. It is
# GENERATED rather than committed for the obvious reason and one less obvious one — a
# 1100-directory tree in git is unreviewable, and the depth is the whole point of the
# case, so a reader has to be able to see the number.
_CRASHING_DEPTH = 1100


def _build_deep_tree(base, depth):
    """`base/d/d/d/…` `depth` levels down, with a file at the bottom.

    Built by chdir-and-mkdir rather than by one `mkdir(parents=True)`: the absolute path
    of a 1100-deep tree is longer than Linux's 4096-byte PATH_MAX, so the single-call
    form fails with ENAMETOOLONG before the case under test is even set up.
    """
    base.mkdir(parents=True, exist_ok=True)
    here = os.getcwd()
    try:
        os.chdir(base)
        for _ in range(depth):
            os.mkdir("d")
            os.chdir("d")
        pathlib.Path("leaf.txt").write_text("x", encoding="utf-8")
    finally:
        os.chdir(here)


def _remove_deep_tree(base, depth):
    """Unwind it the same way, so pytest's own tmp_path cleanup never has to.

    `shutil.rmtree` recurses per directory too — the fixture that proves this bug would
    otherwise re-raise it in teardown, out of the test that was supposed to have caught
    it.
    """
    here = os.getcwd()
    try:
        os.chdir(base)
        for _ in range(depth):
            os.chdir("d")
        pathlib.Path("leaf.txt").unlink(missing_ok=True)
        for _ in range(depth):
            os.chdir("..")
            os.rmdir("d")
    finally:
        os.chdir(here)


@pytest.fixture
def vendored_deep_tree(tmp_path):
    """A plain static site with a ~1100-deep chain under `node_modules/`.

    THE VENDORED SHAPE IS THE REALISTIC ONE and it is also what keeps this test cheap:
    every walk in the scan prunes `node_modules`, so after the fix nothing descends it
    and the scan is instant — while `Path.rglob`, which prunes nothing, descended it and
    raised. Unpruned deep trees are covered by the next test, which stops at `detect`
    because a full scan of one costs 30 seconds of walking that proves nothing further.
    """
    root = tmp_path / "site"
    (root / "node_modules").mkdir(parents=True)
    _build_deep_tree(root / "node_modules" / "pkg", _CRASHING_DEPTH)
    (root / "index.html").write_text("<html></html>\n", encoding="utf-8")
    try:
        yield root
    finally:
        _remove_deep_tree(root / "node_modules" / "pkg", _CRASHING_DEPTH)


@pytest.mark.req("SCAN-DJANGO-UV")
def test_issue_r8_6_a_deep_vendored_tree_does_not_crash_the_scan(vendored_deep_tree):
    """`project_root` walked with `Path.rglob("manage.py")`, and CPython 3.11's rglob
    recurses once per directory, so a tree about a thousand deep raised an uncaught
    `RecursionError`. Measured on this tree: 980 deep was fine, 1000 crashed.

    THE SHAPE OF THE BLAST RADIUS IS THE FINDING, not the crash. `detect()` is
    `project_root(root) is not None`, and `core.detect_modules` calls every framework
    module's `detect` before any check runs — so this fired for EVERY project of every
    framework, including the plain static site here, which holds no Python at all. The
    operator got a traceback and no report, with no partial result to fall back on
    because nothing had been computed yet.

    Verified before the fix, on this exact fixture:

        django.detect RecursionError: maximum recursion depth exceeded while calling a
                                      Python object
        core.scan     RecursionError: maximum recursion depth exceeded while calling a
                                      Python object

    …and after it, `detect -> False` and a report whose module list is `['static']`,
    which is the honest answer for an HTML file with a vendored tree beside it.
    """
    assert dj.module.detect(vendored_deep_tree) is False    # must not raise

    report = core.scan(vendored_deep_tree)                  # must not raise
    assert report["modules"] == ["static"], report["modules"]
    assert report["checks"], "a scan that returned no checks is not a scan"


@pytest.mark.req("SCAN-DJANGO-UV")
def test_issue_r8_6_the_fix_is_the_walk_and_not_the_prune_set(tmp_path):
    """The same depth under a directory name nothing prunes.

    Stated separately because the vendored fixture above would pass on a "prune harder"
    fix that left the recursion in place, and `node_modules` is not the only way a tree
    gets deep — a generated fixture directory, an extracted archive, a symlink-free
    build output under a name nobody put in a skip set. `detect` is the assertion
    because `project_root` is depth-capped at 4 now, so it answers without descending
    at all; a full scan of an unpruned 1100-deep tree costs half a minute of walking and
    proves nothing this does not.
    """
    root = tmp_path / "site"
    _build_deep_tree(root / "generated", _CRASHING_DEPTH)
    try:
        (root / "index.html").write_text("<html></html>\n", encoding="utf-8")

        assert dj.module.project_root(root) is None         # must not raise
        assert dj.module.detect(root) is False
    finally:
        _remove_deep_tree(root / "generated", _CRASHING_DEPTH)


@pytest.mark.req("SCAN-DJANGO-UV")
def test_issue_r8_6_a_django_project_beside_a_deep_tree_is_still_found(
        vendored_deep_tree):
    """The other half, and the one that keeps the fix from being "give up on deep
    trees": a real project whose repo happens to contain a deep vendored directory must
    still be detected, with the depth rule it always had."""
    backend = vendored_deep_tree / "backend"
    backend.mkdir()
    (backend / "manage.py").write_text("#!/usr/bin/env python\n", encoding="utf-8")
    (backend / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["django>=5.0"]\n', encoding="utf-8")

    assert dj.module.detect(vendored_deep_tree) is True
    assert dj.module.project_root(vendored_deep_tree) == backend


@pytest.mark.req("SCAN-DJANGO-UV")
def test_issue_r8_6_a_manage_py_deeper_than_the_rule_is_still_not_the_project_root():
    """`max_depth=4` is the walk's translation of `len(rel.parts) <= 4`, so the boundary
    is asserted in both directions — a bound that moved by one would silently adopt a
    vendored project as the root, which is the failure the depth rule exists for."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        at_limit = root / "a" / "b" / "c"
        at_limit.mkdir(parents=True)
        (at_limit / "manage.py").write_text("#\n", encoding="utf-8")
        assert dj.module.project_root(root) == at_limit

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        too_deep = root / "a" / "b" / "c" / "d"
        too_deep.mkdir(parents=True)
        (too_deep / "manage.py").write_text("#\n", encoding="utf-8")
        assert dj.module.project_root(root) is None


@pytest.mark.req("SCAN-DJANGO-UV")
def test_issue_r8_6_a_scan_root_under_a_pruned_directory_name_is_still_scanned(tmp_path):
    """The behaviour change the fix carries, asserted rather than left to a comment.

    `_iter_files` used to prune on `any(part in _SKIP_DIRS for part in p.parts)` over an
    ABSOLUTE path, so a project checked out at `~/build/myapp` matched on its own prefix
    and every Django check saw an empty tree — `ok`, "nothing found", for a project the
    scanner never opened. Pruning during the walk can only skip directories BELOW the
    root.
    """
    root = tmp_path / "build" / "myapp"
    (root / "config").mkdir(parents=True)
    (root / "manage.py").write_text("#\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["django>=5.0"]\n', encoding="utf-8")
    (root / "config" / "settings.py").write_text("DEBUG = True\n", encoding="utf-8")

    assert sorted(p.name for p in dj._iter_files(root, "*.py")) == ["manage.py",
                                                                    "settings.py"]
    assert dj.module.project_root(root) == root


# ── R10-Q1: the other family of glob callers ───────────────────────────────────
#
# `_deps_text`, `_versions` and `_check_deps_pinned` each `glob("requirements*.txt")`
# and hand every hit to `_read_contained`, which is `fallbacks.escapes_root` plus this
# module's own reader. A `glob` yields symlinks and has been through no walk, so the
# containment rule is the only thing standing between those three and a neighbour's
# pins — and on a symlink loop it raised `RuntimeError` instead of refusing.
#
# `detect` is the entry point that matters: it calls `project_root`, which calls
# `_deps_text`, so the failure landed before any check ran and took the whole report
# with it whatever else the repo contained.

def test_issue_r10_q1_a_looping_requirements_link_does_not_take_detection_down(tmp_path):
    """R10-Q1, django half. `requirements.txt -> requirements.txt`: ELOOP, which
    CPython 3.11's `Path.resolve()` re-raises as `RuntimeError` rather than `OSError`.

    A refused read is `""` here — the same thing an unreadable file already yields — so
    the module answers the way it does for any file it may not read: django is detected
    on its own `manage.py`, and nothing in the report was decided by a path the
    filesystem could not resolve.
    """
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "manage.py").write_text("#\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["django>=5.0"]\n', encoding="utf-8")
    (root / "config" / "settings.py").write_text("DEBUG = False\n", encoding="utf-8")
    (root / "requirements.txt").symlink_to("requirements.txt")

    assert dj.module.detect(root) is True
    assert dj._read_contained(root, root / "requirements.txt") == ""


def test_issue_takko_annotated_env_list_is_an_allowed_hosts_setting(tmp_path):
    """TAKKO's real line, verbatim: `ALLOWED_HOSTS: list[str] = env.list(...)`.

    `_top_assigns` walked only `ast.Assign`, so an annotated assignment was invisible
    and django.allowed-hosts warned "empty or absent" about a site that sets hosts
    from the environment — the check's own fix_hint. The warning trained operators
    to ignore it on the one repo that already does what the hint asks.
    """
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    (tmp_path / "requirements.txt").write_text("Django==5.2.4\ndjango-environ==0.11.2\n")
    (tmp_path / "settings.py").write_text(
        "import environ\n"
        "env = environ.Env()\n"
        'ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])\n'
        "SECRET_KEY = env.str('DJANGO_SECRET_KEY')\n"
        "STATIC_ROOT = '/srv/static'\n"
    )
    checks = _by_id(dj.module.checks(tmp_path))
    assert checks["django.allowed-hosts"].tier == "ok"


def test_issue_hrsaas_empty_base_overridden_in_prod_is_configured(tmp_path):
    """hr-saas-starter: `ALLOWED_HOSTS: list[str] = []` in base.py and
    `ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")` in prod.py.

    AnnAssign made the empty base visible; the check then warned on it even
    though a prod-reachable file supplies the real value. An empty default that
    prod overrides is the Django split-settings pattern, not an empty deploy.
    """
    cfg = tmp_path / "config" / "settings"
    cfg.mkdir(parents=True)
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    (tmp_path / "requirements.txt").write_text("Django==5.2.4\n")
    (cfg / "__init__.py").write_text("")
    (cfg / "base.py").write_text(
        "ALLOWED_HOSTS: list[str] = []\n"
        "SECRET_KEY = 'x'\n"
        "STATIC_ROOT = '/srv/static'\n"
    )
    (cfg / "prod.py").write_text(
        "from .base import *  # noqa\n"
        'ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")\n'
    )
    checks = _by_id(dj.module.checks(tmp_path))
    assert checks["django.allowed-hosts"].tier == "ok"


def test_issue_takko_an_empty_annotated_list_is_still_empty(tmp_path):
    """The AnnAssign path is not a free pass: `ALLOWED_HOSTS: list[str] = []`
    is still the empty-list warning the check exists for."""
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
    (tmp_path / "requirements.txt").write_text("Django==5.2.4\n")
    (tmp_path / "settings.py").write_text(
        "ALLOWED_HOSTS: list[str] = []\n"
        "SECRET_KEY = 'x'\n"
        "STATIC_ROOT = '/srv/static'\n"
    )
    checks = _by_id(dj.module.checks(tmp_path))
    assert checks["django.allowed-hosts"].tier == "warning"
    assert "ALLOWED_HOSTS = []" in checks["django.allowed-hosts"].detail


def test_issue_r10_q1_the_looping_link_cannot_pin_or_version_the_repo(tmp_path):
    """…and the two verdicts those globs feed say what a repo with no readable
    requirements file says, rather than raising: `django.deps-pinned` reports the
    manifest it can see, and the version probe finds no Django version in a file it
    was refused.
    """
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "manage.py").write_text("#\n", encoding="utf-8")
    (root / "config" / "settings.py").write_text("DEBUG = False\n", encoding="utf-8")
    (root / "requirements.txt").symlink_to("requirements.txt")

    assert dj.module._versions(root) == (None, None)
    assert dj.module._check_deps_pinned(root).id == "django.deps-pinned"

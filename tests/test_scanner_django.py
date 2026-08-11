"""Django scanner module: fleet-norm (uv+ASGI+sidecars), legacy blockers, pip/WSGI."""
import pathlib

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

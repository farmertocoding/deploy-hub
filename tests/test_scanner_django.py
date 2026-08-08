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

"""Fallback modules + common-core checks (review3 §V4; scanner/modules/fallbacks.py)."""
import pathlib
import shutil

import pytest

from scanner import core
from scanner.modules import fallbacks

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "fallbacks"
DJANGO_MODULE_SRC = REPO / "scanner" / "modules" / "django.py"


def by_id(results, check_id):
    matches = [r for r in results if r.id == check_id]
    assert len(matches) == 1, f"{check_id} appeared {len(matches)} times"
    return matches[0]


def secret_tree(tmp_path):
    """The committed-.env tree. Repo .gitignore ignores `.env` everywhere, so the
    offending file is materialized at test time instead of shipped in the fixture."""
    tree = tmp_path / "secret_tree"
    shutil.copytree(FIXTURES / "secret_tree", tree)
    (tree / ".env").write_text("FAKE_SECRET=abcdef1234567890abcdef\n")
    return tree


# ── dockerfile fallback module ──────────────────────────────────────────────────

def test_dockerfile_detects_and_fires_its_three_warnings():
    project = FIXTURES / "dockerfile_project"
    mod = fallbacks.dockerfile_module
    assert mod.detect(project)
    results = mod.checks(project)
    assert by_id(results, "dockerfile.expose").tier == "warning"
    assert by_id(results, "dockerfile.non-root").tier == "warning"
    assert by_id(results, "dockerfile.latest-tag").tier == "warning"
    # :latest is also unpinned — the common core flags the digest gap too (§6.8).
    assert by_id(results, "core.digest-pins").tier == "warning"
    # §M1: image build is pipeline step 1 — the scan emits NO build spec.
    assert mod.sandbox_checks(project) == []


def test_dockerfile_manifest_takes_port_from_expose(tmp_path):
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12-slim@sha256:0000000000000000000000000000000000000000"
        "000000000000000000000000\nEXPOSE 8080\nUSER app\nCMD [\"app\"]\n")
    mod = fallbacks.dockerfile_module
    frag = mod.manifest_fragment(tmp_path, answers=None)
    assert frag["components"]["service"] == {"kind": "dockerfile", "port": 8080}
    assert "dockerfile.port" not in {q.id for q in mod.wizard_questions(tmp_path)}
    results = mod.checks(tmp_path)
    assert by_id(results, "dockerfile.expose").tier == "ok"
    assert by_id(results, "dockerfile.non-root").tier == "ok"
    assert by_id(results, "dockerfile.latest-tag").tier == "ok"
    assert by_id(results, "core.digest-pins").tier == "ok"


def test_dockerfile_without_expose_asks_the_port():
    project = FIXTURES / "dockerfile_project"
    mod = fallbacks.dockerfile_module
    frag = mod.manifest_fragment(project, answers=None)
    assert frag["components"]["service"] == {"kind": "dockerfile", "port": None}
    question_ids = {q.id for q in mod.wizard_questions(project)}
    assert {"dockerfile.domain", "dockerfile.exposure",
            "dockerfile.port", "dockerfile.env"} <= question_ids


# ── static fallback module ──────────────────────────────────────────────────────

def test_static_detects_root_index_and_emits_static_route():
    site = FIXTURES / "static_site"
    mod = fallbacks.static_module
    assert mod.detect(site)
    frag = mod.manifest_fragment(site, answers=None)
    assert frag["components"]["static_route"] == {"dir": "."}
    assert mod.sandbox_checks(site) == []


def test_static_detects_dist_index(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>\n")
    mod = fallbacks.static_module
    assert mod.detect(tmp_path)
    frag = mod.manifest_fragment(tmp_path, answers=None)
    assert frag["components"]["static_route"] == {"dir": "dist"}


def test_static_does_not_match_when_server_manifests_exist(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>\n")
    (tmp_path / "manage.py").write_text("import sys\n")
    assert not fallbacks.static_module.detect(tmp_path)
    # A Dockerfile is a server manifest too — that tree belongs to `dockerfile`.
    assert not fallbacks.static_module.detect(FIXTURES / "dockerfile_project")


# ── common core: secret scan ────────────────────────────────────────────────────

def test_committed_env_file_is_a_blocker(tmp_path):
    tree = secret_tree(tmp_path)
    res = by_id(fallbacks.common_checks(tree), "core.secret-scan")
    assert res.tier == "blocker"
    assert ".env: committed .env file" in res.detail
    assert "example" not in res.detail  # .env.example must NOT be flagged


def test_env_example_alone_is_clean():
    res = by_id(fallbacks.common_checks(FIXTURES / "secret_tree"), "core.secret-scan")
    assert res.tier == "ok"


def test_high_entropy_assignment_is_a_blocker_with_file_and_line(tmp_path):
    (tmp_path / "settings.py").write_text(
        "DEBUG = False\nAPI_KEY = \"9fj39fJ2kd93jdkQpz81\"\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.secret-scan")
    assert res.tier == "blocker"
    assert "settings.py:2" in res.detail


def test_aws_key_pattern_is_a_blocker(tmp_path):
    (tmp_path / "deploy.cfg").write_text("key = AKIAABCDEFGHIJKLMNOP\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.secret-scan")
    assert res.tier == "blocker"
    assert "deploy.cfg:1" in res.detail


def test_placeholder_values_are_not_flagged(tmp_path):
    (tmp_path / "settings.py").write_text(
        "SECRET_KEY = \"changeme-changeme-changeme\"\n"
        "TOKEN = \"example_example_example\"\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.secret-scan")
    assert res.tier == "ok"


# ── common core: exposure-auth heuristic (SCAN-M4-EXPOSURE-AUTH) ────────────────
#
# R4-11 WI-3: these two tests carried `@pytest.mark.req("SCAN-M4-EXPOSURE-AUTH")`,
# which reported the requirement `verified`. They prove the warning/ok toggle of the
# common-core heuristic and nothing else. The requirement makes two further claims
# that are not merely untested but absent from the tree:
#   1. "Blocker when the wizard tags financial/personal data" — `_check_exposure_auth`
#      returns only ok/warning, and no wizard question tags data sensitivity, so
#      there is no answer for an escalation to read.
#   2. "*Both modules* warn" — the django module's `checks()` never calls
#      `common_checks`, so `core.exposure-auth` never appears in a Django scan
#      report at all.
# The markers are therefore removed and the requirement is waived (WAIVERS.md,
# 2026-08-11) rather than left reading `verified` on a third of its text. The tests
# stay and still run; they regain the marker when the waiver retires. See D-009.


def test_no_auth_indicators_fires_exposure_auth_warning():
    results = fallbacks.common_checks(FIXTURES / "noauth_project")
    res = by_id(results, "core.exposure-auth")
    assert res.tier == "warning"
    assert "no authentication detected" in res.detail
    assert "wizard will ask" in res.detail


def test_auth_indicators_silence_exposure_auth(tmp_path):
    (tmp_path / "app.py").write_text("def login(request):\n    return None\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.exposure-auth")
    assert res.tier == "ok"


# ── common core: the remaining checks ───────────────────────────────────────────

def test_common_core_on_noauth_tree_flags_lockfile_gitignore_tests_healthz():
    results = fallbacks.common_checks(FIXTURES / "noauth_project")
    assert by_id(results, "core.lockfile").tier == "warning"       # package.json, no lock
    assert by_id(results, "core.gitignore").tier == "warning"      # no .gitignore at all
    assert by_id(results, "core.tests-exist").tier == "advice"     # advisory per plan
    assert by_id(results, "core.healthz").tier == "advice"         # §E9: never a blocker
    assert "200 route or" in by_id(results, "core.healthz").detail  # fallback is stated


def test_healthz_detected_when_route_is_greppable(tmp_path):
    (tmp_path / "app.py").write_text("ROUTES = {\"/healthz\": ok_view}\n")
    assert by_id(fallbacks.common_checks(tmp_path), "core.healthz").tier == "ok"


def test_gitignore_gap_checks(tmp_path):
    (tmp_path / "package.json").write_text("{\"name\": \"a\"}\n")
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.gitignore")
    assert res.tier == "warning" and "node_modules" in res.detail
    (tmp_path / ".gitignore").write_text("node_modules/\n.env\n")
    assert by_id(fallbacks.common_checks(tmp_path), "core.gitignore").tier == "ok"


def test_pyproject_lockfile_satisfied_by_uv_lock(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"x\"\n")
    assert by_id(fallbacks.common_checks(tmp_path), "core.lockfile").tier == "warning"
    (tmp_path / "uv.lock").write_text("version = 1\n")
    assert by_id(fallbacks.common_checks(tmp_path), "core.lockfile").tier == "ok"


# ── precedence (§V4): detect() stays true; core dispatch decides ────────────────

def test_dockerfile_detect_is_true_even_when_manage_py_exists(tmp_path):
    """Framework precedence lives in core.detect_modules, not in detect()."""
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    (tmp_path / "manage.py").write_text("import sys\n")
    assert fallbacks.dockerfile_module.detect(tmp_path)


def test_fallbacks_registered_as_fallbacks_in_the_real_registry():
    import scanner.modules  # noqa: F401 — importing registers all modules

    _, fallback_mods = core.registered_modules()
    names = [m.name for m in fallback_mods]
    assert names.count("dockerfile") == 1
    assert names.count("static") == 1


def test_real_registry_scan_of_dockerfile_project_uses_the_fallback():
    report = core.scan(FIXTURES / "dockerfile_project")
    assert report["modules"] == ["dockerfile"]
    assert report["manifest_draft"]["components"]["service"]["kind"] == "dockerfile"


@pytest.mark.req("SCAN-V4-FALLBACK-PRECEDENCE")
@pytest.mark.skipif(
    DJANGO_MODULE_SRC.read_text(encoding="utf-8").strip() == "",
    reason="scanner.modules.django not implemented yet — precedence untestable "
           "against the real registry until it lands",
)
def test_real_registry_prefers_django_module_over_fallbacks(tmp_path):
    import scanner.modules  # noqa: F401 — importing registers all modules

    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    (tmp_path / "manage.py").write_text("import sys\n")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = \"x\"\ndependencies = [\"django\"]\n")
    names = [m.name for m in core.detect_modules(tmp_path)]
    assert "dockerfile" not in names
    assert "static" not in names

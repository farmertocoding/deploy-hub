"""Phase 6 scale-ready: core.scale-ready is warning not blocker; materialize copies ok.

C13 predicates. Scanner reuses common_checks texts/paths. Missing check or any
non-ok tier → Site.scale_ready False even if confirm_warnings. Markers only on
tests that prove SCALE-READY-PREREQ (C11).
"""
import pytest

from scanner.modules import fallbacks

SCALE_READY_ID = "core.scale-ready"


def _scale_ready(root):
    hits = [c for c in fallbacks.common_checks(root) if c.id == SCALE_READY_ID]
    assert len(hits) == 1, f"{SCALE_READY_ID} appeared {len(hits)} times"
    check = hits[0]
    assert check.tier in ("warning", "ok"), check
    assert check.tier != "blocker"
    return check


def _report(checks):
    from scanner import core as scanner_core

    return {
        "schema_version": scanner_core.SCHEMA_VERSION,
        "modules": ["django"],
        "checks": list(checks),
        "sandbox_jobs": [],
        "wizard_questions": [],
        "manifest_draft": {
            "schema_version": scanner_core.SCHEMA_VERSION,
            "deploy_strategy": "blue_green",
        },
        "summary": {},
    }


def _site_with_report(slug, checks, *, scale_ready=False):
    from dns_fixtures import default_dns_zone

    from core.models import Project, Site
    from wizard import service

    project = Project.objects.create(
        name=slug,
        slug=slug,
        source_kind=Project.Source.GIT,
        git_url="https://github.com/org/repo.git",
        scan_report=_report(checks),
    )
    site = Site.objects.create(
        project=project,
        name=slug,
        dns_zone=default_dns_zone(),
        scale_ready=scale_ready,
    )
    service.set_answers(site, {"site.domain": "demo.example.com"})
    return site


@pytest.mark.req("SCALE-READY-PREREQ")
def test_sqlite_tree_is_scale_ready_warning_not_blocker(tmp_path):
    """A committed sqlite file is marked, not blocked.

    What would make this fail: omitting core.scale-ready, emitting blocker, or
    walking past texts/paths so a named .sqlite3 in the suite walk is invisible.
    """
    (tmp_path / "app.sqlite3").write_text("placeholder\n", encoding="utf-8")
    check = _scale_ready(tmp_path)
    assert check.tier == "warning"
    assert check.id == SCALE_READY_ID


@pytest.mark.req("SCALE-READY-PREREQ")
def test_clean_tree_is_scale_ready_ok(tmp_path):
    """Empty tree is ok. Absence of local-state files is not a fail.

    What would make this fail: warning on an empty tree, or only emitting the
    check when a fail predicate matched.
    """
    check = _scale_ready(tmp_path)
    assert check.tier == "ok"


@pytest.mark.req("SCALE-READY-PREREQ")
def test_parquet_duckdb_wal_are_warning(tmp_path):
    """Parquet, DuckDB, and *-wal files are the same local-state class as sqlite.

    What would make this fail: only matching *.sqlite3, or requiring binary
    headers so a named file in texts/paths is skipped.
    """
    (tmp_path / "bars-2026-01.parquet").write_text("placeholder\n", encoding="utf-8")
    (tmp_path / "levels.duckdb").write_text("placeholder\n", encoding="utf-8")
    (tmp_path / "app.sqlite3-wal").write_text("placeholder\n", encoding="utf-8")
    check = _scale_ready(tmp_path)
    assert check.tier == "warning"


@pytest.mark.req("SCALE-READY-PREREQ")
def test_sqlite_engine_text_is_warning(tmp_path):
    """sqlite ENGINE / sqlite DATABASE_URL in settings text is a warning.

    What would make this fail: only looking at filenames, or matching README
    mentions of sqlite that are not assignments.
    """
    (tmp_path / "settings.py").write_text(
        "DATABASES = {\n"
        '    "default": {"ENGINE": "django.db.backends.sqlite3"}\n'
        "}\n",
        encoding="utf-8",
    )
    check = _scale_ready(tmp_path)
    assert check.tier == "warning"

    clean = tmp_path / "readme-only"
    clean.mkdir()
    (clean / "README.md").write_text(
        "This project used to use sqlite ENGINE and a sqlite DATABASE_URL.\n",
        encoding="utf-8",
    )
    assert _scale_ready(clean).tier == "ok"


@pytest.mark.req("SCALE-READY-PREREQ")
def test_locmem_session_is_warning(tmp_path):
    """SESSION_ENGINE locmem cannot be shared across copies.

    What would make this fail: matching SESSION_COOKIE_SECURE or any 'session'
    substring, which is the exposure-auth false-ok this check must not copy.
    """
    (tmp_path / "settings.py").write_text(
        'SESSION_ENGINE = "django.contrib.sessions.backends.locmem"\n'
        "SESSION_COOKIE_SECURE = True\n",
        encoding="utf-8",
    )
    check = _scale_ready(tmp_path)
    assert check.tier == "warning"


@pytest.mark.req("SCALE-READY-PREREQ")
def test_celery_localhost_broker_is_warning(tmp_path):
    """Celery imported or required AND a localhost broker URL is a warning.

    What would make this fail: celery in pyproject plus a non-broker localhost
    (POSTGRES_HOST) firing, or a localhost broker without celery being ignored.
    """
    (tmp_path / "app.py").write_text(
        "from celery import Celery\n"
        'CELERY_BROKER_URL = "redis://localhost:6379/0"\n',
        encoding="utf-8",
    )
    check = _scale_ready(tmp_path)
    assert check.tier == "warning"


@pytest.mark.req("SCALE-READY-PREREQ")
def test_django_media_root_without_object_storage_is_warning(tmp_path):
    """Django-only media (MEDIA_ROOT without object storage) is not scale-ready.

    What would make this fail: FileSystemStorage counting as a pass, or treating
    STORAGES as an exemption even when it is local.
    """
    (tmp_path / "settings.py").write_text(
        "INSTALLED_APPS = []\n"
        'MEDIA_ROOT = "/var/media"\n'
        'DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"\n',
        encoding="utf-8",
    )
    check = _scale_ready(tmp_path)
    assert check.tier == "warning"


@pytest.mark.req("SCALE-READY-PREREQ")
def test_absence_of_django_settings_is_not_media_fail(tmp_path):
    """MEDIA_ROOT outside Django settings is not a media fail.

    What would make this fail: any MEDIA_ROOT token warning a Node tree, or
    empty-of-Django becoming a media fail.
    """
    (tmp_path / "notes.txt").write_text(
        'MEDIA_ROOT = "/var/media"\n'
        'DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"name": "app"}\n', encoding="utf-8")
    check = _scale_ready(tmp_path)
    assert check.tier == "ok"


@pytest.mark.django_db
@pytest.mark.req("SCALE-READY-PREREQ")
def test_materialize_copies_false_on_warning_even_with_confirm_warnings(db):
    """confirm_warnings lets materialize proceed; it does not set scale_ready.

    Starts True so a missing write cannot hide behind the False default.
    """
    from wizard.materialize import materialize

    site = _site_with_report(
        "sr-warn",
        [{"id": SCALE_READY_ID, "tier": "warning", "title": "Not scale-ready"}],
        scale_ready=True,
    )
    materialize(site, confirm_warnings=True)
    site.refresh_from_db()
    assert site.scale_ready is False


@pytest.mark.django_db
@pytest.mark.req("SCALE-READY-PREREQ")
def test_materialize_copies_true_on_ok(db):
    """locked.scale_ready is True only when the check tier is ok."""
    from wizard.materialize import materialize

    site = _site_with_report(
        "sr-ok",
        [{"id": SCALE_READY_ID, "tier": "ok", "title": "Scale-ready"}],
        scale_ready=False,
    )
    materialize(site)
    site.refresh_from_db()
    assert site.scale_ready is True


@pytest.mark.django_db
@pytest.mark.req("SCALE-READY-PREREQ")
def test_missing_check_in_report_is_false(db):
    """A stored report without core.scale-ready is fail-closed False.

    Starts True so leaving the column untouched would fail this test.
    """
    from wizard.materialize import materialize

    site = _site_with_report(
        "sr-missing",
        [{"id": "core.healthz", "tier": "ok", "title": "Health endpoint detected"}],
        scale_ready=True,
    )
    materialize(site)
    site.refresh_from_db()
    assert site.scale_ready is False

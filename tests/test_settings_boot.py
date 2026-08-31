"""H1: process entrypoints and compose must not boot hub.settings.dev.

What would make these fail: asgi/celery/worker_entry/wsgi setdefault-ing
hub.settings.dev, docker-compose.yml pinning DJANGO_SETTINGS_MODULE to
hub.settings.dev, or a compose settings module that allows FakeKEK / DEBUG /
env-flipped HUB_TEST_MODE. Laptop `manage.py` stays on hub.settings.dev.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import stat

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = REPO / "docker-compose.yml"
HUB_SERVICES = ("web", "worker-deploys", "worker-probes", "worker-control", "beat")
ENTRYPOINTS = (
    REPO / "hub" / "asgi.py",
    REPO / "hub" / "celery.py",
    REPO / "hub" / "wsgi.py",
    REPO / "deploys" / "worker_entry.py",
)


def _setdefault_settings_module(path: pathlib.Path) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "setdefault":
            continue
        if len(node.args) < 2:
            continue
        key, value = node.args[0], node.args[1]
        if isinstance(key, ast.Constant) and key.value == "DJANGO_SETTINGS_MODULE":
            if isinstance(value, ast.Constant):
                return value.value
    return None


def _compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _service_env(service: dict) -> dict:
    env = service.get("environment") or {}
    if isinstance(env, list):
        return dict(item.split("=", 1) for item in env if "=" in item)
    return dict(env)


def test_process_entrypoints_default_to_prod_settings():
    """A bare `daphne` / `celery -A hub` / `python -m deploys.worker_entry`
    must fail closed on prod.py, not silently take FakeKEK + DEBUG.

    What would make this fail: setdefault("DJANGO_SETTINGS_MODULE",
    "hub.settings.dev") in asgi, celery, wsgi, or worker_entry.
    """
    for path in ENTRYPOINTS:
        module = _setdefault_settings_module(path)
        assert module == "hub.settings.prod", (
            f"{path.relative_to(REPO)} setdefault DJANGO_SETTINGS_MODULE="
            f"{module!r}; expected hub.settings.prod"
        )


def test_manage_py_defaults_to_dev_settings():
    """Laptop `python manage.py runserver` stays on hub.settings.dev.

    What would make this fail: manage.py setdefault-ing prod (breaks zero-service
    README) or the empty hub.settings package (boot-fail).
    """
    module = _setdefault_settings_module(REPO / "manage.py")
    assert module == "hub.settings.dev", (
        f"manage.py setdefault DJANGO_SETTINGS_MODULE={module!r}; "
        "expected hub.settings.dev"
    )


def test_compose_does_not_boot_dev_settings():
    """README's compose stack is the runnable shape — it must not select
    hub.settings.dev (DEBUG + FakeKEK).

    What would make this fail: DJANGO_SETTINGS_MODULE: hub.settings.dev on
    any Hub service, or a service dropping the shared env anchor.
    """
    compose = _compose()
    for name in HUB_SERVICES:
        env = _service_env(compose["services"][name])
        module = env.get("DJANGO_SETTINGS_MODULE")
        assert module == "hub.settings.compose", (
            f"compose {name} DJANGO_SETTINGS_MODULE={module!r}; "
            "expected hub.settings.compose"
        )


def test_prod_settings_webauthn_rp_from_public_https_url(monkeypatch):
    """H3: prod WebAuthn RP ID / origins come from HUB_PUBLIC_URL (https only).

    What would make this fail: OTP_WEBAUTHN_RP_ID staying 'localhost' in
    prod.py, or allowed origins remaining HTTP vite ports from base.py.
    """
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "local")
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_AUDIT_S3_BUCKET", "hub-audit-test")
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://hub.example.test")
    from hub.settings import base as base_settings

    importlib.reload(base_settings)
    prod = importlib.reload(importlib.import_module("hub.settings.prod"))
    assert prod.OTP_WEBAUTHN_RP_ID == "hub.example.test"
    assert prod.OTP_WEBAUTHN_ALLOWED_ORIGINS == ["https://hub.example.test"]

    monkeypatch.setenv("HUB_PUBLIC_URL", "http://localhost:8000")
    importlib.reload(base_settings)
    with pytest.raises(ImproperlyConfigured, match="HUB_PUBLIC_URL"):
        importlib.reload(importlib.import_module("hub.settings.prod"))


def test_compose_settings_refuse_fake_kek_and_debug():
    """Compose settings inherit prod.py and must not re-enable FakeKEK or DEBUG.

    What would make this fail: compose.py not importing prod, or assigning
    VAULT_ALLOW_FAKE_KEK = True / DEBUG = True after the import.
    """
    path = REPO / "hub" / "settings" / "compose.py"
    assert path.is_file(), "hub/settings/compose.py is missing"
    src = path.read_text(encoding="utf-8")
    assert "from .prod import" in src
    assert "VAULT_ALLOW_FAKE_KEK = True" not in src
    assert "DEBUG = True" not in src


def test_compose_settings_pin_test_mode_off_and_http_loopback(monkeypatch):
    """HUB_TEST_MODE stays pinned False; loopback HTTP can still set a cookie.

    What would make this fail: compose.py inheriting env-derived HUB_TEST_MODE,
    DEBUG=True, FakeKEK allowed, or keeping SECURE_SSL_REDIRECT so
    127.0.0.1:8000 never issues a session cookie.
    """
    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_TEST_MODE", "1")
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "local")
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_REQUIRE_AUDIT_SHIP", "0")
    from hub.settings import base as base_settings

    importlib.reload(base_settings)
    importlib.reload(importlib.import_module("hub.settings.prod"))
    compose = importlib.reload(importlib.import_module("hub.settings.compose"))

    assert compose.DEBUG is False
    assert compose.HUB_TEST_MODE is False
    assert compose.VAULT_ALLOW_FAKE_KEK is False
    assert compose.SECURE_SSL_REDIRECT is False
    assert compose.SESSION_COOKIE_SECURE is False
    assert compose.CSRF_COOKIE_SECURE is False


def test_compose_settings_trust_vite_login_origin(monkeypatch):
    """Vite :5173 is the operator SPA origin against compose Daphne :8000.

    What would make this fail: compose inheriting prod CSRF/WebAuthn origins,
    so Origin: http://localhost:5173 403s login and webauthn/login/begin.
    """
    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "local")
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_REQUIRE_AUDIT_SHIP", "0")
    from hub.settings import base as base_settings

    importlib.reload(base_settings)
    importlib.reload(importlib.import_module("hub.settings.prod"))
    compose = importlib.reload(importlib.import_module("hub.settings.compose"))
    assert "http://localhost:5173" in compose.CSRF_TRUSTED_ORIGINS
    assert "http://127.0.0.1:5173" in compose.CSRF_TRUSTED_ORIGINS
    assert "http://localhost:5173" in compose.OTP_WEBAUTHN_ALLOWED_ORIGINS
    assert "http://127.0.0.1:5173" not in compose.OTP_WEBAUTHN_ALLOWED_ORIGINS
    assert compose.OTP_WEBAUTHN_RP_ID == "localhost"


def test_compose_shares_a_vault_keyfile_volume():
    """Local KEK must be the same file on web and every worker.

    What would make this fail: no /etc/deploy-hub mount, a bind mount, or
    per-service volumes so Celery unwraps with a different key than daphne.
    """
    compose = _compose()
    declared = compose.get("volumes") or {}
    path = "/etc/deploy-hub"
    names = []
    kek_services = tuple(
        name for name in HUB_SERVICES if name not in {"worker-probes", "beat"}
    )
    for name in kek_services:
        volumes = compose["services"][name].get("volumes") or []
        sources = []
        for mount in volumes:
            if isinstance(mount, str):
                src, _, dest = mount.partition(":")
                dest = dest.split(":")[0]
                if dest.rstrip("/") == path:
                    sources.append(src)
            elif isinstance(mount, dict) and mount.get("target", "").rstrip("/") == path:
                sources.append(mount.get("source"))
        named = [src for src in sources if src in declared]
        assert named, (
            f"{name} has no named volume at {path}; "
            f"mounts={volumes!r}"
        )
        names.append(named[0])
    assert len(set(names)) == 1, names


def test_ensure_keyfile_creates_0400_32_byte_file_without_django(tmp_path, monkeypatch):
    """First compose boot must mint a local KEK before Django ready() checks it.

    What would make this fail: importing django.conf (chicken-egg with
    vault.apps ready()), overwriting an existing key, or writing a world-readable
    / wrong-length file.
    """
    import vault.ensure_keyfile as ensure_keyfile

    tree = ast.parse(pathlib.Path(ensure_keyfile.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("django"), alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("django"), node.module

    target = tmp_path / "vault.key"
    monkeypatch.setenv("HUB_VAULT_KEYFILE", str(target))
    written = ensure_keyfile.ensure()
    assert written == target
    assert target.read_bytes()  # non-empty
    assert len(target.read_bytes()) == 32
    assert stat.S_IMODE(target.stat().st_mode) == 0o400

    first = target.read_bytes()
    ensure_keyfile.ensure()
    assert target.read_bytes() == first, "existing keyfile must not be overwritten"

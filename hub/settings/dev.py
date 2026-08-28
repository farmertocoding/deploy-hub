"""Dev settings — runnable with zero services (SQLite fallback) for quick checks.

`docker compose up` uses Postgres/Redis via env vars; plain `manage.py check`/pytest
on a laptop falls back to SQLite and the in-memory channel layer.
"""
import os

from .base import *  # noqa: F401,F403

DEBUG = True

if not os.environ.get("POSTGRES_PASSWORD"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "dev.sqlite3",  # noqa: F405
        }
    }

if not os.environ.get("REDIS_PASSWORD"):
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    CELERY_TASK_ALWAYS_EAGER = True  # demo job runs inline without a worker

# The vite dev server (5173) proxies /api with changeOrigin, so Django sees
# Host=localhost:8000 while the browser Origin is the vite origin — without this
# every POST fails Django's CSRF origin check. Dev only; prod is same-origin.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Vault: dev uses the fake KEK (refuses to load when DEBUG is False, see vault/kek.py)
# so a laptop needs no keyfile. Tests that exercise the real backend point
# VAULT_KEYFILE at a tmp_path and flip the backend explicitly.
VAULT_KEK_BACKEND = "fake"
VAULT_ALLOW_FAKE_KEK = True

# Laptop/API tests may register a checkout. Production stays off (base.py).
HUB_ALLOW_LOCAL_SOURCES = True

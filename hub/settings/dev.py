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

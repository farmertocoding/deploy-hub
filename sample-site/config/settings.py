"""Env-driven settings — no secrets in this tree."""
import os

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = [
    host for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if host
]

INSTALLED_APPS = ["django.contrib.staticfiles"]
MIDDLEWARE = []
ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

STATIC_URL = "/static/"
STATIC_ROOT = "/srv/static"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_SQLITE_PATH", "/data/db.sqlite3"),
    }
}

# Healthz is HTTP from Caddy; TLS terminates at the edge.
SECURE_SSL_REDIRECT = False

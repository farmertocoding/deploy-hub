"""Base settings — env-driven, classic pip + gunicorn shape."""
import os

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "app"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = "/srv/static"

WSGI_APPLICATION = "config.wsgi.application"

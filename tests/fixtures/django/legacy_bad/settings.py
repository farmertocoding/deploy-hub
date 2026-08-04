"""Single hardcoded settings file — the anti-pattern the scanner must flag."""

DEBUG = True

SECRET_KEY = "django-insecure-h3k9x!p2q@8vw#5rn$7mz&1jt*4cy^0bf(6ds)ale%gu+i"

ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "django.contrib.staticfiles",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "db.sqlite3",
    }
}

STATIC_URL = "/static/"

"""Build the /tmp fixture repos the frontend sim fixtures are generated from.

Not part of the product — a dev-only driver, the same shape as `ws_reconnect_demo.py`,
and it is committed for one reason: r8's finding was that a fixture nobody can re-derive
is a UI nobody reviewed. `frontend/src/sim.js` claims every payload in it came from a
real run of these trees, and this file is what makes that claim checkable by anyone.

    python scripts_dev/sim_fixture_repos.py          # writes /tmp/{clean,messy}repo
    python -m hub scan /tmp/messyrepo                # what the sim's project 2 shows

The payloads themselves come from `ReadinessSerializer(...).data`,
`wizard.views._state(site)` and `wizard.materialize.materialize` run over these trees —
see the commit that regenerated sim.js for the exact harness.

The credentials below are the shape the heuristic axis exists to find and are fake by
construction (one 40-character value, repeated). They are here because the messy tree is
the SATURDAYS_site analog: ten of its fifteen blocking lines are in a drill tree the repo
declares in `deployhub.yaml`, and since D-012 left Phase 1 all fifteen report at full
tier in one bucket, with a `core.declaration-file` warning beside them.
"""
import pathlib
import shutil

FAKE_HIGH_ENTROPY = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P"
DRILL_REASON = "red-team / QA drill scripts; deliberate fake credentials"


def write(root, files):
    root = pathlib.Path(root)
    if root.exists():
        shutil.rmtree(root)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


CLEAN = {
    "Dockerfile": (
        "FROM python:3.12-slim@sha256:"
        "1a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "RUN useradd -m app\n"
        "USER app\n"
        "EXPOSE 8000\n"
        'CMD ["python", "server.py"]\n'),
    "server.py": (
        "import os\n"
        "\n"
        "SESSION_TTL = 3600\n"
        "\n"
        "\n"
        "def healthz(request):\n"
        '    """Liveness route: GET /healthz -> 200."""\n'
        '    return {"status": "ok"}\n'
        "\n"
        "\n"
        "def dashboard(request):\n"
        "    if not request.user.is_authenticated:\n"
        '        return {"status": 401}\n'
        '    return {"status": 200}\n'),
    "package.json": '{\n  "name": "takko",\n  "version": "1.0.0"\n}\n',
    "package-lock.json": '{\n  "name": "takko",\n  "lockfileVersion": 3\n}\n',
    "tests/test_healthz.py": (
        "from server import healthz\n"
        "\n"
        "\n"
        "def test_healthz_reports_ok():\n"
        '    assert healthz(None)["status"] == "ok"\n'),
    ".gitignore": ".env\nnode_modules/\n__pycache__/\n",
}

MESSY = {
    "manage.py": (
        "#!/usr/bin/env python\n"
        "import os\n"
        "import sys\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')\n"
        "    from django.core.management import execute_from_command_line\n"
        "    execute_from_command_line(sys.argv)\n"),
    "pyproject.toml": (
        "[project]\n"
        'name = "legacy-shop"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["Django==4.2.11", "gunicorn==21.2.0"]\n'),
    "requirements.txt": "Django==4.2.11\ngunicorn==21.2.0\n",
    "config/__init__.py": "",
    "config/wsgi.py": (
        "import os\n"
        "\n"
        "from django.core.wsgi import get_wsgi_application\n"
        "\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')\n"
        "application = get_wsgi_application()\n"),
    "config/settings/__init__.py": "",
    "config/settings/base.py": (
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "BASE_DIR = Path(__file__).resolve().parent.parent.parent\n"
        "\n"
        "# log-scrub: allow — fixture tree for the sim fixtures, never imported\n"
        'SECRET_KEY = "django-insecure-8Kq2mZ4tR7wLbY1nX6vC3jH9sD5gF0aP2eU4iO7kQ1z"\n'
        'FIELD_ENCRYPTION_KEYS = ["dev-only-fallback-key-not-used-in-production"]\n'
        "\n"
        'ALLOWED_HOSTS = ["shop.example.com"]\n'
        "INSTALLED_APPS = [\n"
        "    'django.contrib.admin',\n"
        "    'django.contrib.auth',\n"
        "    'django.contrib.contenttypes',\n"
        "    'django.contrib.sessions',\n"
        "    'shop',\n"
        "]\n"
        "MIDDLEWARE = [\n"
        "    'django.contrib.sessions.middleware.SessionMiddleware',\n"
        "    'django.contrib.auth.middleware.AuthenticationMiddleware',\n"
        "]\n"
        "ROOT_URLCONF = 'config.urls'\n"
        "STATIC_URL = 'static/'\n"
        "STATIC_ROOT = BASE_DIR / 'staticfiles'\n"
        "DATABASES = {\n"
        "    'default': {\n"
        "        'ENGINE': 'django.db.backends.postgresql',\n"
        "        'NAME': os.environ.get('DB_NAME', 'shop'),\n"
        "    }\n"
        "}\n"),
    "config/settings/prod.py": (
        "import os\n"
        "\n"
        "from .base import *  # noqa: F401,F403\n"
        "\n"
        "DEBUG = True\n"
        "\n"
        "FIELD_ENCRYPTION_KEYS = [os.environ['FIELD_ENCRYPTION_KEYS']]\n"
        "\n"
        "SECURE_SSL_REDIRECT = True\n"
        "SESSION_COOKIE_SECURE = True\n"
        "CSRF_COOKIE_SECURE = True\n"
        "SECURE_HSTS_SECONDS = 31536000\n"
        "CSRF_TRUSTED_ORIGINS = ['https://shop.example.com']\n"),
    "config/urls.py": (
        "from django.urls import path\n"
        "\n"
        "from shop import views\n"
        "\n"
        "urlpatterns = [\n"
        "    path('healthz/', views.healthz),\n"
        "    path('', views.storefront),\n"
        "]\n"),
    "shop/__init__.py": "",
    "shop/views.py": (
        "from django.contrib.auth.decorators import login_required\n"
        "from django.http import JsonResponse\n"
        "\n"
        "\n"
        "def healthz(request):\n"
        "    return JsonResponse({'status': 'ok'})\n"
        "\n"
        "\n"
        "@login_required\n"
        "def storefront(request):\n"
        "    return JsonResponse({'items': []})\n"),
    "shop/tests/__init__.py": "",
    "shop/tests/test_views.py": (
        "def test_healthz(client):\n"
        "    assert client.get('/healthz/').status_code == 200\n"),
    # The drill tree, ten deliberate credentials across the files SATURDAYS_site
    # carries them in — this fixture is that repo's analog, and ten of its lines are
    # what the declaration used to move into a bucket of its own.
    "frontend/scripts/drill/README.md": (
        "# Drill scripts\n\n"
        "Run against a seeded database only. Every credential in this tree is fake.\n\n"
        "The staff console seeds with:\n\n"
        "    django_superuser_password = \"" + FAKE_HIGH_ENTROPY + "\"\n"),
    "frontend/scripts/drill/redteam/01_rbac_money.mjs": (
        "// Red-team drill: privilege escalation against the refunds API.\n"
        "const admin_password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "export default { admin_password };\n"),
    "frontend/scripts/drill/qa/03_regressions.mjs": (
        "// QA drill: the staff console regression pass.\n"
        "const staff_password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "export default { staff_password };\n"),
    "frontend/scripts/drill/qa/05_archive_results.mjs": (
        "// QA drill: archives a completed run.\n"
        "const staff_password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "export default { staff_password };\n"),
    "frontend/scripts/drill/qa/06_admin_shell.mjs": (
        "// QA drill: admin shell smoke pass.\n"
        "const staff_password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "export default { staff_password };\n"),
    "frontend/scripts/drill/qa/08_redis_outage.mjs": (
        "// QA drill: behaviour under a redis outage.\n"
        "const customer_password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "const password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "const fallback_password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "export default { customer_password, password, fallback_password };\n"),
    "frontend/scripts/drill/qa/09_consent_and_lifecycle.mjs": (
        "// QA drill: consent and data-lifecycle flows.\n"
        "const customer_password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "export default { customer_password };\n"),
    "frontend/scripts/drill/qa/10_destinations_and_reconciliation.mjs": (
        "// QA drill: destination reconciliation.\n"
        "const customer_password = \"" + FAKE_HIGH_ENTROPY + "\";\n"
        "export default { customer_password };\n"),
    # …and five blocking lines the declaration never covered: the settings literal, a
    # committed .env, and three secrets pasted into a workflow.
    ".env": "DJANGO_SETTINGS_MODULE=config.settings.prod\n",
    ".github/workflows/ci.yml": (
        "name: ci\n"
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: pytest\n"
        "        env:\n"
        "          SECRET_KEY: " + FAKE_HIGH_ENTROPY + "\n"
        "          DB_PASSWORD: " + FAKE_HIGH_ENTROPY + "\n"
        "          DJANGO_SUPERUSER_PASSWORD: " + FAKE_HIGH_ENTROPY + "\n"),
    "deployhub.yaml": (
        "scanner:\n"
        "  test_material:\n"
        "    - path: frontend/scripts/drill\n"
        f"      reason: {DRILL_REASON}\n"),
    ".gitignore": ".env\n__pycache__/\nstaticfiles/\n",
}

if __name__ == "__main__":
    write("/tmp/cleanrepo", CLEAN)
    write("/tmp/messyrepo", MESSY)
    print("built /tmp/cleanrepo and /tmp/messyrepo")

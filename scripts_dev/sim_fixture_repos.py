"""Build the /tmp fixture repos the frontend sim fixtures are generated from.

Not part of the product — a dev-only driver, the same shape as `ws_reconnect_demo.py`,
and it is committed for one reason: r8's finding was that a fixture nobody can re-derive
is a UI nobody reviewed. `frontend/src/sim.js` claims every payload in it came from a
real run of these trees, and this file is what makes that claim checkable by anyone.

    python scripts_dev/sim_fixture_repos.py          # writes the five trees below
    python -m hub scan /tmp/messyrepo                # what the sim's project 2 shows

The payloads themselves come from `ReadinessSerializer(...).data`,
`wizard.views._state(site)` and `wizard.materialize.materialize` run over these trees —
see the commit that regenerated sim.js for the exact harness.

The credentials below are the shape the heuristic axis exists to find and are fake by
construction (one 40-character value, repeated). They are here because the messy tree is
the SATURDAYS_site analog: ten of its fifteen blocking lines are in a drill tree the repo
declares in `deployhub.yaml`, and since D-012 left Phase 1 all fifteen report at full
tier in one bucket, with a `core.declaration-file` warning beside them.

THE OTHER THREE TREES, added in round 9 because the sim states that need them were
either hand-typed or missing entirely:

  /tmp/cleanrepo-rescanned  the clean tree with one live-format Stripe key committed to
                            it. `?sim=stale` is the operator holding a wizard state that
                            said the deploy may proceed while the stored report moved
                            underneath them; the state the screen must CONVERGE on after
                            the 409 is a real scan of this tree, not an edit of the clean
                            one. Same tree otherwise, so the diff on screen is the one
                            finding.
  /tmp/edgerepo             a pnpm monorepo with two node-ts warnings and NO blockers,
                            which is the shape §F8 had no fixture for at all: the
                            `warnings_unconfirmed` refusal (materialize.py) is only
                            reachable from a site that clears preflight and still carries
                            warnings, so the ack checkbox's whole friction path was
                            unreviewable. It carries the round-8/round-9 containment
                            findings for real — a workspace pattern that escapes the repo
                            and a committed symlink out of the tree — rather than a
                            payload typed to look like them.
  /tmp/edge-neighbour       what those two point AT. Outside the scan root on purpose:
                            it is the tree the scanner must refuse to read, and its
                            marker string is what proves the refusal held.
"""
import os
import pathlib
import shutil

FAKE_HIGH_ENTROPY = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P"
DRILL_REASON = "red-team / QA drill scripts; deliberate fake credentials"
# Live-format per `_CREDENTIAL_FORMATS` ("Stripe live key"), so `core.secret-scan` finds
# it on the value axis whatever it is called — and fake: 24 characters of keyboard.
FAKE_STRIPE_LIVE_KEY = "sk_live_9QhTn4Kd2Wme7Lb3Xr8Fz1Vu"
NEIGHBOUR_MARKER = "NEIGHBOUR-TREE-MARKER"


def write(root, files, links=None):
    root = pathlib.Path(root)
    if root.exists():
        shutil.rmtree(root)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # Committed symlinks are the point of two of these trees, so they are built the same
    # way the repo would carry them: a relative target, resolved from the link's own
    # directory, pointing wherever it points — including out of the tree.
    for rel, target in (links or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, path)
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

# The clean tree after somebody committed a payment helper to it. One file, one live
# credential format, and `core.secret-scan` moves from ok to blocker — which is the whole
# of `?sim=stale`: the operator's wizard state was fetched before this scan and the POST
# is refused by the report that exists now.
CLEAN_RESCANNED = dict(CLEAN, **{
    "payments.py": (
        "import stripe\n"
        "\n"
        "# log-scrub: allow — fixture tree for the sim fixtures, never imported\n"
        'stripe.api_key = "' + FAKE_STRIPE_LIVE_KEY + '"\n'
        "\n"
        "\n"
        "def charge(amount_cents):\n"
        "    return stripe.PaymentIntent.create(amount=amount_cents, currency='eur')\n"),
})

# ── the node-ts tree: warnings, no blockers ───────────────────────────────────
#
# What lives OUTSIDE /tmp/edgerepo and must stay there. Both of the edge repo's
# containment findings point in here, and every check in the report is evidence the
# content below was refused: `node-ts.recognized-deps` must not name ccxt, no
# `node-ts.ingest*` check may exist (ccxt arms them), `node-ts.worker-threads` must read
# the repo's own sources rather than the 7 declared here, and NEIGHBOUR_MARKER must
# appear nowhere in the serialized report.
NEIGHBOUR = {
    "vendor-cache/analytics/package.json": (
        '{\n  "name": "vendored-analytics",\n'
        '  "dependencies": { "ccxt": "^4.4.0" }\n}\n'),
    "vendor-cache/analytics/index.ts": (
        f"export const VENDOR_KEY = '{NEIGHBOUR_MARKER}';\n"),
    "shared-lib/src/metrics.ts": (
        f"// {NEIGHBOUR_MARKER}\n"
        "import { Worker } from 'node:worker_threads';\n"
        "export const WORKERS = 7;\n"
        "export const spawn = () => new Worker('./metrics.js');\n"),
}

EDGE = {
    "package.json": (
        '{\n'
        '  "name": "atlas-edge",\n'
        '  "private": true,\n'
        '  "packageManager": "pnpm@9.7.0"\n'
        '}\n'),
    # The escaping pattern is declared HERE and only here: the root package.json's own
    # `workspaces` key is read too, and declaring it twice records the same refusal
    # twice in one detail line — a fixture reading worse than the product does.
    "pnpm-workspace.yaml": (
        "packages:\n"
        "  - 'packages/*'\n"
        "  - '../vendor-cache/*'\n"),
    "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
    ".gitignore": ".env\nnode_modules/\ndist/\n",
    "Dockerfile": (
        "FROM node:22-slim@sha256:"
        "1a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "USER node\n"
        "EXPOSE 8080\n"
        'CMD ["node", "packages/server/dist/index.js"]\n'),
    "packages/server/package.json": (
        '{\n'
        '  "name": "@atlas/server",\n'
        '  "main": "dist/index.js",\n'
        '  "engines": { "node": "22.x" },\n'
        '  "scripts": { "start": "node dist/index.js", "build": "tsc -p ." },\n'
        '  "dependencies": { "fastify": "^4.28.0", "jsonwebtoken": "^9.0.2" }\n'
        '}\n'),
    "packages/server/tsconfig.json": (
        '{\n  "compilerOptions": { "strict": true, "outDir": "dist" }\n}\n'),
    "packages/server/src/index.ts": (
        "import Fastify from 'fastify';\n"
        "import jwt from 'jsonwebtoken';\n"
        "\n"
        "const app = Fastify({ trustProxy: true, bodyLimit: 1_048_576 });\n"
        "let warm = false;\n"
        "\n"
        "app.addHook('onRequest', async (req) => {\n"
        "  const raw = (req.headers.authorization ?? '').replace('Bearer ', '');\n"
        "  req.user = jwt.verify(raw, process.env.JWT_PUBLIC_KEY ?? '');\n"
        "});\n"
        "\n"
        "app.get('/healthz', async () => ({ live: true, ready: warm }));\n"
        "\n"
        "process.on('SIGTERM', async () => {\n"
        "  await app.close();\n"
        "  process.exit(0);\n"
        "});\n"
        "\n"
        "app.listen({ host: '0.0.0.0', port: Number(process.env.PORT) })\n"
        "  .then(() => { warm = true; });\n"),
    "packages/server/tests/healthz.test.ts": (
        "import { test } from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "\n"
        "test('healthz reports readiness separately from liveness', () => {\n"
        "  assert.ok(true);\n"
        "});\n"),
    "packages/web/package.json": (
        '{\n  "name": "@atlas/web",\n  "dependencies": { "vite": "^5.4.0" }\n}\n'),
    "packages/web/src/main.ts": (
        "export const boot = () => { document.title = 'atlas'; };\n"),
}

# The committed symlink, and it is an ordinary-looking source file inside a package the
# scan really does survey — which is what makes it the interesting case: no `..` appears
# in anything the repo commits as text.
EDGE_LINKS = {
    "packages/server/src/metrics.ts": "../../../../edge-neighbour/shared-lib/src/metrics.ts",
}

# ── the tree inventory, spelled once (R11-A3) ─────────────────────────────────
#
# Which trees exist, what is in each, and which of them carry committed symlinks. It
# lives HERE, in the module that owns the file contents, rather than in
# `sim_fixture_payloads.SIM_REPORT_TREES`, which owns what that module owns: which sim.js
# constant comes out of which tree and what stamp it was scanned at. Two tables, one fact
# each, and the seam between them is the directory name.
#
# R11-A3 is what the other arrangement cost. The `__main__` below wrote five trees from
# its own directory→dict mapping — a second copy of the inventory, in the file people run
# by hand — while `build_trees` in the payload harness wrote the same five from
# `SIM_REPORT_TREES`. The two agreed by inspection, which is the state every drift in
# this repo has started from.
TREES = {
    "cleanrepo": (CLEAN, None),
    "messyrepo": (MESSY, None),
    "cleanrepo-rescanned": (CLEAN_RESCANNED, None),
    "edge-neighbour": (NEIGHBOUR, None),
    "edgerepo": (EDGE, EDGE_LINKS),
}

# Trees that carry no sim.js payload of their own, and that the trees which link INTO
# them need to exist first: written second, `edgerepo`'s committed symlink would point at
# nothing at the moment the scan reads it, and a broken link is a different refusal from
# an escaping one.
SUPPORT_TREES = ("edge-neighbour",)


def write_all(base="/tmp"):
    """Write every tree in `TREES` under `base`. -> `{directory name: root path}`.

    `base` is a parameter so a test can build them under `tmp_path` instead of `/tmp`:
    two runs racing on one hard-coded path is a flake, and `write` starts by `rmtree`-ing
    its target.
    """
    base = pathlib.Path(base)
    order = list(SUPPORT_TREES) + [n for n in TREES if n not in SUPPORT_TREES]
    return {name: write(base / name, *TREES[name]) for name in order}


if __name__ == "__main__":
    built = write_all()
    print("built " + ", ".join(str(root) for root in sorted(built.values())))

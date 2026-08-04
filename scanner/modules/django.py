"""Django scanner module (plan §5.1; phase-1 design note item 3; J7 findings).

Every check in this module is STATIC — file, manifest, regex and AST reads
only. Nothing from the scanned project is imported or run on the Hub
(SEC-SCAN-NOEXEC); the three executing checks are emitted as SandboxSpec jobs
for the Phase-2 sandbox runner and surface as tier=pending_sandbox.

Fleet norms encoded here (J7 cross-cutting inventory findings):
- uv-managed projects (pyproject.toml + uv.lock) are the norm; requirements.txt
  is the classic alternative; missing BOTH is a Blocker (nothing pins deploys).
- ASGI-only serving (daphne/uvicorn + Channels) is universal on the fleet —
  when detected, the manifest service command stays ASGI. NEVER default to
  gunicorn on an ASGI project (SCAN-DJANGO-ASGI).
- compose files carry sidecar processes — celery worker/beat, scheduler
  management loops, one-shot migrate services — each becomes a manifest
  components.jobs entry {name, command, kind}.
"""
import ast
import math
import re
import shlex
import tomllib
from collections import Counter
from pathlib import Path

import yaml

from scanner.core import CheckResult, SandboxSpec, WizardQuestion, register

_SKIP_DIRS = {".git", ".hg", ".venv", "venv", ".venv-scaffold", "node_modules",
              "__pycache__", ".tox", ".mypy_cache", "staticfiles", "dist", "build"}
_DEV_STEMS = {"dev", "development", "local", "test", "testing", "ci"}
_SECURITY_SETTINGS = ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE",
                      "CSRF_COOKIE_SECURE", "SECURE_HSTS_SECONDS",
                      "SECURE_PROXY_SSL_HEADER")
_SECRETISH = ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "PRIVATE", "SIGNING",
              "CREDENTIAL", "SALT", "DSN", "PASS")
_ENV_RE = re.compile(
    r"(?:os\.environ\.get|os\.getenv|os\.environ|\benv)\s*[\(\[]\s*['\"]([A-Z][A-Z0-9_]+)['\"]")
_ENV_DRIVEN_RE = re.compile(
    r"os\.environ|os\.getenv|\benv\(|\bconfig\(|from decouple import|import environ")


def _iter_files(root, pattern):
    for p in sorted(Path(root).rglob(pattern)):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.is_file():
            yield p


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _shannon(s):
    if not s:
        return 0.0
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def _top_assigns(text):
    """Top-level `NAME = <value>` assignments of a settings file, via AST."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
    return out


def _split_cmd(cmd):
    if cmd is None:
        return []
    if isinstance(cmd, list):
        return [str(c) for c in cmd]
    try:
        return shlex.split(str(cmd))
    except ValueError:
        return str(cmd).split()


class DjangoScannerModule:
    """§S1 module object for Django projects. Registered at import time."""

    name = "django"

    # ── detection ───────────────────────────────────────────────────────────
    def detect(self, root):
        return self.project_root(root) is not None

    def project_root(self, root):
        """The directory actually holding the Django project. Real repos nest it
        (backend/, app/backend/ — J7: all four inventoried projects do); search
        manage.py / a Django dependency up to depth 3, skipping vendored trees."""
        root = Path(root)
        skip = {"node_modules", ".venv", "venv", ".git", "dist", "build",
                "reference_impl", "reference-code"}
        candidates = []
        for p in sorted(root.rglob("manage.py")):
            rel = p.relative_to(root)
            if len(rel.parts) <= 4 and not (set(rel.parts[:-1]) & skip):
                candidates.append(p.parent)
        if candidates:
            # Shallowest wins; ties broken alphabetically by the sort above.
            return min(candidates, key=lambda d: len(d.relative_to(root).parts))
        deps = self._deps_text(root)
        if re.search(r"(?im)^\s*[\"']?django\b", deps) or re.search(
                r"(?i)[\"']django[\[>=<~!,\"']", deps):
            return root
        return None

    # ── shared file discovery ───────────────────────────────────────────────
    def _settings_files(self, root):
        found = []
        for p in _iter_files(root, "*.py"):
            if p.name == "settings.py" or p.parent.name == "settings":
                if p.name != "__init__.py":
                    found.append(p)
        return found

    def _prod_settings(self, root):
        return [p for p in self._settings_files(root) if p.stem not in _DEV_STEMS]

    def _deps_text(self, root):
        root = Path(root)
        parts = []
        py = root / "pyproject.toml"
        if py.is_file():
            parts.append(_read(py))
        for req in sorted(root.glob("requirements*.txt")):
            parts.append(_read(req))
        return "\n".join(parts)

    def _compose_files(self, root):
        """Compose files live at the REPO root while manage.py nests in backend/
        (J7: all four inventoried projects) — search the project dir, then walk
        up to the originally scanned root."""
        root = Path(root)
        dirs = [root]
        stop = getattr(self, "_scan_root", None)
        cur = root
        while stop is not None and cur != cur.parent:
            if cur == Path(stop):
                break
            cur = cur.parent
            dirs.append(cur)
            if cur == Path(stop):
                break
        out = []
        for d in dirs:
            for pat in ("docker-compose*.yml", "docker-compose*.yaml",
                        "compose.yml", "compose.yaml"):
                out.extend(sorted(d.glob(pat)))
        # de-dup preserving order
        seen, uniq = set(), []
        for f in out:
            if f not in seen:
                seen.add(f)
                uniq.append(f)
        return uniq

    def _dockerfiles(self, root):
        return list(_iter_files(root, "Dockerfile*"))

    def _dotted(self, root, filename, default):
        """Dotted module path of e.g. asgi.py relative to root ('config.asgi')."""
        for p in _iter_files(root, filename):
            rel = p.relative_to(root).with_suffix("")
            return ".".join(rel.parts)
        return default

    # ── dependency manifest / versions (SCAN-DJANGO-UV) ─────────────────────
    def _dependency_source(self, root):
        root = Path(root)
        has_pyproject = (root / "pyproject.toml").is_file()
        has_lock = (root / "uv.lock").is_file()
        has_reqs = any(root.glob("requirements*.txt"))
        if has_pyproject and has_lock:
            return "uv"
        if has_reqs:
            return "requirements"
        return None

    def _pyproject(self, root):
        py = Path(root) / "pyproject.toml"
        if not py.is_file():
            return {}
        try:
            return tomllib.loads(_read(py))
        except tomllib.TOMLDecodeError:
            return {}

    def _versions(self, root):
        """(python_version, django_version) as (major, minor) tuples or None."""
        project = self._pyproject(root).get("project", {})
        python_v = None
        m = re.search(r"(\d+)\.(\d+)", project.get("requires-python") or "")
        if m:
            python_v = (int(m.group(1)), int(m.group(2)))
        django_v = None
        dep_lines = list(project.get("dependencies") or [])
        for req in sorted(Path(root).glob("requirements*.txt")):
            dep_lines.extend(_read(req).splitlines())
        for line in dep_lines:
            m = re.match(r"\s*[Dd]jango\s*(?:\[[^\]]*\])?\s*[=><~!]+=?\s*(\d+)\.(\d+)", line)
            if m:
                django_v = (int(m.group(1)), int(m.group(2)))
                break
        return python_v, django_v

    # ── server shape (SCAN-DJANGO-ASGI) ─────────────────────────────────────
    def _server_shape(self, root):
        """Returns (mode, argv, detail). ASGI wins whenever detected."""
        deps = self._deps_text(root).lower()
        asgi_text = "".join(_read(p) for p in _iter_files(root, "asgi.py"))
        channels = "channels" in deps or "ProtocolTypeRouter" in asgi_text
        has_daphne = "daphne" in deps
        has_uvicorn = "uvicorn" in deps
        asgi = channels or has_daphne or has_uvicorn
        # Prefer the compose file's own web argv when it already runs an ASGI
        # server — the project author's argv is ground truth.
        for _svc, argv in self._compose_services(root):
            joined = " ".join(argv)
            if "daphne" in joined or "uvicorn" in joined:
                start = next(i for i, a in enumerate(argv) if a in ("daphne", "uvicorn"))
                return "asgi", argv[start:], f"compose web service runs {argv[start]}"
        asgi_mod = self._dotted(root, "asgi.py", "config.asgi")
        if asgi:
            if has_uvicorn and not has_daphne:
                argv = ["uvicorn", f"{asgi_mod}:application",
                        "--host", "0.0.0.0", "--port", "8000"]
                return "asgi", argv, "uvicorn in dependencies"
            why = "daphne in dependencies" if has_daphne else "Channels detected"
            argv = ["daphne", "-b", "0.0.0.0", "-p", "8000", f"{asgi_mod}:application"]
            return "asgi", argv, why
        wsgi_mod = self._dotted(root, "wsgi.py", "config.wsgi")
        argv = ["gunicorn", f"{wsgi_mod}:application", "--bind", "0.0.0.0:8000"]
        return "wsgi", argv, "no ASGI server/Channels found; classic WSGI shape"

    # ── compose sidecars (J7: worker/beat/scheduler/one-shot migrate) ───────
    def _compose_services(self, root):
        out = []
        for cf in self._compose_files(root):
            try:
                data = yaml.safe_load(_read(cf)) or {}
            except yaml.YAMLError:
                continue
            services = data.get("services") if isinstance(data, dict) else None
            if not isinstance(services, dict):
                continue
            for name, svc in services.items():
                if not isinstance(svc, dict):
                    continue
                argv = _split_cmd(svc.get("command") or svc.get("entrypoint"))
                out.append((str(name), argv))
        return out

    def _sidecar_jobs(self, root):
        jobs = []
        for name, argv in self._compose_services(root):
            joined = " ".join(argv)
            if not joined:
                continue  # infra images (redis/postgres) carry no project argv
            if "celery" in joined and "worker" in joined:
                jobs.append({"name": name, "command": argv, "kind": "long_running"})
            elif "celery" in joined and "beat" in joined:
                jobs.append({"name": name, "command": argv, "kind": "long_running"})
            elif "manage.py" in joined and "runserver" in joined:
                continue  # flagged separately as a blocker
            elif "manage.py" in joined and re.search(r"\bmigrate\b", joined) \
                    and "makemigrations" not in joined:
                jobs.append({"name": name, "command": argv, "kind": "one_shot"})
            elif "manage.py" in joined and not any(
                    s in joined for s in ("daphne", "uvicorn", "gunicorn")):
                # a management loop (scheduler etc.) run as its own service
                jobs.append({"name": name, "command": argv, "kind": "long_running"})
        return jobs

    def _runserver_hits(self, root):
        hits = []
        for df in self._dockerfiles(root):
            if "runserver" in _read(df):
                hits.append(str(df.name))
        for name, argv in self._compose_services(root):
            if "runserver" in " ".join(argv):
                hits.append(f"compose service '{name}'")
        return hits

    # ── static checks ───────────────────────────────────────────────────────
    def checks(self, root):
        self._scan_root = Path(root)
        root = self.project_root(root) or Path(root)
        results = []
        settings = self._settings_files(root)
        prod = self._prod_settings(root)
        prod_texts = {p: _read(p) for p in prod}
        all_texts = {p: _read(p) for p in settings}
        prod_union = "\n".join(prod_texts.values())
        all_union = "\n".join(all_texts.values())

        results.append(self._check_settings_shape(settings, all_texts))
        results.append(self._check_debug(root, prod_texts))
        results.append(self._check_secret_key(root, all_texts))
        results.append(self._check_allowed_hosts(root, prod_texts))
        results.append(self._check_db_engine(prod_union))
        results.append(self._check_static_root(all_union))
        results.append(self._check_security_settings(prod, prod_union))
        csrf = self._check_csrf_trusted(root, prod_union, all_union)
        if csrf:
            results.append(csrf)
        results.append(self._check_dependency_manifest(root))
        results.append(self._check_deps_pinned(root))
        results.append(self._check_versions(root))
        results.append(self._check_server_mode(root))
        sidecar = self._check_sidecars(root)
        if sidecar:
            results.append(sidecar)
        results.append(self._check_runserver(root))
        return results

    def _check_settings_shape(self, settings, all_texts):
        split = any(p.parent.name == "settings" for p in settings)
        if split:
            return CheckResult(
                id="django.settings-shape", tier="ok", title="Settings are a split package",
                detail="Found a settings/ package (base + per-environment modules).")
        env_driven = any(_ENV_DRIVEN_RE.search(t) for t in all_texts.values())
        if settings and env_driven:
            return CheckResult(
                id="django.settings-shape", tier="ok",
                title="Single settings module, env-driven",
                detail="settings.py reads its configuration from the environment.")
        detail = ("A single hardcoded settings.py serves every environment."
                  if settings else "No settings module could be located.")
        return CheckResult(
            id="django.settings-shape", tier="warning",
            title="Settings are a single hardcoded file", detail=detail,
            fix_hint=("One settings file means dev values ship to production. Split into "
                      "config/settings/{base,dev,prod}.py (prod imports base and overrides), "
                      "or read every environment-specific value via os.environ."))

    def _check_debug(self, root, prod_texts):
        offenders = []
        for path, text in prod_texts.items():
            val = _top_assigns(text).get("DEBUG")
            if isinstance(val, ast.Constant) and val.value is True:
                offenders.append(str(path.relative_to(root)))
        if offenders:
            return CheckResult(
                id="django.debug-hardcoded", tier="blocker",
                title="DEBUG is hardcoded True in prod-reachable settings",
                detail="DEBUG = True in: " + ", ".join(offenders),
                fix_hint=("DEBUG=True serves full tracebacks and settings dumps to every "
                          "visitor. Read it from the environment — DEBUG = "
                          "os.environ.get('DJANGO_DEBUG', '0') == '1' — and leave "
                          "DJANGO_DEBUG unset in production."))
        return CheckResult(id="django.debug-hardcoded", tier="ok",
                           title="DEBUG is not hardcoded True",
                           detail="No prod-reachable settings file pins DEBUG = True.")

    def _check_secret_key(self, root, all_texts):
        offenders = []
        for path, text in all_texts.items():
            for name, val in _top_assigns(text).items():
                if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
                    continue
                literal = val.value
                secretish = any(s in name for s in _SECRETISH)
                if name == "SECRET_KEY" or (secretish and literal):
                    offenders.append(f"{path.relative_to(root)}: {name}")
                elif len(literal) >= 24 and _shannon(literal) > 4.0:
                    offenders.append(f"{path.relative_to(root)}: {name} (high-entropy literal)")
        if offenders:
            return CheckResult(
                id="django.secret-key-literal", tier="blocker",
                title="Secret material is a literal in source",
                detail="; ".join(sorted(offenders)),
                fix_hint=("A secret in source sits in git history forever and in every "
                          "clone. Load it from the environment — SECRET_KEY = "
                          "os.environ['DJANGO_SECRET_KEY'] — rotate the leaked value, and "
                          "store the new one through the Hub vault."))
        return CheckResult(id="django.secret-key-literal", tier="ok",
                           title="No secret literals in settings",
                           detail="SECRET_KEY and friends come from the environment.")

    def _check_allowed_hosts(self, root, prod_texts):
        seen, blank = False, []
        for path, text in prod_texts.items():
            val = _top_assigns(text).get("ALLOWED_HOSTS")
            if val is None:
                continue
            seen = True
            if isinstance(val, (ast.List, ast.Tuple)) and not val.elts:
                blank.append(str(path.relative_to(root)))
        if seen and not blank:
            return CheckResult(id="django.allowed-hosts", tier="ok",
                               title="ALLOWED_HOSTS is configured",
                               detail="Set (literal hosts or env-driven) in prod settings.")
        detail = ("ALLOWED_HOSTS = [] in: " + ", ".join(blank)) if blank else \
            "No prod-reachable settings file sets ALLOWED_HOSTS."
        return CheckResult(
            id="django.allowed-hosts", tier="warning",
            title="ALLOWED_HOSTS is empty or absent", detail=detail,
            fix_hint=("With DEBUG off, Django refuses every request when ALLOWED_HOSTS is "
                      "empty — the site 500s the moment it goes live. Set ALLOWED_HOSTS = "
                      "os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') and supply the "
                      "domain via the wizard."))

    def _check_db_engine(self, prod_union):
        if "sqlite3" in prod_union:
            return CheckResult(
                id="django.db-engine", tier="warning",
                title="SQLite engine in prod-reachable settings",
                detail="django.db.backends.sqlite3 found in prod-reachable settings.",
                fix_hint=("SQLite is a single local file: no concurrent writers, lost on "
                          "container rebuild, invisible to backups. Point prod at Postgres "
                          "— ENGINE 'django.db.backends.postgresql' with env-driven "
                          "credentials — and keep SQLite for dev only."))
        engine = "postgresql" if "postgresql" in prod_union else \
            ("mysql" if "mysql" in prod_union else "not declared in settings")
        return CheckResult(id="django.db-engine", tier="ok",
                           title="Database engine", detail=f"Engine: {engine}.")

    def _check_static_root(self, all_union):
        if "STATIC_ROOT" in all_union:
            return CheckResult(id="django.static-root", tier="ok",
                               title="STATIC_ROOT is set",
                               detail="collectstatic has a destination.")
        return CheckResult(
            id="django.static-root", tier="warning",
            title="STATIC_ROOT is absent",
            detail="No settings file sets STATIC_ROOT.",
            fix_hint=("Without STATIC_ROOT, collectstatic has nowhere to write and the "
                      "admin/site CSS 404s behind a real server. Set STATIC_ROOT = "
                      "BASE_DIR / 'staticfiles' (or /srv/static) so the pipeline can "
                      "collect and serve assets."))

    def _check_security_settings(self, prod, prod_union):
        missing = [n for n in _SECURITY_SETTINGS if n not in prod_union]
        if prod and not missing:
            return CheckResult(id="django.security-settings", tier="ok",
                               title="HTTPS security settings present",
                               detail="All of: " + ", ".join(_SECURITY_SETTINGS))
        return CheckResult(
            id="django.security-settings", tier="warning",
            title="Security settings missing in prod",
            detail="Missing: " + ", ".join(missing or _SECURITY_SETTINGS),
            fix_hint=("These settings make sessions HTTPS-only behind the proxy: without "
                      "them cookies leak over plain HTTP and Django cannot see the TLS "
                      "termination. Add to prod settings: SECURE_SSL_REDIRECT = True, "
                      "SESSION_COOKIE_SECURE = True, CSRF_COOKIE_SECURE = True, "
                      "SECURE_HSTS_SECONDS = 31536000, SECURE_PROXY_SSL_HEADER = "
                      "('HTTP_X_FORWARDED_PROTO', 'https')."))

    def _check_csrf_trusted(self, root, prod_union, all_union):
        if "CSRF_TRUSTED_ORIGINS" in prod_union:
            return CheckResult(id="django.csrf-trusted-origins", tier="ok",
                               title="CSRF_TRUSTED_ORIGINS is set",
                               detail="Cross-origin POSTs from the SPA/domain will pass.")
        indicators = (re.search(r"cors[-_]?headers", self._deps_text(root), re.I) is not None
                      or "corsheaders" in all_union
                      or any(True for _ in _iter_files(root, "package.json")))
        if indicators:
            return CheckResult(
                id="django.csrf-trusted-origins", tier="advice",
                title="CSRF_TRUSTED_ORIGINS absent with a SPA/CORS frontend present",
                detail="CORS/SPA indicators found but no CSRF_TRUSTED_ORIGINS in prod settings.",
                fix_hint=("A separate frontend origin means Django 4+ rejects its POSTs "
                          "with 403 CSRF failures in production. Set CSRF_TRUSTED_ORIGINS "
                          "= ['https://<your-domain>'] in prod settings (env-driven, so "
                          "the wizard's domain answer feeds it)."))
        return None

    def _check_dependency_manifest(self, root):
        source = self._dependency_source(root)
        if source == "uv":
            return CheckResult(id="django.dependency-manifest", tier="ok",
                               title="Dependency manifest: uv",
                               detail="source: uv (pyproject.toml + uv.lock) — fleet norm.")
        if source == "requirements":
            return CheckResult(id="django.dependency-manifest", tier="ok",
                               title="Dependency manifest: requirements.txt",
                               detail="source: requirements (requirements*.txt).")
        return CheckResult(
            id="django.dependency-manifest", tier="blocker",
            title="No dependency manifest found",
            detail="Neither pyproject.toml + uv.lock nor requirements*.txt is present.",
            fix_hint=("Without a manifest the build cannot reproduce your environment — "
                      "every deploy would guess at versions. Adopt uv (uv init, uv add "
                      "django, commit pyproject.toml + uv.lock) or commit a pinned "
                      "requirements.txt."))

    def _check_deps_pinned(self, root):
        root = Path(root)
        if (root / "uv.lock").is_file():
            return CheckResult(id="django.deps-pinned", tier="ok",
                               title="Dependencies are locked",
                               detail="uv.lock pins the full resolved dependency set.")
        unpinned = []
        for req in sorted(root.glob("requirements*.txt")):
            for line in _read(req).splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                if "==" not in line:
                    unpinned.append(line.split()[0])
        if unpinned:
            return CheckResult(
                id="django.deps-pinned", tier="warning",
                title="Requirements are unpinned",
                detail="No lockfile, and unpinned entries: " + ", ".join(sorted(set(unpinned))),
                fix_hint=("Unpinned requirements make every build a lottery — a transitive "
                          "release can break prod with zero code change. Pin exact versions "
                          "(pip freeze > requirements.txt) or move to uv for a real "
                          "lockfile."))
        return CheckResult(id="django.deps-pinned", tier="ok",
                           title="Dependencies are pinned",
                           detail="All requirements entries pin exact versions.")

    def _check_versions(self, root):
        python_v, django_v = self._versions(root)
        py_s = f"{python_v[0]}.{python_v[1]}" if python_v else "not declared"
        dj_s = f"{django_v[0]}.{django_v[1]}" if django_v else "not declared"
        detail = f"Python: {py_s} (requires-python); Django: {dj_s} (dependency spec)."
        py_bad = python_v is not None and not ((3, 12) <= python_v <= (3, 14))
        dj_bad = django_v is not None and not ((5, 2) <= django_v < (7, 0))
        if py_bad or dj_bad:
            return CheckResult(
                id="django.runtime-versions", tier="advice",
                title="Runtime versions outside the supported window", detail=detail,
                fix_hint=("The fleet standard is Python 3.12–3.14 and Django 5.2–6.x; "
                          "outside that window the base images and playbooks here are "
                          "untested. Bump requires-python / the Django pin, or expect "
                          "manual image work."))
        return CheckResult(id="django.runtime-versions", tier="ok",
                           title="Runtime versions recorded", detail=detail)

    def _check_server_mode(self, root):
        mode, argv, why = self._server_shape(root)
        if mode == "asgi":
            return CheckResult(
                id="django.server-mode", tier="ok",
                title="ASGI serving detected",
                detail=f"ASGI ({argv[0]}): {why}. Service argv: {' '.join(argv)}.")
        return CheckResult(
            id="django.server-mode", tier="ok",
            title="WSGI serving (gunicorn)",
            detail=f"WSGI: {why}. Service argv: {' '.join(argv)}.")

    def _check_sidecars(self, root):
        if not self._compose_files(root):
            return None
        jobs = self._sidecar_jobs(root)
        if not jobs:
            return CheckResult(id="django.sidecars", tier="ok",
                               title="No sidecar processes in compose",
                               detail="Compose defines no worker/beat/scheduler/migrate jobs.")
        listing = "; ".join(f"{j['name']} ({j['kind']}): {' '.join(j['command'])}"
                            for j in jobs)
        return CheckResult(
            id="django.sidecars", tier="ok",
            title=f"Sidecar processes recorded ({len(jobs)})",
            detail=listing + " — each becomes a manifest components.jobs entry.")

    def _check_runserver(self, root):
        hits = self._runserver_hits(root)
        if hits:
            return CheckResult(
                id="django.runserver", tier="blocker",
                title="runserver used as a container command",
                detail="Found in: " + ", ".join(hits),
                fix_hint=("runserver is Django's dev server: single-threaded, no security "
                          "hardening, and the docs forbid production use. Replace the "
                          "container command with daphne/uvicorn (ASGI) or gunicorn "
                          "(WSGI) bound to 0.0.0.0:8000."))
        return CheckResult(id="django.runserver", tier="ok",
                           title="No runserver in container files",
                           detail="Dockerfile/compose entries use a real app server.")

    # ── executing checks: EMITTED as sandbox specs, never run here (§M1) ────
    def sandbox_checks(self, root):
        self._scan_root = Path(root)
        root = self.project_root(root) or Path(root)
        return [
            SandboxSpec(
                id="django.check-deploy",
                command=["python", "manage.py", "check", "--deploy"],
                why="Django's own deploy checklist; needs the app importable, so sandbox."),
            SandboxSpec(
                id="django.migrations-check",
                command=["python", "manage.py", "makemigrations", "--check", "--dry-run"],
                why="Detects model changes missing a migration; imports the app, so sandbox."),
            SandboxSpec(
                id="django.collectstatic",
                command=["python", "manage.py", "collectstatic", "--noinput", "--dry-run"],
                why="Proves static collection succeeds before a deploy depends on it."),
        ]

    # ── wizard ──────────────────────────────────────────────────────────────
    def _env_names(self, root):
        names = set()
        for p in self._settings_files(root):
            names.update(_ENV_RE.findall(_read(p)))
        names.discard("DJANGO_SETTINGS_MODULE")
        return sorted(names)

    def wizard_questions(self, root):
        self._scan_root = Path(root)
        root = self.project_root(root) or Path(root)
        questions = [
            WizardQuestion(id="django.domain", prompt="Public domain for this site",
                           kind="text"),
            WizardQuestion(id="django.exposure", prompt="How is this site exposed?",
                           kind="choice", default="public", choices=["public", "mesh_only"]),
            WizardQuestion(id="django.db", prompt="Database for production",
                           kind="choice", default="postgres",
                           choices=["postgres", "mysql", "sqlite"]),
        ]
        for name in self._env_names(root):
            secretish = any(s in name for s in _SECRETISH)
            questions.append(WizardQuestion(
                id=f"django.env.{name}",
                prompt=f"Value for environment variable {name}",
                kind="secret" if secretish else "text"))
        return questions

    # ── manifest fragment (§V5: ONE manifest) ───────────────────────────────
    def _liveness_path(self, root):
        for p in _iter_files(root, "urls*.py"):
            text = _read(p)
            if "healthz" in text:
                return "/healthz"
            if re.search(r"path\(\s*['\"]health", text):
                return "/health"
        return None

    def manifest_fragment(self, root, answers=None):
        self._scan_root = Path(root)
        root = self.project_root(root) or Path(root)
        _mode, argv, _why = self._server_shape(root)
        fragment = {
            "components": {
                "service": {"kind": "django", "command": argv, "port": 8000},
                "jobs": self._sidecar_jobs(root),
            },
            "healthz": {"liveness_path": self._liveness_path(root)},
            "dependency_source": self._dependency_source(root),
        }
        if answers:
            if answers.get("django.exposure"):
                fragment["exposure"] = answers["django.exposure"]
            if answers.get("django.domain"):
                fragment["domain"] = answers["django.domain"]
        return fragment


module = register(DjangoScannerModule())

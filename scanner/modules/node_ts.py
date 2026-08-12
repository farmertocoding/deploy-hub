"""Node/TS scanner module (scanner addendum §S2–S4; review3 §N1–N7; fixture §Q7).

Understands the reference trading stack: pnpm monorepo, Fastify + native `ws`
service, CCXT-style ingestion daemon, worker_threads S/R engine, a Python
offline backtesting component, and local on-disk state (Parquet/SQLite/DuckDB).

Every check in this module is STATIC — file, JSON, TOML, YAML and regex reads
only (SEC-SCAN-NOEXEC, review3 §M1). The three executing checks (install with
--ignore-scripts, `tsc --noEmit`, production build) are EMITTED as SandboxSpec
jobs for the Phase-2 sandbox runner and surface as tier=pending_sandbox.

Check-id naming follows the fixture contract in `sample-node-site/MUTATIONS.md`
(`node-ts.compiled-js`, `node-ts.graceful-shutdown`, `node-ts.ingest-reconnect`,
…) — that table is the negative-case contract these checks are tested against.
"""
import json
import re
import tomllib
from pathlib import Path

import yaml

from scanner.core import CheckResult, SandboxSpec, WizardQuestion, register

_SKIP_DIRS = {".git", "node_modules", ".pnpm-store", "dist", "build", "coverage",
              "__pycache__", ".venv", "venv"}
_SOURCE_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs")

# §S3 detection: server frameworks that mark a deployable Node service.
_SERVER_DEPS = ("fastify", "express", "koa")
_RECOGNIZED_DEPS = ("fastify", "ws", "zod", "ccxt")
_INGESTION_DEPS = ("ccxt",)                       # arm the ingestion checks
_OFFLINE_DEPS = ("vectorbt", "polars", "duckdb")  # Python offline component
_EXCLUSIVE_UPSTREAMS = ("alpaca",)                # one ws per account (§N4)
_DATA_SUFFIXES = (".parquet", ".duckdb", ".sqlite3")
_SERVERISH_MAIN_RE = re.compile(
    r"(?:^|/)(?:dist|build|out|src)/(?:index|server|main|app)\.[mc]?js$")
_BROKER_ENV_RE = re.compile(
    r"^(?:ALPACA|FINMIND|BINANCE|BROKER|IBKR)_[A-Z0-9_]*|^[A-Z0-9_]*_(?:KEY_ID|SECRET|TOKEN)\s*=",
    re.MULTILINE)
_SIGTERM_RE = re.compile(r"process\.on\(\s*['\"]SIGTERM['\"]")
# Object-literal field form only (`ready: <expr>`), the §N2 pinned JSON shape —
# the `=` form would also match prose in doc comments ("ready = warm engine").
_READY_RE = re.compile(r"\bready\s*:\s*([^,;\n]+)")
_PORT_DEFAULT_RE = re.compile(r"process\.env\.PORT\s*\?\?\s*(\d+)")
_WORKERS_DEFAULT_RE = re.compile(r"process\.env\.WORKER_THREADS\s*\?\?\s*(\d+)")


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_tsconfig(path):
    """tsconfig is JSONC in the wild — strip // and /* */ comments, then parse."""
    text = _read(path)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    try:
        return json.loads(text)
    except ValueError:
        return {}


def _iter_source_files(base):
    """Yield the module's source files under `base`.

    OUT OF ROUND-7 SCOPE, fixed on the round-7 branch: this followed symlinked
    directories, so a repo containing one link back at an ancestor was an infinite walk
    — and it runs during MODULE DETECTION, before any check, so the operator's scan never
    returned at all. Found by the SRE reviewer while testing loops.

    `fallbacks._iter_files` already had the treatment and this is that treatment rather
    than a second one: a symlinked DIRECTORY is not followed (a link out of the tree is
    not the project's source and a link back into it is a loop), and `resolve()` into a
    `seen` set catches the loops that a hard link or a `..`-shaped path can still make.
    Symlinked FILES are still read, which is the same distinction `fallbacks` draws for
    the same reason: a committed symlinked config file is real source.
    """
    stack = [Path(base)]
    seen = set()
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            if path.is_symlink() and path.is_dir():
                continue
            if path.is_dir():
                if path.name in _SKIP_DIRS or path.name.startswith("."):
                    continue
                try:
                    key = path.resolve()
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                stack.append(path)
            elif path.is_file() and path.suffix in _SOURCE_SUFFIXES:
                yield path


class _Survey:
    """One static pass over the tree; every check reads from here."""

    def __init__(self, root):
        self.root = Path(root)
        self.workspace_file = self.root / "pnpm-workspace.yaml"
        self.package_dirs = self._find_package_dirs()
        self.packages = {d: _load_json(d / "package.json") for d in self.package_dirs}
        self.service_dir = self._pick_service_dir()
        self.service_pkg = self.packages.get(self.service_dir, {})
        base = self.service_dir if self.service_dir else self.root
        self.service_sources = {p: _read(p) for p in _iter_source_files(base)}
        self.all_sources = ("\n".join(_read(p) for d in self.package_dirs
                                      for p in _iter_source_files(d))
                            if self.package_dirs else
                            "\n".join(self.service_sources.values()))
        self.all_deps = self._collect_deps()
        self.data_files = self._find_data_files()
        self.offline_deps = self._offline_deps()
        self.env_example = _read(self.root / ".env.example")

    # ── workspace / packages ────────────────────────────────────────────────
    def _find_package_dirs(self):
        dirs = []
        if (self.root / "package.json").is_file():
            dirs.append(self.root)
        patterns = []
        if self.workspace_file.is_file():
            try:
                data = yaml.safe_load(_read(self.workspace_file)) or {}
            except yaml.YAMLError:
                data = {}
            patterns.extend(p for p in (data.get("packages") or []) if isinstance(p, str))
        root_pkg = _load_json(self.root / "package.json")
        workspaces = root_pkg.get("workspaces")
        if isinstance(workspaces, list):
            patterns.extend(p for p in workspaces if isinstance(p, str))
        for pattern in patterns:
            for candidate in sorted(self.root.glob(pattern)):
                if candidate.is_dir() and (candidate / "package.json").is_file():
                    dirs.append(candidate)
        return dirs

    def workspace_names(self):
        return [d.name if d != self.root else "." for d in self.package_dirs
                if d != self.root or len(self.package_dirs) == 1]

    @staticmethod
    def _deps(pkg, dev=False):
        section = pkg.get("devDependencies" if dev else "dependencies")
        return dict(section) if isinstance(section, dict) else {}

    def _collect_deps(self):
        out = {}
        for pkg in self.packages.values():
            out.update(self._deps(pkg))
        return out

    def _pick_service_dir(self):
        """Deployable service heuristic (§S3): a server/ws dep plus a main/bin
        entry point. The wizard confirms the pick; this is only the default."""
        candidates = []
        for directory, pkg in self.packages.items():
            deps = self._deps(pkg)
            server_dep = (any(d in deps for d in _SERVER_DEPS) or "ws" in deps
                          or any(d.startswith("@nestjs/") for d in deps))
            entry = pkg.get("main") or pkg.get("bin") or \
                (pkg.get("scripts") or {}).get("start")
            if server_dep and entry:
                score = 2 if any(d in deps for d in _SERVER_DEPS) else 1
                candidates.append((score, directory))
        if candidates:
            return max(candidates, key=lambda c: c[0])[1]
        return None

    def service_name(self):
        if self.service_dir is None:
            return None
        return "." if self.service_dir == self.root else self.service_dir.name

    def service_scripts(self):
        scripts = self.service_pkg.get("scripts")
        return dict(scripts) if isinstance(scripts, dict) else {}

    def service_text(self):
        return "\n".join(self.service_sources.values())

    def healthz_text(self):
        """Concatenated text of source files whose code mentions healthz."""
        return "\n".join(t for t in self.service_sources.values() if "healthz" in t.lower())

    # ── python offline component (§S3 co-detection, §N7) ────────────────────
    def _offline_deps(self):
        py = self.root / "pyproject.toml"
        if not py.is_file():
            return []
        try:
            data = tomllib.loads(_read(py))
        except tomllib.TOMLDecodeError:
            return []
        dep_lines = [str(d) for d in (data.get("project", {}).get("dependencies") or [])]
        joined = "\n".join(dep_lines).lower()
        return sorted(d for d in _OFFLINE_DEPS if d in joined)

    # ── local state (§S3 data-path heuristics, §N1/N5/N6) ───────────────────
    def _find_data_files(self):
        found = []
        stack = [self.root]
        while stack:
            directory = stack.pop()
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                continue
            for path in entries:
                if path.is_dir():
                    if path.name not in _SKIP_DIRS and not path.name.startswith("."):
                        stack.append(path)
                elif path.is_file():
                    if path.suffix in _DATA_SUFFIXES or path.name.endswith("-wal"):
                        found.append(path.relative_to(self.root))
        return found

    def data_dir(self):
        if self.data_files:
            parts = self.data_files[0].parts
            return parts[0] if len(parts) > 1 else "."
        return "data"

    # ── cross-cutting signals ───────────────────────────────────────────────
    def ingestion_armed(self):
        return any(d in self.all_deps for d in _INGESTION_DEPS)

    def exclusive_upstreams(self):
        haystack = (self.service_text() + "\n" + self.env_example).lower()
        found = sorted({u for u in _EXCLUSIVE_UPSTREAMS if u in haystack})
        if "EXCLUSIVE_UPSTREAM" in self.service_text() and not found:
            found = ["(declared via EXCLUSIVE_UPSTREAM marker)"]
        return found

    def handoff_hook(self):
        """A pre-stop ingestion-handoff hook counts only as a SCRIPT entry —
        prose in comments does not satisfy §N4."""
        for pkg in self.packages.values():
            scripts = pkg.get("scripts")
            if not isinstance(scripts, dict):
                continue
            for key in scripts:
                if re.search(r"pre[-_]?stop|handoff", key, re.IGNORECASE):
                    return key
        return None

    def broker_env_names(self):
        return sorted({m.split("=")[0].strip() for m in
                       _BROKER_ENV_RE.findall(self.env_example)} - {""})

    def port(self):
        m = _PORT_DEFAULT_RE.search(self.service_text())
        return int(m.group(1)) if m else None

    def worker_threads_default(self):
        m = _WORKERS_DEFAULT_RE.search(self.all_sources)
        return int(m.group(1)) if m else 2

    def financial_signals(self):
        return bool(self.broker_env_names() or self.exclusive_upstreams()
                    or self.ingestion_armed())


class NodeTsScannerModule:
    """§S1 module object for Node/TS service stacks. Registered at import time."""

    name = "node-ts"

    # Core results this module replaces outright (D-010 follow-up item 1). It
    # re-derives `core.lockfile` because the pnpm-workspace shape and the §N7 offline
    # Python component both change what "locked" means here, and because the sandbox's
    # `pnpm install --frozen-lockfile` is what the warning is really about. Everything
    # else in the core suite reaches the report untouched; superseding it would need a
    # line here first.
    supersedes = frozenset({"core.lockfile"})

    # ── detection (§S3, SCAN-S3-DETECTION-RULES) ────────────────────────────
    def detect(self, root):
        root = Path(root)
        if (root / "pnpm-workspace.yaml").is_file():
            return True
        survey = _Survey(root)
        for pkg in survey.packages.values():
            deps = _Survey._deps(pkg)
            if any(d in deps for d in _SERVER_DEPS):
                return True
            if any(d.startswith("@nestjs/") for d in deps):
                return True
            main = pkg.get("main")
            if isinstance(main, str) and _SERVERISH_MAIN_RE.search(main):
                return True
        return False

    # ── static checks (§S4) ─────────────────────────────────────────────────
    def checks(self, root):
        s = _Survey(root)
        results = []
        override = self._lockfile_override(s)
        if override is not None:
            results.append(override)
        results.extend(self._detection_recording(s))
        results.append(self._check_strict_build(s))
        results.append(self._check_compiled_js(s))
        results.append(self._check_engines_pin(s))
        results.append(self._check_bun_dev_only(s))
        if "fastify" in s.all_deps:
            results.append(self._check_fastify_serving(s))
        results.append(self._check_graceful_shutdown(s))
        results.append(self._check_ws_heartbeat(s))
        results.append(self._check_readiness_pattern(s))
        if s.ingestion_armed():
            results.append(self._check_ingest_reconnect(s))
            results.append(self._check_ingest_staleness(s))
            results.append(self._check_ingest_backfill(s))
        results.append(self._check_exclusive_upstream(s))
        results.append(self._check_local_state(s))
        results.append(self._check_secrets_env(s))
        if s.offline_deps:
            results.append(self._check_jobs_image(s))
        return results

    def _lockfile_override(self, s):
        """Re-derive core.lockfile over the Node side when the pyproject is the
        recognized §N7 offline component: it is manual-v1, never deployed as a
        serving process, and its lock lands with the Phase-3 jobs_image build —
        an unlocked offline pyproject must not mask the pnpm lock status.

        Returns a CheckResult that SUPERSEDES the registry-composed generic
        `core.lockfile` (D-010: same id, replaced in place), or None to leave the
        generic result standing. `scanner.core.scan` guarantees the entry exists.
        """
        if not s.offline_deps:
            return None
        node_locks = ("package-lock.json", "package-lock.yaml",
                      "pnpm-lock.yaml", "yarn.lock")
        has_manifest = any((d / "package.json").is_file()
                           for d in (s.package_dirs or [s.root]))
        node_locked = any((s.root / name).is_file() for name in node_locks)
        if has_manifest and not node_locked:
            return CheckResult(
                id="core.lockfile", tier="warning",
                title="Dependency manifest without a lockfile",
                detail="package.json without package-lock.json / pnpm-lock.yaml / "
                       "yarn.lock — `pnpm install --frozen-lockfile` (the sandbox "
                       "CI-honesty check) cannot pass.",
                fix_hint="Commit the pnpm lockfile so deploys are reproducible — "
                         "the same source must build the same image every time.")
        return CheckResult(
            id="core.lockfile", tier="ok",
            title="Node dependency manifests are locked",
            detail="pnpm lockfile present. The Python pyproject.toml is the "
                   "§N7 offline component (manual-v1): its lock is deferred "
                   "to the Phase-3 jobs_image build, not a deploy gate.")

    # ── §S3 detection recording — ok-tier informational results ─────────────
    def _detection_recording(self, s):
        out = []
        if s.workspace_file.is_file():
            names = ", ".join(s.workspace_names()) or "(none found)"
            out.append(CheckResult(
                id="node-ts.monorepo", tier="ok", title="pnpm monorepo detected",
                detail=f"pnpm-workspace.yaml — workspace packages: {names}."))
        else:
            out.append(CheckResult(
                id="node-ts.monorepo", tier="ok", title="Single-package Node project",
                detail="No pnpm-workspace.yaml; the root package.json is the package."))
        if s.service_dir is not None:
            entry = s.service_pkg.get("main") or s.service_pkg.get("bin") or "?"
            out.append(CheckResult(
                id="node-ts.service-package", tier="ok",
                title=f"Deployable service package: {s.service_name()}",
                detail=f"Heuristic pick (server/ws dependency + entry point {entry}); "
                       "the wizard confirms this choice."))
        else:
            out.append(CheckResult(
                id="node-ts.service-package", tier="warning",
                title="No deployable service package identified",
                detail="No workspace package has a server framework dependency plus a "
                       "main/bin entry point.",
                fix_hint="Give the service package a `main` (compiled entry) or `bin`, "
                         "or pick the package explicitly in the wizard."))
        recognized = sorted(d for d in _RECOGNIZED_DEPS if d in s.all_deps)
        armed = " — ccxt present: ingestion-daemon checks armed" if s.ingestion_armed() else ""
        out.append(CheckResult(
            id="node-ts.recognized-deps", tier="ok",
            title="Recognized dependencies recorded",
            detail=f"Recognized: {', '.join(recognized) or '(none)'}{armed}."))
        uses_workers = ("worker_threads" in s.all_sources
                        or "SharedArrayBuffer" in s.all_sources)
        out.append(CheckResult(
            id="node-ts.worker-threads", tier="ok",
            title="worker_threads usage " + ("detected" if uses_workers else "not detected"),
            detail=("worker_threads/SharedArrayBuffer run fine in Docker, no special "
                    "flags (COOP/COEP is a browser concern, §S4 workers); the wizard's "
                    "thread-count answer feeds container CPU guidance."
                    if uses_workers else
                    "No worker_threads/SharedArrayBuffer usage found in sources.")))
        if s.offline_deps:
            out.append(CheckResult(
                id="node-ts.offline-component", tier="ok",
                title="Python offline component present",
                detail="pyproject.toml with " + ", ".join(s.offline_deps) +
                       " — co-detected, never blocking (§S3): an offline analysis "
                       "component, not a serving process and not its own Site (§V5)."))
        return out

    # ── build & runtime ─────────────────────────────────────────────────────
    def _check_strict_build(self, s):
        base = s.service_dir or s.root
        tsconfig_path = base / "tsconfig.json"
        if not tsconfig_path.is_file():
            tsconfig_path = s.root / "tsconfig.json"
        if not tsconfig_path.is_file():
            return CheckResult(
                id="node-ts.strict-build", tier="warning",
                title="No tsconfig.json found",
                detail="The service package has no tsconfig.json — strict mode "
                       "cannot be verified.",
                fix_hint="Add a tsconfig.json with \"strict\": true; the sandbox "
                         "`tsc --noEmit` check verifies the build stays clean.")
        options = _load_tsconfig(tsconfig_path).get("compilerOptions", {})
        if options.get("strict") is True:
            return CheckResult(
                id="node-ts.strict-build", tier="ok",
                title="TypeScript strict mode is on",
                detail=f"{tsconfig_path.name} of the service package sets "
                       "\"strict\": true; `tsc --noEmit` runs in the sandbox.")
        return CheckResult(
            id="node-ts.strict-build", tier="warning",
            title="TypeScript strict mode is off or absent",
            detail=f"compilerOptions.strict is not true in {tsconfig_path.name}.",
            fix_hint="Strict mode is what makes `tsc --noEmit` a real gate — without "
                     "it whole error classes (implicit any, null misuse) ship "
                     "silently. Set \"strict\": true and fix what surfaces.")

    def _check_compiled_js(self, s):
        start = s.service_scripts().get("start", "")
        if re.search(r"\bts-node\b|\btsx\b", start):
            return CheckResult(
                id="node-ts.compiled-js", tier="warning",
                title="Production start script transpiles at runtime",
                detail=f"start script: `{start}` — ts-node/tsx in the runtime path.",
                fix_hint="Production runs compiled JS (§S4): transpiling on boot slows "
                         "startup and drags dev tooling into the runtime image. Build "
                         "with `tsc -p .` and set start to `node dist/index.js`.")
        if not start:
            return CheckResult(
                id="node-ts.compiled-js", tier="warning",
                title="No start script in the service package",
                detail="The service package.json has no scripts.start entry.",
                fix_hint="Add `\"start\": \"node dist/index.js\"` so the container "
                         "command is declared by the project, not guessed.")
        if re.search(r"\bnode\b", start) and re.search(r"\b(dist|build|out)/", start):
            return CheckResult(
                id="node-ts.compiled-js", tier="ok",
                title="Production runs compiled JS",
                detail=f"start script: `{start}`.")
        return CheckResult(
            id="node-ts.compiled-js", tier="warning",
            title="Start script does not run compiled JS with node",
            detail=f"start script: `{start}`.",
            fix_hint="Production runs compiled JS with node (§S4): build to dist/ "
                     "and set start to `node dist/index.js`.")

    def _check_engines_pin(self, s):
        pkg = s.service_pkg if s.service_dir is not None else \
            _load_json(s.root / "package.json")
        engines = (pkg.get("engines") or {})
        node_range = engines.get("node") if isinstance(engines, dict) else None
        if isinstance(node_range, str):
            m = re.search(r"(\d+)", node_range)
            if m and int(m.group(1)) == 22:
                return CheckResult(
                    id="node-ts.engines-pin", tier="ok",
                    title="engines.node pinned to Node 22 LTS",
                    detail=f"Service package engines.node: \"{node_range}\" — the "
                           "generated image uses that exact line.")
            return CheckResult(
                id="node-ts.engines-pin", tier="warning",
                title="engines.node is not Node 22 LTS",
                detail=f"Service package engines.node: \"{node_range}\".",
                fix_hint="The fleet base image is Node 22 LTS; another pin means the "
                         "image and the declared runtime disagree. Set "
                         "`\"engines\": {\"node\": \"22.x\"}` in the service package.")
        return CheckResult(
            id="node-ts.engines-pin", tier="warning",
            title="engines.node is absent from the service package",
            detail="The deployable package declares no engines.node.",
            fix_hint="Without an engines pin the runtime version is whatever the "
                     "image happens to carry. Add `\"engines\": {\"node\": \"22.x\"}` "
                     "to the service package.json.")

    def _check_bun_dev_only(self, s):
        offenders = []
        start = s.service_scripts().get("start", "")
        if re.search(r"\bbun\b", start):
            offenders.append(f"start script: `{start}`")
        main = s.service_pkg.get("main")
        if isinstance(main, str) and re.search(r"\bbun\b", main):
            offenders.append(f"main: {main}")
        for name in s.all_deps:
            if name == "bun" or name.startswith("bun-"):
                offenders.append(f"runtime dependency: {name}")
        if offenders:
            return CheckResult(
                id="node-ts.bun-dev-only", tier="warning",
                title="Bun in the runtime path",
                detail="; ".join(offenders),
                fix_hint="Bun is dev tooling only (§S4): the production image "
                         "contains Node, not Bun. Move bun usage to dev/test scripts "
                         "and devDependencies; production starts with node.")
        return CheckResult(
            id="node-ts.bun-dev-only", tier="ok",
            title="Bun is confined to dev tooling",
            detail="No bun in start/main or runtime dependencies "
                   "(devDependencies and test scripts are fine).")

    # ── Fastify serving / shutdown / ws (§S4) ───────────────────────────────
    def _check_fastify_serving(self, s):
        text = s.service_text()
        missing = []
        if not re.search(r"\btrustProxy\s*:", text):
            missing.append("trustProxy (it lives behind Caddy — the Node analog of "
                           "Django's SECURE_PROXY_SSL_HEADER)")
        if not re.search(r"\bbodyLimit\s*:", text):
            missing.append("bodyLimit (request body size cap)")
        # nosec B104 — this *looks for* a 0.0.0.0 bind in the scanned project;
        # it does not bind anything itself.
        if "0.0.0.0" not in text or not re.search(r"process\.env\.PORT\b", text):  # nosec B104
            missing.append("a 0.0.0.0 + $PORT listen (containers need both)")
        if missing:
            return CheckResult(
                id="node-ts.fastify-serving", tier="warning",
                title="Fastify serving hardening incomplete",
                detail="Missing: " + "; ".join(missing),
                fix_hint="Construct Fastify with `trustProxy: true` and a `bodyLimit`, "
                         "and listen on `{ host: \"0.0.0.0\", port: "
                         "Number(process.env.PORT) }` so Caddy can reach and trust it.")
        return CheckResult(
            id="node-ts.fastify-serving", tier="ok",
            title="Fastify serving is container-shaped",
            detail="trustProxy set, bodyLimit set, listens on 0.0.0.0:$PORT.")

    def _check_graceful_shutdown(self, s):
        sigterm_files = [t for t in s.service_sources.values() if _SIGTERM_RE.search(t)]
        if not sigterm_files:
            return CheckResult(
                id="node-ts.graceful-shutdown", tier="warning",
                title="No SIGTERM handler found",
                detail="No `process.on(\"SIGTERM\", ...)` in the service sources.",
                fix_hint="Cutover sends SIGTERM; without a handler every live ws "
                         "client and in-flight request is severed mid-write. Handle "
                         "SIGTERM: close the ws server, drain in-flight HTTP "
                         "(fastify.close()), then exit — required for clean cutover.")
        has_ws = "ws" in s.all_deps
        if has_ws:
            closes_ws = any(re.search(r"\.close\(", t[_SIGTERM_RE.search(t).start():])
                            for t in sigterm_files)
            if not closes_ws:
                return CheckResult(
                    id="node-ts.graceful-shutdown", tier="warning",
                    title="SIGTERM handler does not close the ws server",
                    detail="A SIGTERM handler exists but no .close( call follows it.",
                    fix_hint="Close the WebSocketServer in the SIGTERM handler so "
                             "peers get a close frame instead of a dead socket.")
        return CheckResult(
            id="node-ts.graceful-shutdown", tier="ok",
            title="SIGTERM drain handler present",
            detail="SIGTERM handler found" +
                   (", closing the ws server and draining in-flight work."
                    if has_ws else "."))

    def _check_ws_heartbeat(self, s):
        if "ws" not in s.all_deps:
            return CheckResult(
                id="node-ts.ws-heartbeat", tier="ok",
                title="No ws server — heartbeat not applicable",
                detail="The service has no `ws` dependency.")
        text = s.service_text()
        has_ping = re.search(r"\.ping\(", text) is not None
        has_pong = re.search(r"['\"]pong['\"]", text) is not None
        if has_ping and has_pong:
            return CheckResult(
                id="node-ts.ws-heartbeat", tier="ok",
                title="Server-side ws heartbeat present",
                detail="ping/pong heartbeat found — half-open sockets get reaped. "
                       "Clients should auto-reconnect with snapshot-then-stream "
                       "(the §3.5 pattern) since blue-green cutover severs every "
                       "live socket.")
        return CheckResult(
            id="node-ts.ws-heartbeat", tier="warning",
            title="No ws heartbeat (ping/pong) found",
            detail="No server-side ping()/on(\"pong\") pair in the service sources.",
            fix_hint="Half-open sockets accumulate silently without a heartbeat: "
                     "ping every client on an interval and terminate peers that "
                     "missed the previous ping. Advise clients to auto-reconnect "
                     "with snapshot-then-stream on reconnect (§3.5).")

    def _check_readiness_pattern(self, s):
        """SCAN-S4-READINESS-PATTERN (review3 §N2): pattern detection only — the
        enforceable gate is pipeline work (PIPE-S4-READINESS-GATE, Phase 2)."""
        text = s.healthz_text()
        if not text:
            return CheckResult(
                id="node-ts.readiness-pattern", tier="warning",
                title="No /healthz endpoint found",
                detail="No healthz handler in the service sources. The §E9 fallback "
                       "applies — the pipeline probes an existing 200 route or falls "
                       "back to a TCP connect — but a warm-up-gated cutover is "
                       "impossible without one.",
                fix_hint="Add a /healthz returning the pinned JSON contract "
                         "{live, ready, checks: {feed_age_s, backfill_pct, ...}} "
                         "(§N2) with `ready` gated on warm-up completion.")
        match = _READY_RE.search(text)
        if not match:
            return CheckResult(
                id="node-ts.readiness-pattern", tier="warning",
                title="/healthz exists but exposes no `ready` field",
                detail="The healthz handler returns no ready field — liveness and "
                       "readiness are collapsed into one signal.",
                fix_hint="Split them (§N2): `live` = process up; `ready` = warm "
                         "engine, gated on backfill — otherwise cutover switches "
                         "traffic to a cold instance answering with empty levels.")
        expression = match.group(1).strip().rstrip(",")
        if expression in ("true", "!0", "1"):
            return CheckResult(
                id="node-ts.readiness-pattern", tier="warning",
                title="/healthz `ready` is unconditionally true",
                detail=f"ready: {expression} — no warm-up gating; a cold instance "
                       "reports ready before backfill completes.",
                fix_hint="Gate ready on the warm-up condition (e.g. "
                         "`ready: backfillDone && feed.connected`) so cutover waits "
                         "for a warm engine; the pipeline gate (PIPE-S4-READINESS-"
                         "GATE) enforces it at deploy time.")
        shape = [f for f in ("live", "checks") if re.search(rf"\b{f}\s*:", text)]
        return CheckResult(
            id="node-ts.readiness-pattern", tier="ok",
            title="Readiness gate pattern detected in /healthz",
            detail=f"ready gated on `{expression}`; contract fields present: "
                   f"ready, {', '.join(shape)} (§N2 pinned shape "
                   "{live, ready, checks: {...}}).")

    # ── ingestion daemon (§S4, armed by ccxt/streaming deps) ────────────────
    def _check_ingest_reconnect(self, s):
        if re.search(r"backoff", s.service_text(), re.IGNORECASE):
            return CheckResult(
                id="node-ts.ingest-reconnect", tier="ok",
                title="Ingestion reconnects with backoff",
                detail="A reconnect-with-backoff pattern is present in the "
                       "ingestion path.")
        return CheckResult(
            id="node-ts.ingest-reconnect", tier="warning",
            title="No reconnect-with-backoff in the ingestion path",
            detail="ccxt/streaming dependencies are present but no backoff/retry "
                   "pattern was found — an upstream disconnect kills the feed until "
                   "the process restarts.",
            fix_hint="Upstream streams are background loops, not request handlers — "
                     "a dead feed fails no HTTP check. Wrap the stream loop in "
                     "reconnect-with-backoff (exponential, capped, jittered, reset "
                     "on a healthy tick); the loop never gives up — upstream "
                     "silence is normal for closed markets.")

    def _check_ingest_staleness(self, s):
        text = s.service_text()
        tracked = re.search(r"last_?tick_?age|lastTickAge|feed_age", text, re.IGNORECASE)
        surfaced = re.search(r"feed_age|lastTickAge", s.healthz_text(), re.IGNORECASE)
        if tracked and surfaced:
            return CheckResult(
                id="node-ts.ingest-staleness", tier="ok",
                title="Last-tick age surfaced in /healthz",
                detail="Feed staleness is its own metric with its own Finding class "
                       "(§N2/§N3): P2 at most, market-calendar-aware, and NEVER a "
                       "reconciler restart trigger — feed silence is the normal "
                       "state most of the week.")
        return CheckResult(
            id="node-ts.ingest-staleness", tier="warning",
            title="Last-tick age is not surfaced in /healthz",
            detail="No feed-age metric feeds the healthz payload — a silently "
                   "frozen feed is invisible to monitoring.",
            fix_hint="Track the last tick timestamp in the ingestion loop and "
                     "report `checks.feed_age_s` (plus per-feed upstream-connected "
                     "vs process-wedged status) from /healthz, so the repair "
                     "policy can tell exchange downtime from a wedged process.")

    def _check_ingest_backfill(self, s):
        text = s.service_text()
        has_checkpoint = re.search(r"checkpoint", text, re.IGNORECASE) is not None
        has_bounded = re.search(r"concurrency", text, re.IGNORECASE) is not None
        if has_checkpoint and has_bounded:
            return CheckResult(
                id="node-ts.ingest-backfill", tier="ok",
                title="Backfill resumes from checkpoint with bounded concurrency",
                detail="Resume-from-checkpoint plus bounded request concurrency "
                       "found — restarts do not re-pull full history (§N4 "
                       "rate-limit guidance).")
        missing = ([] if has_checkpoint else ["resume-from-checkpoint"]) + \
                  ([] if has_bounded else ["bounded concurrency"])
        return CheckResult(
            id="node-ts.ingest-backfill", tier="advice",
            title="Backfill rate-limit guidance not fully detected",
            detail="Missing pattern(s): " + ", ".join(missing) + ".",
            fix_hint="A full re-backfill on every restart burns FinMind quota and "
                     "trips Alpaca rate limits (§N4). Persist a durable checkpoint "
                     "and resume from it, and cap in-flight history requests.")

    # ── exclusive upstream (§N4) ────────────────────────────────────────────
    def _check_exclusive_upstream(self, s):
        upstreams = s.exclusive_upstreams()
        if not upstreams:
            return CheckResult(
                id="node-ts.exclusive-upstream", tier="ok",
                title="No exclusive-upstream feeds detected",
                detail="No known single-socket upstream (e.g. Alpaca) or "
                       "EXCLUSIVE_UPSTREAM marker found; blue-green overlap is "
                       "safe on the ingestion side.")
        hook = s.handoff_hook()
        if hook:
            return CheckResult(
                id="node-ts.exclusive-upstream", tier="ok",
                title="Exclusive upstream with a documented handoff hook",
                detail=f"Exclusive upstream(s) {', '.join(upstreams)} detected, but "
                       f"a pre-stop ingestion-handoff script (`{hook}`) exists — "
                       "the old instance pauses ingestion before green warms (§N4).")
        return CheckResult(
            id="node-ts.exclusive-upstream", tier="warning",
            title="Exclusive upstream feeds require the recreate strategy",
            detail=f"Detected: {', '.join(upstreams)}. These permit one concurrent "
                   "websocket per account — during a blue-green overlap two "
                   "ingestion daemons fight over the socket (green never becomes "
                   "ready, or kicks blue's live feed mid-serving), and a double "
                   "backfill can exhaust quotas. deploy_strategy is set to "
                   "recreate in the manifest (§N4).",
            fix_hint="Keep the recreate strategy (the manifest already pins it), "
                     "or add a documented pre-stop ingestion-handoff hook (a "
                     "`prestop`/handoff script that pauses ingestion) if "
                     "blue-green is truly needed.")

    # ── local state (§N1/N5/N6) ─────────────────────────────────────────────
    def _check_local_state(self, s):
        if not s.data_files:
            return CheckResult(
                id="node-ts.local-state", tier="ok",
                title="No local on-disk state detected",
                detail="No *.parquet / *.duckdb / *.sqlite3 / WAL files found.")
        listing = ", ".join(str(p) for p in s.data_files[:10])
        sqlite = [p for p in s.data_files if p.suffix == ".sqlite3"
                  or p.name.endswith("-wal")]
        duckdb = [p for p in s.data_files if p.suffix == ".duckdb"]
        lines = [f"Data files: {listing}.",
                 "State on host disk means single-instance only (§9.5.6) — marked, "
                 "not blocked; correct for v1. deploy_strategy is set to recreate "
                 "and the data directory becomes a per-Site named volume (§N1/N5)."]
        if sqlite:
            lines.append("SQLite present: WAL does not make concurrent "
                         "cross-container writers safe — the old writer must stop "
                         "before the new one writes.")
        if duckdb:
            lines.append("DuckDB files are derived data, rebuildable from Parquet — "
                         "excluded from backup (§N6).")
        migrate = self._migrate_script(s)
        if migrate and sqlite:
            lines.append(f"A migrate-ish script (`{migrate}`) plus SQLite means "
                         "rollback-across-schema-change lands old code on a newer "
                         "schema — declare the pre-cutover migrate hook and treat "
                         "schema-changing deploys as one-way (§N6).")
        return CheckResult(
            id="node-ts.local-state", tier="warning",
            title="Local on-disk state — single-instance site",
            detail=" ".join(lines),
            fix_hint="Keep the data directory on the named volume the manifest "
                     "declares (never in image layers); backups ride the per-site "
                     "data-backup registry (sqlite_file + incremental "
                     "directory_sync, §N6).")

    @staticmethod
    def _migrate_script(s):
        for pkg in s.packages.values():
            scripts = pkg.get("scripts")
            if isinstance(scripts, dict):
                for key in scripts:
                    if "migrate" in key.lower():
                        return key
        return None

    # ── secrets (§S4 config & secrets, §M4) ─────────────────────────────────
    def _check_secrets_env(self, s):
        names = s.broker_env_names()
        if not names:
            return CheckResult(
                id="node-ts.secrets-env", tier="ok",
                title="No broker credential env names detected",
                detail="No broker/exchange key names in .env.example. Committed "
                       "key-like values are covered by core.secret-scan.")
        return CheckResult(
            id="node-ts.secrets-env", tier="advice",
            title="Broker credentials are env-driven — prefer read-only/paper keys",
            detail="Broker key env names found in .env.example: "
                   + ", ".join(names) + ". Env-driven is correct; committed "
                   "key-like values ride core.secret-scan (entropy scan §4.5). "
                   "Keyless Binance endpoints need no secret.",
            fix_hint="Broker keys are a money-moving credential class (§M4): use "
                     "read-only or paper-trading keys wherever the broker supports "
                     "scoping, store live keys in the vault, and never commit .env.")

    # ── Python offline component / jobs image (§N7) ─────────────────────────
    def _check_jobs_image(self, s):
        return CheckResult(
            id="node-ts.jobs-image", tier="advice",
            title="Backtesting is manual-only in v1",
            detail="The Python offline component (" + ", ".join(s.offline_deps) +
                   ") cannot run inside the Node-only production image. v1 ships "
                   "backtesting as manual-only (§N7); the manifest records a "
                   "jobs_image stub from pyproject.toml so the Phase-3 "
                   "run-image-X-with-volumes job type can pick it up.",
            fix_hint="Run backtests manually against the same Parquet data for now; "
                     "when the Phase-3 job type lands, the jobs_image container "
                     "shares the site's Parquet volume read-only.")

    # ── executing checks: EMITTED as sandbox specs, never run here (§M1) ────
    def sandbox_checks(self, root):
        return [
            SandboxSpec(
                id="node-ts.install",
                command=["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"],
                why="CI-honesty install check; lifecycle scripts are the §6.8 "
                    "supply-chain surface, so --ignore-scripts is explicit (§M1)."),
            SandboxSpec(
                id="node-ts.tsc",
                command=["pnpm", "exec", "tsc", "--noEmit"],
                why="Strict-mode type check; requires installed node_modules and "
                    "plugin execution, so sandbox-only."),
            SandboxSpec(
                id="node-ts.build",
                command=["pnpm", "run", "build"],
                why="Production build must succeed; builds execute project code, "
                    "so sandbox-only (§M1)."),
        ]

    # ── wizard (§S3 additions + §N4/§M4) ────────────────────────────────────
    def wizard_questions(self, root):
        s = _Survey(root)
        names = s.workspace_names() or ["."]
        service = s.service_name()
        dev_default = ", ".join(n for n in names if n != service) or None
        exclusive = s.exclusive_upstreams()
        return [
            WizardQuestion(
                id="node-ts.service-package",
                prompt="Which workspace package is the deployable service?",
                kind="choice", default=service, choices=names),
            WizardQuestion(
                id="node-ts.dev-packages",
                prompt="Which workspace packages are dev-only (never deployed)?",
                kind="text", default=dev_default),
            WizardQuestion(
                id="node-ts.data-dir",
                prompt="Where does the data directory live? (becomes a per-Site "
                       "named volume surviving container replacement)",
                kind="text", default=s.data_dir()),
            WizardQuestion(
                id="node-ts.worker-threads",
                prompt="Expected worker-thread count (feeds container CPU guidance)",
                kind="number", default=s.worker_threads_default()),
            WizardQuestion(
                id="node-ts.exposure",
                prompt="Who should reach this site? This service appears to handle "
                       "financial/broker data — mesh_only is recommended; public "
                       "requires authentication (§M4)."
                       if s.financial_signals() else "Who should reach this site?",
                kind="choice",
                default="mesh_only" if s.financial_signals() else "public",
                choices=["public", "mesh_only"]),
            WizardQuestion(
                id="node-ts.exclusive-upstream",
                prompt="Do any upstream feeds permit only one concurrent connection "
                       "per account (e.g. Alpaca standard plan)? Flagged sites "
                       "require the recreate strategy or a pre-stop handoff (§N4)."
                       + (f" Detected: {', '.join(exclusive)}." if exclusive else ""),
                kind="bool", default=bool(exclusive)),
        ]

    # ── manifest fragment (§V5: merged into the ONE manifest) ───────────────
    def manifest_fragment(self, root, answers=None):
        s = _Survey(root)
        main = s.service_pkg.get("main") or "dist/index.js"
        fragment = {
            "components": {
                "service": {
                    "kind": "node-ts",
                    "package": s.service_name(),
                    "command": ["node", str(main)],
                    "port": s.port(),
                },
            },
            "healthz": {
                "liveness_path": "/healthz" if s.healthz_text() else None,
                "readiness_path": "/healthz" if s.healthz_text() else None,
                # §N2: warm-up defaults high for this stack (10–15 min) — 600 s.
                "warmup_timeout_s": 600,
            },
        }
        if s.ingestion_armed():
            # §N2/§N3: per-feed staleness threshold, market-calendar-aware in the
            # pipeline; never a restart trigger.
            fragment["healthz"]["data_staleness_threshold"] = 900
        if s.data_files or s.exclusive_upstreams():
            fragment["deploy_strategy"] = "recreate"  # §N1: mandatory-if-flagged
        if s.data_files:
            data_dir = s.data_dir()
            sqlite = [str(p) for p in s.data_files if p.suffix == ".sqlite3"]
            duckdb = [str(p) for p in s.data_files if p.suffix == ".duckdb"]
            backup_units = [{"kind": "sqlite_file", "path": p} for p in sqlite]
            backup_units.append({"kind": "directory_sync", "path": data_dir,
                                 "incremental": True})
            fragment["volumes"] = [{
                "name": f"site-{Path(data_dir).name}-data",
                "path": data_dir,
                "backup_policy": {
                    "backup_units": backup_units,
                    "derived_excluded": duckdb,  # §N6: DuckDB rebuilds from Parquet
                },
            }]
        if s.offline_deps:
            fragment["jobs_image"] = {"from": "pyproject.toml", "status": "manual-v1"}
        if answers:
            if answers.get("node-ts.exposure"):
                fragment["exposure"] = answers["node-ts.exposure"]
            if answers.get("node-ts.service-package"):
                fragment["components"]["service"]["package"] = \
                    answers["node-ts.service-package"]
        return fragment


module = register(NodeTsScannerModule())

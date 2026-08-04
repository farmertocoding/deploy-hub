"""Fallback scanner modules (review3 §V4) + the common-core check suite.

`common_checks(root)` is the shared static check set every module should include
in its report; framework modules import and call it. The two modules defined
here — `dockerfile` and `static` — are the LOWEST-precedence fallbacks: core
consults them only when no framework module matched (§V4). An existing
Dockerfile is an input we validate (EXPOSE / non-root / :latest), never a
bypass of the deeper checks.

SEC-SCAN-NOEXEC (review3 §M1): everything in this file is `static` — file and
manifest reading only. Nothing from the scanned tree is ever executed on the
Hub, and the `dockerfile` module emits NO build spec: the image build is
pipeline step 1, governed by §B1, not a scan-time sandbox job.
"""
import math
import re
from pathlib import Path

from scanner import core

# Directories that are dependency/build/data output, never reviewed source.
_SKIP_DIRS = {"node_modules", ".venv", "venv", "dist", "build", "data",
              "__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
_MAX_TEXT_BYTES = 512 * 1024

# ── secret-scan patterns ────────────────────────────────────────────────────────
_AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
_ASSIGNMENT_RE = re.compile(
    r"(secret|token|password|api_key)\s*[=:]\s*['\"]([A-Za-z0-9+/_-]{16,})",
    re.IGNORECASE,
)
_PLACEHOLDER_MARKERS = ("changeme", "change-me", "change_me", "xxx", "example",
                        "dummy", "insecure", "placeholder", "sample", "your_", "your-")
_ENTROPY_FLOOR_BITS = 2.5  # bits/char; filters "aaaaaaaa…"-style non-secrets

_HEALTH_ROUTE_RE = re.compile(r"['\"/](healthz?|ping|health[-_]?check)\b", re.IGNORECASE)
_AUTH_INDICATOR_RE = re.compile(
    r"(session|login|jwt|authenticate|api_key|authorization)", re.IGNORECASE)

# ── Dockerfile line patterns ────────────────────────────────────────────────────
_FROM_RE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?",
                      re.IGNORECASE)
_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(\d+)", re.IGNORECASE)
_USER_RE = re.compile(r"^\s*USER\s+\S+", re.IGNORECASE)

_TEST_FILE_RE = re.compile(r"(^test_.*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$)")
_CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rb", ".go"}


# ── file walking (static reads only) ────────────────────────────────────────────

def _iter_files(root):
    """Yield tracked-looking files under root, skipping dependency/build/data
    dirs and hidden dirs. Dotfiles (e.g. `.env`) are yielded; dot-dirs are not."""
    stack = [Path(root)]
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
                yield path


def _read_text(path):
    """Return decoded text, or None for binary / oversized / unreadable files."""
    try:
        if path.stat().st_size > _MAX_TEXT_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except UnicodeDecodeError:
            return None


def _text_files(root):
    """[(path, text)] for every scannable text file under root."""
    out = []
    for path in _iter_files(root):
        text = _read_text(path)
        if text is not None:
            out.append((path, text))
    return out


def _shannon_entropy(value):
    if not value:
        return 0.0
    counts = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_placeholder(value):
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _is_env_file(name):
    if name in (".env.example", ".env.sample", ".env.template"):
        return False
    return name == ".env" or name.startswith(".env.")


# ── common core checks (id prefix `core.`) ──────────────────────────────────────

def _check_secret_scan(root, texts):
    findings = []
    for path, text in texts:
        rel = path.relative_to(root)
        if _is_env_file(path.name):
            findings.append(f"{rel}: committed .env file")
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _AWS_KEY_RE.search(line):
                findings.append(f"{rel}:{lineno}: AWS access key id (AKIA…)")
                continue
            match = _ASSIGNMENT_RE.search(line)
            if match:
                value = match.group(2)
                if (not _looks_placeholder(value)
                        and _shannon_entropy(value) >= _ENTROPY_FLOOR_BITS):
                    findings.append(
                        f"{rel}:{lineno}: hardcoded {match.group(1).lower()} value")
    if findings:
        return core.CheckResult(
            id="core.secret-scan", tier="blocker",
            title="Committed secrets detected",
            detail="\n".join(findings),
            fix_hint="Move secrets to the vault / environment injection, rotate any "
                     "value that was committed, and add .env to .gitignore. "
                     "Committed secrets stay in git history until rotated.",
        )
    return core.CheckResult(id="core.secret-scan", tier="ok",
                            title="No committed secrets found")


def _has_pinned_requirements(root):
    for req in Path(root).glob("requirements*.txt"):
        text = _read_text(req)
        if text and "==" in text:
            return True
    return False


def _check_lockfile(root):
    root = Path(root)
    missing = []
    if (root / "package.json").is_file():
        node_locks = ("package-lock.json", "package-lock.yaml",
                      "pnpm-lock.yaml", "yarn.lock")
        if not any((root / name).is_file() for name in node_locks):
            missing.append("package.json without package-lock.json / "
                           "pnpm-lock.yaml / yarn.lock")
    if (root / "pyproject.toml").is_file():
        py_locked = ((root / "uv.lock").is_file() or (root / "poetry.lock").is_file()
                     or _has_pinned_requirements(root))
        if not py_locked:
            missing.append("pyproject.toml without uv.lock / poetry.lock / "
                           "pinned (==) requirements file")
    if missing:
        return core.CheckResult(
            id="core.lockfile", tier="warning",
            title="Dependency manifest without a lockfile",
            detail="; ".join(missing),
            fix_hint="Commit a lockfile so deploys are reproducible — the same "
                     "source must build the same image every time.",
        )
    return core.CheckResult(id="core.lockfile", tier="ok",
                            title="Dependency manifests are locked")


def _check_gitignore(root, texts):
    root = Path(root)
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return core.CheckResult(
            id="core.gitignore", tier="warning",
            title="No .gitignore",
            detail="The project has no .gitignore at its root.",
            fix_hint="Add a .gitignore covering at least .env and (for node "
                     "projects) node_modules, so secrets and dependency trees "
                     "never enter the repo.",
        )
    lines = [ln.strip() for ln in (_read_text(gitignore) or "").splitlines()
             if ln.strip() and not ln.strip().startswith("#")]

    def covered(token):
        return any(token in ln for ln in lines)

    gaps = []
    env_matters = any(_is_env_file(p.name) for p, _ in texts) or (root / ".env").exists()
    if env_matters and not covered(".env"):
        gaps.append(".env files exist but .gitignore does not cover .env")
    node_matters = (root / "package.json").is_file() or (root / "node_modules").is_dir()
    if node_matters and not covered("node_modules"):
        gaps.append("node project but .gitignore does not cover node_modules")
    if gaps:
        return core.CheckResult(
            id="core.gitignore", tier="warning",
            title=".gitignore has gaps", detail="; ".join(gaps),
            fix_hint="Add the missing patterns to .gitignore.",
        )
    return core.CheckResult(id="core.gitignore", tier="ok",
                            title=".gitignore covers the basics")


def _check_tests_exist(root):
    root = Path(root)
    for path in _iter_files(root):
        if _TEST_FILE_RE.search(path.name):
            return core.CheckResult(id="core.tests-exist", tier="ok",
                                    title="Test files found")
        rel_dirs = path.relative_to(root).parts[:-1]
        if (("tests" in rel_dirs or "test" in rel_dirs)
                and path.suffix in _CODE_SUFFIXES):
            return core.CheckResult(id="core.tests-exist", tier="ok",
                                    title="Test files found")
    return core.CheckResult(
        id="core.tests-exist", tier="advice",
        title="No test files found",
        detail="No test_*.py / *_test.py / *.test.* / *.spec.* files or tests/ "
               "directory were found.",
        fix_hint="Even a small smoke-test suite lets the pipeline verify a build "
                 "before it ships.",
    )


def _check_healthz(texts):
    """§E9 fallback semantics: a missing health endpoint is ADVICE at core level —
    the pipeline will probe an existing 200 route or fall back to a TCP connect.
    Framework modules may upgrade this with §N2 readiness semantics."""
    for _, text in texts:
        if _HEALTH_ROUTE_RE.search(text):
            return core.CheckResult(id="core.healthz", tier="ok",
                                    title="Health endpoint detected")
    return core.CheckResult(
        id="core.healthz", tier="advice",
        title="No health endpoint detected",
        detail="No route containing health/healthz/ping was found. The deploy "
               "pipeline will fall back to probing an existing 200 route or a "
               "TCP connect (§E9) — deploys still work, with a weaker readiness "
               "signal.",
        fix_hint="Add a cheap /healthz route returning 200 for first-class "
                 "readiness and warmup gating (§N2).",
    )


def _check_digest_pins(root, texts):
    findings = []
    for path, text in texts:
        if not path.name.startswith("Dockerfile"):
            continue
        rel = path.relative_to(root)
        aliases = set()
        for lineno, line in enumerate(text.splitlines(), 1):
            match = _FROM_RE.match(line)
            if not match:
                continue
            image, alias = match.group(1), match.group(2)
            if alias:
                aliases.add(alias.lower())
            if image.lower() in aliases or image.lower() == "scratch":
                continue
            if "@sha256:" not in image:
                findings.append(f"{rel}:{lineno}: FROM {image} is not digest-pinned")
    if findings:
        return core.CheckResult(
            id="core.digest-pins", tier="warning",
            title="Base images not pinned by digest (§6.8)",
            detail="\n".join(findings),
            fix_hint="Pin each FROM to an @sha256: digest so builds cannot "
                     "silently change under a moving tag.",
        )
    return core.CheckResult(id="core.digest-pins", tier="ok",
                            title="All base images digest-pinned")


def _check_exposure_auth(texts):
    """SCAN-M4-EXPOSURE-AUTH heuristic. Core emits a warning only — the wizard's
    exposure question decides whether this escalates for a public site."""
    for path, text in texts:
        if _is_env_file(path.name):
            continue
        if _AUTH_INDICATOR_RE.search(text):
            return core.CheckResult(id="core.exposure-auth", tier="ok",
                                    title="Authentication indicators found")
    return core.CheckResult(
        id="core.exposure-auth", tier="warning",
        title="No authentication detected",
        detail="no authentication detected — Blocker if this site will be public "
               "with financial/personal data (wizard will ask)",
        fix_hint="If the site is meant to be public and handles financial or "
                 "personal data, add authentication before deploying, or set "
                 "exposure to mesh_only in the wizard.",
    )


def common_checks(root):
    """The common-core static check suite (id prefix `core.`), run by both
    fallback modules and exported for framework modules to include."""
    root = Path(root)
    texts = _text_files(root)
    return [
        _check_secret_scan(root, texts),
        _check_lockfile(root),
        _check_gitignore(root, texts),
        _check_tests_exist(root),
        _check_healthz(texts),
        _check_digest_pins(root, texts),
        _check_exposure_auth(texts),
    ]


# ── fallback module: dockerfile (§V4) ───────────────────────────────────────────

def _parse_root_dockerfile(root):
    """(has_expose, first_port, has_user, latest_findings) for root Dockerfile."""
    text = _read_text(Path(root) / "Dockerfile") or ""
    port, has_expose, has_user, latest = None, False, False, []
    aliases = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        expose = _EXPOSE_RE.match(line)
        if expose:
            has_expose = True
            if port is None:
                port = int(expose.group(1))
            continue
        if _USER_RE.match(line):
            has_user = True
            continue
        match = _FROM_RE.match(line)
        if match:
            image, alias = match.group(1), match.group(2)
            if alias:
                aliases.add(alias.lower())
            if image.lower() not in aliases and image.endswith(":latest"):
                latest.append(f"Dockerfile:{lineno}: FROM {image}")
    return has_expose, port, has_user, latest


class DockerfileModule:
    """Validates an existing Dockerfile as INPUT (§V4) — never a bypass."""

    name = "dockerfile"

    def detect(self, root):
        return (Path(root) / "Dockerfile").is_file()

    def checks(self, root):
        results = common_checks(root)
        has_expose, _, has_user, latest = _parse_root_dockerfile(root)
        if has_expose:
            results.append(core.CheckResult(id="dockerfile.expose", tier="ok",
                                            title="Dockerfile declares EXPOSE"))
        else:
            results.append(core.CheckResult(
                id="dockerfile.expose", tier="warning",
                title="Dockerfile has no EXPOSE",
                detail="Without EXPOSE the service port cannot be inferred; the "
                       "wizard will ask for it.",
                fix_hint="Add `EXPOSE <port>` matching the port the app listens on.",
            ))
        if has_user:
            results.append(core.CheckResult(id="dockerfile.non-root", tier="ok",
                                            title="Dockerfile sets USER"))
        else:
            results.append(core.CheckResult(
                id="dockerfile.non-root", tier="warning",
                title="Container runs as root (no USER directive)",
                detail="No USER directive found — the container process runs as "
                       "root inside the container.",
                fix_hint="Create an unprivileged user in the image and add a USER "
                         "directive before CMD/ENTRYPOINT.",
            ))
        if latest:
            results.append(core.CheckResult(
                id="dockerfile.latest-tag", tier="warning",
                title="Base image uses the :latest tag",
                detail="\n".join(latest),
                fix_hint="Use an explicit version tag (and a digest pin, §6.8) so "
                         "rebuilds are reproducible.",
            ))
        else:
            results.append(core.CheckResult(id="dockerfile.latest-tag", tier="ok",
                                            title="No :latest base tags"))
        return results

    def sandbox_checks(self, root):
        # Deliberately none: the image build is pipeline step 1 (§B1), deleted
        # from the scan phase by review3 §M1 — no build spec is emitted here.
        return []

    def wizard_questions(self, root):
        _, port, _, _ = _parse_root_dockerfile(root)
        questions = [
            core.WizardQuestion(id="dockerfile.domain",
                                prompt="Domain to serve this site on"),
            core.WizardQuestion(id="dockerfile.exposure",
                                prompt="Who should reach this site?",
                                kind="choice", default="public",
                                choices=["public", "mesh_only"]),
        ]
        if port is None:
            questions.append(core.WizardQuestion(
                id="dockerfile.port", kind="number",
                prompt="Which port does the container listen on? "
                       "(no EXPOSE found in the Dockerfile)"))
        questions.append(core.WizardQuestion(
            id="dockerfile.env", kind="secret",
            prompt="Environment variables/secrets the container needs "
                   "(stored in the vault, injected at deploy)"))
        return questions

    def manifest_fragment(self, root, answers=None):
        _, port, _, _ = _parse_root_dockerfile(root)
        if port is None and answers:
            port = answers.get("dockerfile.port")
        return {"components": {"service": {"kind": "dockerfile", "port": port}}}


# ── fallback module: static (§V4) ───────────────────────────────────────────────

_SERVER_MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt",
                     "manage.py", "Dockerfile", "go.mod", "Gemfile", "composer.json")


class StaticModule:
    """Plain static site: an index.html and no server-side manifest."""

    name = "static"

    @staticmethod
    def _site_dir(root):
        for candidate in (".", "dist", "build"):
            if (Path(root) / candidate / "index.html").is_file():
                return candidate
        return None

    def detect(self, root):
        root = Path(root)
        if any((root / manifest).is_file() for manifest in _SERVER_MANIFESTS):
            return False
        return self._site_dir(root) is not None

    def checks(self, root):
        return common_checks(root)

    def sandbox_checks(self, root):
        return []

    def wizard_questions(self, root):
        return [
            core.WizardQuestion(id="static.domain",
                                prompt="Domain to serve this site on"),
            core.WizardQuestion(id="static.exposure",
                                prompt="Who should reach this site?",
                                kind="choice", default="public",
                                choices=["public", "mesh_only"]),
        ]

    def manifest_fragment(self, root, answers=None):
        return {"components": {"static_route": {"dir": self._site_dir(root) or "."}}}


dockerfile_module = core.register(DockerfileModule(), fallback=True)
static_module = core.register(StaticModule(), fallback=True)

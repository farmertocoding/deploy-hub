"""Fallback scanner modules (review3 §V4) + the common-core check suite.

`common_checks(root)` is the shared static check set. No module calls it: since
D-010 `scanner.core.scan` composes it into EVERY report itself, once per scan over
the scan root, so a module cannot forget it (the django module did, and every
Django report lacked all seven `core.*` checks). A module may SUPERSEDE a core
result by emitting the same id — node-ts re-deriving `core.lockfile` is the
precedent, and it is the only way to express "this check does not apply here";
absence is impossible. The two modules defined here — `dockerfile` and `static` —
are the LOWEST-precedence fallbacks: core consults them only when no framework
module matched (§V4). An existing Dockerfile is an input we validate (EXPOSE /
non-root / :latest), never a bypass of the deeper checks.

SEC-SCAN-NOEXEC (review3 §M1): everything in this file is `static` — file and
manifest reading only. Nothing from the scanned tree is ever executed on the
Hub, and the `dockerfile` module emits NO build spec: the image build is
pipeline step 1, governed by §B1, not a scan-time sandbox job.
"""
import base64
import math
import re
from pathlib import Path

from scanner import core

# Directories that are dependency/build/data output, never reviewed source.
#
# Dot-directories used to be skipped WHOLESALE, which meant a committed key in
# `.github/workflows/deploy.yml` — a classic place for one — scanned clean (D-010
# follow-up item 4). They are enumerated here instead. A skip-list rather than an
# allow-list, deliberately: an allow-list means the next dot-directory anyone invents
# is silently unscanned, and the direction to fail in is "scanned something dull",
# not "missed a key".
_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "dist", "build", "data",
    "__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    # generated / cache dot-dirs: large, machine-written, and never reviewed source
    ".tox", ".nox", ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
    ".cache", ".gradle", ".idea", ".terraform", ".serverless", ".yarn", ".pnpm-store",
}
# ── N6: machine-written output trees (2026-08-11, follow-up 1 of the R4-10 record) ──
#
# These are NOT in `_SKIP_DIRS`, and the difference is the whole finding. `_SKIP_DIRS`
# prunes the walk: the tree is never opened, so nothing in it is checked by anything.
# The first cut of N6 added these names there, and an adversarial pass found it had
# done what round-6b's noise reduction did — opened holes while closing noise:
#
#   * a committed `.vercel/.env.production.local` (the file `vercel env pull` writes,
#     gitignored everywhere precisely BECAUSE it holds live credentials) stopped being
#     reported at all — `_is_env_file` never saw it;
#   * `core.gitignore` went quiet on the same repo, because it reads the same walk, so
#     one prune silently cost two checks;
#   * every bundler on this list INLINES `process.env.*` at build time, so a key can
#     exist in the artifact and in an ignored `.env` and NOWHERE in source — the
#     docstring's claim that generated output "only ever echoes scanned source" is
#     simply false for `.output/`, `storybook-static/` and friends.
#
# So the suppression is scoped to the axis that produced the measured noise. The
# heuristic axis (a secret-shaped NAME holding a high-entropy literal) does not run
# over these trees; the `[proof]` axis (published credential formats) and the `.env`
# handler still do. That kills the entire D-011r case — the measured finding,
# `frontend/coverage/lcov-report/src/auth.ts.html`, was `[heuristic]` — at zero cost
# in misses. This mirrors what `_GENERATED_FILE_RE` already does for `.min.js`/`.map`,
# and `_check_secret_scan` had the correct reasoning written next to it all along.
#
# `.vercel` and `.netlify` appear on neither list: they are CLI STATE directories a
# tool writes secrets into, not build output, and nothing about them is noise.
_GENERATED_DIRS = {
    "htmlcov", "lcov-report", ".nyc_output", "storybook-static",
    ".output", ".angular", ".astro", ".docusaurus", ".eggs",
}

# A directory whose name is an ordinary English word cannot be classified on the name.
# That is exactly the round-6b mistake: the test-material downgrade reached `spec`,
# `fixtures`, `e2e` and `cypress`, all of which name production directories, and a real
# key at `api/spec/config.py` stopped gating a deploy. An insurance or benefits product
# has an `apps/coverage/` holding source. So `coverage` needs EVIDENCE a generator
# wrote it: a marker that is a real, non-empty, non-symlink file sitting directly
# inside. `lcov-report` is deliberately NOT a marker — it is a generated dir in its own
# right, and accepting it here would prune the PARENT, taking sibling source with it.
_GENERATED_IF_MARKED = {
    "coverage": {
        "lcov.info", "coverage-final.json", "clover.xml",
        "cobertura-coverage.xml", "coverage-summary.json", ".resultset.json",
    },
}


def _dir_is_generated(path):
    """True when `path` is a machine-written output directory (N6).

    Name comparisons are lowercased on BOTH sides, and the marker lookup reads the
    directory listing rather than calling `exists()`. Both are deliberate: `exists()`
    delegates to the filesystem, which is case-insensitive on macOS and case-sensitive
    on the Linux CI runner, so a `coverage/LCOV.INFO` would have classified differently
    on the developer's machine than on CI — a gate result that depends on the OS is not
    a gate result. The marker must also be a real non-empty file: `mkdir lcov.info` and
    `ln -s /etc/hostname lcov.info` both satisfied `exists()`.
    """
    name = path.name.lower()
    if name in _GENERATED_DIRS:
        return True
    markers = _GENERATED_IF_MARKED.get(name)
    if not markers:
        return False
    try:
        for entry in path.iterdir():
            if entry.name.lower() not in markers:
                continue
            if entry.is_symlink() or not entry.is_file():
                continue
            if entry.stat().st_size > 0:
                return True
    except OSError:
        return False
    return False


def _in_generated_dir(path, root):
    """True when any directory between `root` and `path` is machine-written output.

    The scan root itself is never classified — a repo that happens to be checked out
    into a directory called `coverage` is still the project under review.
    """
    root, current = Path(root), Path(path).parent
    while current != root:
        if _dir_is_generated(current):
            return True
        if current.parent == current:      # filesystem root; never met the scan root
            return False
        current = current.parent
    return False


_MAX_TEXT_BYTES = 512 * 1024

# ── secret-scan patterns ────────────────────────────────────────────────────────
#
# TWO INDEPENDENT AXES, and the review that followed the first cut of this file is the
# reason both exist. Detection used to be entirely NAME-driven — a keyword in the
# identifier — with `AKIA…` the single exception. So a committed `id_rsa`, a
# `ghp_…` GitHub token or a `sk_live_…` Stripe key scanned clean unless the variable
# they were assigned to happened to be called something helpful, which a credential
# pasted into a config file rarely is.
#
#   axis 1 (VALUE): formats that are self-evidently credentials, whatever they are
#                   called or whether they are quoted at all.
#   axis 2 (NAME):  a secret-ish identifier assigned a high-entropy literal.
_AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")

# Axis 1. Each is a published, prefixed credential format — a match is a credential,
# not a heuristic, so these fire regardless of quoting, naming or entropy.
_CREDENTIAL_FORMATS = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(
        r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}")),
    ("GitLab personal access token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Slack webhook URL", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("PyPI token", re.compile(r"\bpypi-[A-Za-z0-9_-]{16,}")),
    ("SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")),
    # Reviewed: the body may not contain `-`. `sk-[A-Za-z0-9_-]{32,}` matched every
    # kebab-case CSS class of that length, and SpinKit's `.sk-chase-dot-…` ships in
    # `public/vendor/` on a great many sites — two blockers on a constructed Next.js
    # tree, both from one stylesheet, no credentials. Project keys keep the wider
    # alphabet but must carry the `sk-proj-` prefix and be 64+ characters, which no
    # class name is.
    ("OpenAI key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("OpenAI project key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{64,}")),
    # Twilio's `AC[0-9a-f]{32}` was dropped on review: it is the Account SID, a public
    # identifier, not the Auth Token — and it collides with any content-addressed hex.
    # Flagging a non-secret costs the check's credibility twice over.
)

# Axis 1, two entries that need a look at the match rather than just its shape.
_CONNECTION_STRING_RE = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis(?:s)?|amqps?|ftp|"
    r"ssh|https?)://(?P<user>[^/\s:@'\"]*):(?P<password>[^/\s@'\"]+)@", re.IGNORECASE)
_DOCKER_AUTH_RE = re.compile(r'"auth"\s*:\s*"(?P<b64>[A-Za-z0-9+/]{16,}={0,2})"')

# The keyword may sit ANYWHERE in the identifier, and that is the whole point of the
# widening (D-010 follow-up item 3). The previous pattern required the keyword to be
# followed immediately by `=` or `:`, so the two commonest shapes in the fleet never
# matched: in `AWS_SECRET_ACCESS_KEY` the keyword is followed by `_ACCESS_KEY`, and in
# `SECRET_KEY` by `_KEY`. Inside a Django settings file `django.secret-key-literal`
# covered them; in any other file nothing did.
#
# Both markers below are the round-5 F10 shape — a rule that has to name the pattern
# trips the source scans looking for it, and the remedy is a marked line, not degraded
# product copy.
_SECRET_WORD = (r"(?:secret|token|passwd|password|api[_-]?key|apikey|"  # nosec B105
                r"access[_-]?key|private[_-]?key|client[_-]?secret|credential)")
#
# The VALUE is "anything quoted that contains no whitespace", not a fixed alphabet.
# A base64/hex alphabet looked safe and was wrong in the direction that matters:
# Django's `startproject` draws its SECRET_KEY from
# `abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)`, so a real generated key
# contains punctuation and a narrow alphabet simply failed to match it. Requiring the
# CLOSING quote is what keeps this from running away — it bounds the match to one
# literal instead of to the rest of the line.
_ASSIGNMENT_RE = re.compile(
    rf"(?P<name>[A-Za-z0-9_]*{_SECRET_WORD}[A-Za-z0-9_]*)\s*[=:]\s*"
    rf"(?P<quote>['\"])(?P<value>[^\s'\"]{{16,}})(?P=quote)",
    re.IGNORECASE,
)

# The same thing UNQUOTED, which is how it appears everywhere the item-4 fix just made
# reachable: `run: AWS_SECRET_ACCESS_KEY=…` in a workflow, `API_KEY: …` in YAML,
# `export TOKEN=…` in a shell script, `password: …` in a k8s manifest. The first cut
# required both quotes, so the motivating case of item 4 — a key in
# `.github/workflows/deploy.yml` — was still missed unless it happened to be
# AKIA-shaped. Unquoted values carry no delimiter, so this arm is deliberately stricter:
# a narrower alphabet (no shell metacharacters, no `$`, so an interpolation cannot
# match) and a higher entropy floor.
_UNQUOTED_ASSIGNMENT_RE = re.compile(
    rf"(?P<name>[A-Za-z0-9_]*{_SECRET_WORD}[A-Za-z0-9_]*)\s*[=:]\s*"
    rf"(?P<value>[A-Za-z0-9+/_=.~-]{{20,}})(?=[\s,;)\"']|$)",
    re.IGNORECASE,
)
_UNQUOTED_ENTROPY_FLOOR_BITS = 3.5

# Values that are addresses rather than credentials: `token_url`, `secret_path` and
# `credentials_file` are ordinary names holding ordinary values.
#
# Reviewed and narrowed — the first cut skipped anything matching `^\w+://`, which was a
# one-character bypass (`API_KEY = "x://<40-char key>"` scanned clean) AND dropped the
# one URL shape that IS a credential: `postgres://user:REALPASSWORD@host`. So the
# scheme must be a real one, and a URL carrying userinfo with a password is never
# skipped — it is the finding.
_URL_RE = re.compile(
    r"^(?:https?|ftps?|s3|git|ssh|file|postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?"
    r"|redis(?:s)?|amqps?|kafka|jdbc):/{2,3}(?P<userinfo>[^/@\s]*@)?", re.IGNORECASE)
_PATH_RE = re.compile(r"^(?:\.{0,2}/|~/|[A-Za-z]:\\)")


def _is_address_not_credential(value):
    """True for a URL or path that carries no credential of its own."""
    if _PATH_RE.match(value):
        return True
    match = _URL_RE.match(value)
    if not match:
        return False
    userinfo = match.group("userinfo") or ""
    # `user:password@` is a credential wearing a URL. `user@` alone is not.
    return ":" not in userinfo.rstrip("@")


# Directory names whose contents are test material. A password in a test helper is a
# fixture, and blocking a deployment on it teaches people to route around the check —
# but it is not nothing either, so it is reported at a lower tier rather than dropped.
#
# Reviewed and narrowed. The first cut also listed `spec`, `specs`, `e2e`, `fixtures`
# and `cypress`, which routinely name PRODUCTION directories — an OpenAPI `spec/`, a
# Django `fixtures/`, a service called `e2e`. A real key at `api/spec/config.py` was
# downgraded from blocker to warning by nothing more than a directory name, which is a
# security hole dressed as noise reduction. What is left is unambiguous, and a file
# whose own NAME is test-shaped counts wherever it lives.
_TEST_DIR_NAMES = {"tests", "test", "__tests__", "testdata", "__snapshots__"}
_TEST_FILE_NAME_RE = re.compile(
    r"(^test_|_test\.|\.(test|spec)\.|^conftest\.|^factories\.|\.snap$)")


def _is_test_path(rel):
    parts = [p.lower() for p in rel.parts]
    return (bool(_TEST_FILE_RE.search(rel.name))
            or bool(_TEST_FILE_NAME_RE.search(rel.name.lower()))
            or any(part in _TEST_DIR_NAMES for part in parts[:-1]))


# Machine-written files whose contents are not reviewed source: a minified bundle is
# full of high-entropy identifiers and none of them is a committed credential.
_GENERATED_FILE_RE = re.compile(r"\.min\.(?:js|css|mjs)$|\.map$|\.lock$|\.woff2?$")

_PLACEHOLDER_MARKERS = ("changeme", "change-me", "change_me", "xxx", "example",
                        "dummy", "insecure", "placeholder", "sample", "your_", "your-",
                        # Same class as `sample`/`dummy`/`example`, added after scanning
                        # this repo with the widened rule: `PASSWORD = "a-long-demo-
                        # password"` in a dev script is a stand-in, not a credential.
                        # `test` is deliberately absent — it is a substring of `latest`.
                        "demo", "fake", "redacted", "notreal")
_ENTROPY_FLOOR_BITS = 2.5  # bits/char; filters "aaaaaaaa…"-style non-secrets
# Above this length AND entropy, a placeholder marker no longer excuses the value —
# see `_looks_placeholder` (D-010 follow-up item 5).
_REAL_KEY_MIN_LEN = 40
_REAL_KEY_MIN_ENTROPY = 4.0

_HEALTH_ROUTE_RE = re.compile(r"['\"/](healthz?|ping|health[-_]?check)\b", re.IGNORECASE)

# Auth INDICATORS, not auth-adjacent vocabulary (D-010 follow-up item 7). The previous
# pattern matched the bare substring `session`, so `SESSION_COOKIE_SECURE = True` alone
# satisfied it — meaning every project that passed `django.security-settings`
# auto-passed this check regardless of whether it had any authentication at all. What
# is wanted is evidence of an authentication *decision*: a guard, a check, a middleware,
# a token verification. Still a heuristic — the wizard's exposure question is what
# decides whether a miss matters — but a heuristic that can fail.
_AUTH_INDICATOR_RE = re.compile(
    r"(?:@?login_required|is_authenticated|request\.user\b|current_user\b"
    r"|\blogin\b|\blogout\b|\bsignin\b|\bsign_in\b|\bLOGIN_URL\b"
    r"|permission_classes|IsAuthenticated|AllowAny|authenticate\s*\("
    r"|LoginRequiredMixin|PermissionRequiredMixin|AuthenticationMiddleware"
    r"|passport\.(?:authenticate|use)|require[_-]?auth|ensureAuthenticated"
    r"|jwt\.(?:sign|verify|decode)|verify[_-]?jwt|jsonwebtoken"
    r"|next[-_]?auth|getServerSession|useSession"
    r"|req\.session\b|request\.session\b|session\[|flask_login|Depends\s*\(\s*get_current"
    r"|Authorization\s*:\s*Bearer|WWW-Authenticate|OAuth2?|OpenID)",
    re.IGNORECASE,
)
# Only source and templates can carry an auth decision. A hit in a lockfile, a
# .gitignore or a committed .env is vocabulary, not evidence.
_AUTH_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rb", ".go",
                  ".html", ".htm", ".vue", ".svelte", ".php", ".java", ".kt", ".cs"}

# ── Dockerfile line patterns ────────────────────────────────────────────────────
_FROM_RE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?",
                      re.IGNORECASE)
_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(\d+)", re.IGNORECASE)
_USER_RE = re.compile(r"^\s*USER\s+\S+", re.IGNORECASE)

_TEST_FILE_RE = re.compile(r"(^test_.*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$)")
_CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rb", ".go"}


# ── file walking (static reads only) ────────────────────────────────────────────

def _iter_files(root):
    """Yield tracked-looking files under root, skipping dependency/build/cache dirs.

    Dotfiles (`.env`) and dot-directories (`.github/`) are both yielded — only the
    names in `_SKIP_DIRS` are pruned. Symlinked directories are not followed: a link
    out of the tree is not the project's source, and a link back into it is a loop.
    """
    stack = [Path(root)]
    seen = set()
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            # Symlinked DIRECTORIES are not followed — a link out of the tree is not the
            # project's source and a link back into it is a loop. Symlinked FILES are
            # still read: master yielded them, and a committed symlinked `.env` or
            # config file is exactly the thing this suite is looking for.
            if path.is_symlink() and path.is_dir():
                continue
            if path.is_dir():
                if path.name in _SKIP_DIRS:
                    continue
                try:
                    key = path.resolve()
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
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
    """True when a marker word excuses this value as documentation, not a key.

    D-010 follow-up item 5: a marker used to excuse the value outright, which hides the
    single most common real finding there is. `django-insecure-<50 random chars>` is
    what Django's own `startproject` writes into `settings.py`, it contains the marker
    `insecure`, and on a great many sites it is the production key. So a marker excuses
    a *low-signal* value — `changeme`, `your_api_key_here` — and stops excusing anything
    long and random enough to be a real credential.
    """
    lowered = value.lower()
    if not any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return False
    return not (len(value) >= _REAL_KEY_MIN_LEN
                and _shannon_entropy(value) >= _REAL_KEY_MIN_ENTROPY)


def _is_env_file(name):
    if name in (".env.example", ".env.sample", ".env.template"):
        return False
    return name == ".env" or name.startswith(".env.")


# ── common core checks (id prefix `core.`) ──────────────────────────────────────

def _credential_format_in(line):
    """The label of the published credential format on this line, or None.

    Axis 1. The two shapes that need more than a pattern are handled here: a connection
    string is only a finding if its userinfo carries a real-looking password, and a
    docker `"auth"` blob only if it base64-decodes to `user:password`.
    """
    for label, pattern in _CREDENTIAL_FORMATS:
        if pattern.search(line):
            return label
    # Reviewed as a miss: `DATABASE_URL = "postgres://user:pass@host"` is the single
    # commonest committed database credential, and the name carries no keyword, so the
    # name-driven axis never saw it. As a value format it fires regardless of the name.
    match = _CONNECTION_STRING_RE.search(line)
    if match:
        password = match.group("password")
        if len(password) >= 6 and not _looks_placeholder(password):
            return "connection string with an embedded password"
    match = _DOCKER_AUTH_RE.search(line)
    if match:
        try:
            decoded = base64.b64decode(match.group("b64"), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            decoded = ""
        # A docker registry auth is base64 of `username:password`. Decoding is what
        # separates it from any other base64 blob under a key called `auth`.
        if ":" in decoded and len(decoded.split(":", 1)[1]) >= 6:
            return "docker registry auth (base64 user:password)"
    return None


def _is_identifier_echo(name, value):
    """`CLOUD_CREDENTIAL = "cloud_credential"` — the value IS the name.

    Enum labels, choice values, header names and field names all take this shape, and
    the widened keyword match walks straight into them: `cloud_credential` is 16
    characters and clears the entropy floor comfortably. Compared exactly rather than
    by "looks like an identifier", because a 40-character lowercase hex token also
    looks like an identifier and is a real key.
    """
    return name.lower().strip("_") == value.lower().replace("-", "_").strip("_")


def _check_secret_scan(root, texts):
    findings, test_findings = [], []
    for path, text in texts:
        rel = path.relative_to(root)
        bucket = test_findings if _is_test_path(rel) else findings
        if _is_env_file(path.name):
            bucket.append(f"{rel}: committed .env file")
            continue
        # N6: a machine-written FILE (`.min.js`, `.map`, a lockfile) and a file inside
        # a machine-written DIRECTORY are the same case — the heuristic axis below is
        # suppressed for both, and axis 1 plus the `.env` handler above still run.
        generated = (bool(_GENERATED_FILE_RE.search(path.name.lower()))
                     or _in_generated_dir(path, root))
        for lineno, line in enumerate(text.splitlines(), 1):
            # Axis 1 — a published credential format. Runs even in generated files: a
            # bundler can inline a key, and `AKIA…` in a minified bundle is still a key.
            fmt = _credential_format_in(line)
            if fmt:
                bucket.append(f"{rel}:{lineno}: [proof] {fmt}")
                continue
            # Axis 2 — a secret-ish name assigned a high-entropy literal. This one is a
            # heuristic, so it does not run over machine-written files.
            if generated:
                continue
            match = _ASSIGNMENT_RE.search(line)
            floor = _ENTROPY_FLOOR_BITS
            if not match:
                match = _UNQUOTED_ASSIGNMENT_RE.search(line)
                floor = _UNQUOTED_ENTROPY_FLOOR_BITS
            if match:
                name, value = match.group("name"), match.group("value")
                if (not _is_address_not_credential(value)
                        and not _is_identifier_echo(name, value)
                        and not _looks_placeholder(value)
                        and _shannon_entropy(value) >= floor):
                    bucket.append(
                        f"{rel}:{lineno}: [heuristic] hardcoded {name.lower()} value")
    if findings:
        detail = "\n".join(findings)
        if test_findings:
            detail += ("\n\nAlso in test material (not blocking):\n"
                       + "\n".join(test_findings))
        return core.CheckResult(
            id="core.secret-scan", tier="blocker",
            title="Committed secrets detected",
            detail=detail,
            fix_hint="Move secrets to the vault / environment injection, rotate any "
                     "value that was committed, and add .env to .gitignore. "
                     "Committed secrets stay in git history until rotated.\n\n"
                     "[proof] lines matched a published credential format — a GitHub "
                     "token, a PEM block, an AWS key id — and are not guesses. "
                     "[heuristic] lines are a secret-shaped name assigned a "
                     "high-entropy literal: real most of the time, and worth a look "
                     "before you decide.",
        )
    if test_findings:
        # Reported, not blocked. A fixture password is not a deployable credential, and
        # a blocker that fires on every test suite is a blocker people learn to route
        # around — but a real key does get committed to a test file sometimes, so the
        # finding still has to appear in the report with its file and line.
        return core.CheckResult(
            id="core.secret-scan", tier="warning",
            title="Secret-shaped values in test material only",
            detail="\n".join(test_findings),
            fix_hint="These are in test files, so they do not block a deploy. Confirm "
                     "each one is a fixture rather than a real credential that was "
                     "pasted into a test — if any is real, rotate it: it is in git "
                     "history either way.",
        )
    return core.CheckResult(id="core.secret-scan", tier="ok",
                            title="No committed secrets found")


def _has_pinned_requirements(directory):
    for req in Path(directory).glob("requirements*.txt"):
        text = _read_text(req)
        if text and "==" in text:
            return True
    return False


# How deep to look for a nested manifest. D-010 follow-up item 6: this check read only
# the scan ROOT, but every repo in the fleet nests — `backend/pyproject.toml`,
# `frontend/package.json`, `packages/*/package.json` — so on a real adopt-path scan it
# was vacuously `ok` and the frontend lockfile was covered by nothing at all. Three
# levels reaches `apps/web/frontend/package.json` and `services/api/internal/`, and
# stops short of a vendored tree. Raised from 3 on review: `services/api/internal/
# worker/package.json` is an ordinary shape and was out of scope.
_MANIFEST_MAX_DEPTH = 4
_NODE_LOCKS = ("package-lock.json", "package-lock.yaml", "pnpm-lock.yaml", "yarn.lock",
               "bun.lockb", "bun.lock")
_PY_LOCKS = ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock")


def _find_manifests(root, names, files=None, max_depth=_MANIFEST_MAX_DEPTH):
    """[Path] for every `names` file at or under root, to `max_depth` directories.

    `files` lets the caller pass the walk it already did: `common_checks` walks the tree
    once for `texts`, and re-walking it per check was three full traversals of a
    monorepo to answer one question about lockfiles.
    """
    root = Path(root)
    found = []
    for path in (_iter_files(root) if files is None else files):
        if path.name not in names:
            continue
        if len(path.relative_to(root).parts) - 1 > max_depth:
            continue
        found.append(path)
    return sorted(found)


def _locked_at_or_above(manifest, root, lock_names):
    """A lock beside the manifest, or at any ancestor up to the scan root.

    npm/pnpm/yarn workspaces put ONE lockfile at the workspace root and none beside the
    member packages, so requiring a sibling lock would report every well-run monorepo as
    unlocked — which is how a check earns its way into being ignored.
    """
    directory = manifest.parent
    root = Path(root).resolve()
    while True:
        if any((directory / name).is_file() for name in lock_names):
            return True
        if directory.resolve() == root or directory.parent == directory:
            return False
        directory = directory.parent


def _check_lockfile(root, files=None):
    root = Path(root)
    missing = []
    for manifest in _find_manifests(root, {"package.json"}, files):
        if not _locked_at_or_above(manifest, root, _NODE_LOCKS):
            missing.append(f"{manifest.relative_to(root)} without a lockfile "
                           f"({' / '.join(_NODE_LOCKS[:4])}) beside it or above it")
    for manifest in _find_manifests(root, {"pyproject.toml"}, files):
        locked = (_locked_at_or_above(manifest, root, _PY_LOCKS)
                  or _has_pinned_requirements(manifest.parent)
                  or _has_pinned_requirements(root))
        if not locked:
            missing.append(f"{manifest.relative_to(root)} without "
                           f"{' / '.join(_PY_LOCKS[:2])} or a pinned (==) "
                           f"requirements file")
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


def _check_gitignore(root, texts, files=None):
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
    # Nested too (item 6, same reason): a repo whose only package.json is
    # `frontend/package.json` is still a node project, and its node_modules still must
    # not enter the repo. One root .gitignore covers subdirectories, so only the
    # DETECTION needed widening, not the coverage lookup.
    node_matters = (bool(_find_manifests(root, {"package.json"}, files))
                    or (root / "node_modules").is_dir())
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
        if _is_env_file(path.name) or path.suffix.lower() not in _AUTH_SUFFIXES:
            continue
        match = _AUTH_INDICATOR_RE.search(text)
        if match:
            return core.CheckResult(
                id="core.exposure-auth", tier="ok",
                title="Authentication indicators found",
                detail=f"{path.name}: {match.group(0)}")
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
    """The common-core static check suite (id prefix `core.`), composed into every
    scan report by `scanner.core.scan` (D-010) and called directly by tests."""
    root = Path(root)
    texts = _text_files(root)
    paths = [path for path, _ in texts]
    return [
        _check_secret_scan(root, texts),
        _check_lockfile(root, paths),
        _check_gitignore(root, texts, paths),
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
        results = []                       # the core suite is composed by core.scan
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
        return []                          # the core suite is composed by core.scan

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

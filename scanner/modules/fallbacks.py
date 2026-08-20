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
from scanner.core import repo_relative

# The name of the file the presence notice below looks for. A literal, deliberately:
# `scanner.declarations` owns the parser and it is PARKED (D-012 out of Phase 1), so
# importing it for one string would re-wire the module into a live path — the thing
# `test_d012_no_live_code_imports_the_parked_declarations_module` exists to keep red.
# The two constants agreeing is asserted by that module's own tests.
DECLARATION_FILE = "deployhub.yaml"

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
    # N7 (TAKKO scan, 2026-08-11). A JWT carries its own authorization, so it is a
    # credential whatever it is called — and `data = "<jwt>"` names nothing, which is
    # how they usually appear. It is here for a second reason: the dotted-identifier
    # exclusion below drops any value shaped `ident.ident`, and a JWT IS dot-separated —
    # its base64url segments match that pattern whenever they carry no `-` and no
    # leading digit. Axis 1 runs first and never consults the exclusion, so this entry
    # is what makes that exclusion safe to ship. Both the header and the payload of a
    # real JWT are base64url of `{"…`, which is always `eyJ`; no import path starts a
    # segment that way and then continues in base64.
    ("JWT", re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
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


# N7 (TAKKO scan, 2026-08-11), the first two of three false-positive classes a real
# Django+Vite monorepo produced. Both are judgments about the VALUE, which is N5's
# principle: a rule on the name can be fooled by naming a variable after a setting, and
# a rule on the value cannot.
#
# ANCHORED AND EXACT, deliberately. `var(--x)` followed by 36 random characters is a key
# wearing a stylesheet lookup, and a prefix match would launder it.
_CSS_VAR_REF_RE = re.compile(r"^var\(--[A-Za-z0-9_-]+\)$")
# The same regex N5 put in `django.py::_looks_like_import_path`, which is where it
# stopped — it never reached this axis, so every attribute access whose name carried a
# secret word was a blocker here: TAKKO's `qr_token=preorder.pickup_code.token,` (an
# ordinary Python keyword argument) fired the unquoted arm, whose value alphabet allows
# `.`.
#
# THE FIRST CUT OF THIS RULE CLAIMED "no published credential format survives this
# pattern except a JWT". That claim was the defect, and the adversarial pass produced
# two counterexamples in one sitting:
#
#   dp.st.prod.aXbYcZdEfGhIjKlMnOpQrStUvWxYzAbCdEfGh   a Doppler service token
#   eyJhbGciOiJSUEEtT0FFUCJ9.QXBwRW5jS2V5.SXZWZWN0b3I.Q2lwaGVyVGV4dERhdGE.QXV0aFRhZw
#                                                      a 5-segment JWE
#
# Both match the pattern exactly. The JWE also slips axis 1: its second segment is the
# encrypted content key, not `eyJ…`, so the JWT format above does not match it. Dotted
# STRUCTURE is not provenance; what makes an import path harmless is that its segments
# are words. So the shape is necessary and no longer sufficient — see
# `_is_dotted_identifier_path` for the two measurements that bound it.
_DOTTED_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
# Measured, not guessed, over Django/DRF/Celery/allauth import paths and fleet attribute
# paths (the numbers below are whole-value Shannon bits/char unless stated):
#
#   longest real segment      32  `UserAttributeSimilarityValidator` (Django validator)
#   longest real segment in a
#     value that reaches an
#     axis                    26  `BCryptSHA256PasswordHasher` (PASSWORD_HASHERS)
#   highest real whole-value
#     entropy               4.489 `django.contrib.auth.hashers.BCryptSHA256PasswordHasher`
#   Doppler token          4.887  segment 37
#   5-segment JWE          5.023  segment 24
#
# Hence: a segment ceiling of 28 (clears the 26-char hasher class) and an entropy
# ceiling of 4.5 on values ≥40 chars (clears the hasher path at 4.489 — an 0.011-bit
# margin, which is thin, and is why the guard test names that exact value). The Doppler
# token is over BOTH ceilings (segment 37, entropy 4.89), so its regression test pins
# the pair without isolating either knob; the JWE (segments ≤24, entropy 5.02) is
# caught by the entropy ceiling alone and pins it, and the long-identifier cost test
# is what pins the segment ceiling alone. Second adversarial pass verified each knob
# goes red under mutation via those two tests.
#
# A per-SEGMENT entropy floor was measured and rejected: `BCryptSHA256PasswordHasher`
# alone is 4.18 bits and `PBKDF2SHA1PasswordHasher` 4.05, so any floor low enough to
# catch a random blob resurrects N5's PASSWORD_HASHERS false positive.
#
# KNOWN COST, accepted deliberately: the segment ceiling un-excuses genuine identifiers
# longer than 28 characters — Django's own `UserAttributeSimilarityValidator` (32) and
# long method names such as `get_signed_authentication_token` (31). Under a secret-shaped
# name those now produce a `[heuristic]`. A heuristic-tier false positive on a long
# method name is a cheaper mistake than a blocker-tier miss on a live credential, and
# the Django validator reaches no axis in practice (it is written as a dict entry,
# `{"NAME": …}`, which neither the core regex nor `django._string_literals` reads).
# `test_n7_fix2_the_segment_ceiling_costs_long_identifier_names` holds this cost visible.
_DOTTED_MAX_SEGMENT = 28
_DOTTED_ENTROPY_CEILING = 4.5
_DOTTED_ENTROPY_MIN_LEN = 40


def _is_css_var_reference(value):
    """True for `var(--color-pink-fill)` — a stylesheet lookup, never key material.

    TAKKO wrote `token: "var(--color-pink-fill)"` twelve times in one illustration
    component: the name axis matches `token`, and the value is 22 characters at 3.6
    bits/char, so it cleared the entropy floor every time.
    """
    return bool(_CSS_VAR_REF_RE.match(value))


def _is_dotted_identifier_path(value):
    """True for a value that is an import path or attribute access, and not a credential.

    `preorder.pickup_code.token`, `django.contrib.auth.hashers.Argon2PasswordHasher` —
    judged before the name/entropy question is asked, on both the core heuristic axis
    and (via `django._looks_like_import_path`, which delegates here) the Django settings
    axis. ONE implementation on purpose: N5's rule was ported to the core axis, the
    adversarial pass found a hole in the port, and the same hole was open in the
    original — a Doppler token committed as a Django setting was excused too.

    Three conditions, all required, with the measurements behind the two numbers in the
    comment above `_DOTTED_MAX_SEGMENT`:

      * the dotted-identifier SHAPE (necessary, and on its own not sufficient);
      * no segment ≥28 characters — a credential's random blob is one long segment
        (`dp.st.prod.<37 chars>`), an identifier is words;
      * not both ≥40 characters and ≥4.5 bits/char — the whole-value test that catches
        a 5-segment JWE, whose segments are individually short.
    """
    if not _DOTTED_IDENT_RE.match(value):
        return False
    if max(len(segment) for segment in value.split(".")) >= _DOTTED_MAX_SEGMENT:
        return False
    return not (len(value) >= _DOTTED_ENTROPY_MIN_LEN
                and _shannon_entropy(value) >= _DOTTED_ENTROPY_CEILING)


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
                        "demo", "fake", "redacted", "notreal",
                        # N7 (TAKKO scan, 2026-08-11): the Django `SECRET_KEY` set to
                        # `dev-only-not-a-secret-change-in-prod`, shipped in
                        # `.env.example` and in `config/settings/base.py`. 36 characters
                        # at 3.8 bits/char, so it cleared both floors while saying in
                        # words that it is not a credential. The `_looks_placeholder`
                        # escape below is the over-correction guard and is unchanged: a
                        # marker never excuses a value long AND random enough to be a
                        # real key. (The assignment is described rather than quoted so
                        # this comment does not trip `make log-scrub` — round-5 F10's
                        # marker exemption is for copy that MUST name the pattern.)
                        "dev-only", "not-a-secret")
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

# ── R9-A: resolve-containment, and this is the seam it belongs on ──────────────
#
# Round 9 contained `node_ts` — its source walk, its `package.json` reads and its four
# fixed-name reads — and the comment that shipped with that work said `fallbacks` needed
# none of the same treatment because
#
#     Nothing in fallbacks lets file CONTENT choose a default the operator is then
#     offered. Here it does, in every check in this module.
#
# THAT SENTENCE WAS FALSE, and it was false about both halves of this module. Two
# probes, no `..` in anything the repo commits and no workspace pattern involved:
#
#   * `Dockerfile -> ../victim/Dockerfile`, and `_parse_root_dockerfile` opened the
#     name. `EXPOSE 9999` from the neighbour became `manifest_draft.components.service
#     .port`, which SUPPRESSED the `dockerfile.port` wizard question (a port had been
#     "found", so the operator is never asked), and `dockerfile.expose`,
#     `dockerfile.non-root` and `dockerfile.latest-tag` all reported `ok` about an image
#     definition the scanned repo does not contain. That is a default chosen by outside
#     content, a wizard question deleted by outside content, and three vouched check
#     verdicts, from one link.
#   * `config/settings.py -> ../../victim/settings.py`, and this one rides the walk
#     below rather than a fixed name: `django._settings_files` is `_iter_files` plus a
#     name rule, and every `os.environ['…']` in the neighbour's settings became a
#     `django.env.<NAME>` wizard question — a `SECRET`-ish name among them becomes a
#     value the operator is asked to type into the vault.
#
# So containment moves HERE, to the one walk both modules share, rather than being
# copied into each caller: `_iter_files` refuses to YIELD an escaping file symlink, and
# `read_contained` is the same rule for the reads that open a fixed name and never touch
# the walk. Those two are the only ways into a repo-controlled path in this module and
# in `django`, which is said out loud at each of them, because a rule that is not
# written down is what produced this finding twice.
#
# THE CARVE-OUT, kept as narrow as it can be stated: the SECRET-SCAN axis may still read
# an escaping link. A committed `.env` that is a symlink to a real secret file is
# precisely what `core.secret-scan` hunts, and refusing to read it there would hide the
# finding the check exists for — that much of the round-7 rationale was right. It is
# scoped to the AXIS, not to the walk: `_text_files` puts escaping files in a separate
# list, `common_checks` hands that list to `_check_secret_scan` and to nothing else, and
# no other check, question, default or manifest fragment sees a byte of it.
#
# BOTH SIDES RESOLVED, and only symlinks are examined — `node_ts._symlink_escape_problem`
# for both reasons. A scan root is frequently reached THROUGH a symlink (`/tmp` on macOS,
# a checkout under a linked home), so comparing an unresolved root against a resolved
# file would refuse every file in such a tree; and an ordinary file found by a walk that
# already prunes symlinked directories is inside the tree by construction, so `resolve()`
# on every file of every scan would be paid for nothing.
#
# WHAT THIS RULE IS NOT ABOUT: existence. `DockerfileModule.detect`, `StaticModule
# .detect`, `_check_declaration_file` and `_locked_at_or_above` ask `is_file()` about a
# name and read nothing, so a symlinked `Dockerfile` still selects the dockerfile module
# — and then every check it makes reports the honest "no EXPOSE / no USER" of a file
# this scan may not read — and a symlinked `package-lock.json` still satisfies
# `core.lockfile`. Deriving a module's SELECTION, or a "this file is here" answer, from
# a link is a smaller thing than deriving a verdict from its content; it points in the
# safe direction for the two `detect`s, and for the lockfile probe it is the same
# question the walk answers about every other committed file. Narrowing it is a
# behaviour decision about what a linked path MEANS to a deploy — the same call
# `node_ts._find_data_files` is parked on — and wants its own diff. Stated rather than
# left for the next reader to find, which is the mistake this fix is undoing.


def _resolves_outside(root, path):
    """True when `path`'s resolved location is neither `root` itself nor under it.

    THE NAKED COMPARISON, with no symlink gate and no exception handling, because its
    two callers disagree about both and are right to (R10-A4):

      * `escapes_root` below asks it only about symlinks — an ordinary file found by a
        walk that already prunes symlinked directories is contained by construction, and
        resolving every file of every scan would be paid for nothing.
      * `node_ts._workspace_candidate_problem` asks it only about NON-symlinks: a
        symlinked workspace base is refused one line earlier, outright and for a
        different reason (it is a second NAME for a package, so accepting it
        double-counts a package the survey already has, whatever it points at).

      * `escapes_root` answers an unresolvable path with True and nothing else, because
        its callers want a verdict.
      * `_workspace_candidate_problem` answers it with a SENTENCE naming the exception
        class, because its caller is composing a report line the operator reads.

    So what is shared is the comparison and only the comparison. This raises whatever
    `resolve()` raises and the caller says what that means.

    THE ROOT-ITSELF ARM IS A RECONCILIATION, not a preserved difference, and this is the
    one place the two old spellings gave different answers. `_workspace_candidate_problem`
    carried `resolved != root_resolved`; `escapes_root` did not, so it called a link
    resolving TO the scan root an escape — the root is not among its own parents. A path
    that resolves to the root is inside the root by any reading, and the old answer was
    reachable only for a symlink to a directory, which every reader in this repo then
    fails to read anyway. One answer, and it is the defensible one.
    """
    resolved, root_resolved = Path(path).resolve(), Path(root).resolve()
    return resolved != root_resolved and root_resolved not in resolved.parents


def escapes_root(root, path):
    """True when `path` is a symlink resolving outside `root`. The containment rule.

    Public because `django` reads through it too: one rule, one implementation. A second
    copy is the defect N6, N7 and R4-12 are each an instance of.

    R10-Q1 — WHY THE EXCEPT CLAUSE NAMES TWO TYPES. `Path.resolve()` does not report an
    unresolvable path with one exception class. CPython 3.11's implementation catches
    the `OSError(ELOOP)` a symlink loop raises and re-raises it as `RuntimeError`
    ("Symlink loop from …"), so `except OSError` — the whole fail-closed arm — did not
    fire for the one input it most obviously exists for. It propagated instead: out of
    this function, out of `django.detect`, out of `scanner.core.scan`, and the operator
    of a repo carrying `requirements.txt -> requirements.txt` got a traceback and no
    report at all. A rule that fails closed must fail closed on every way its probe can
    fail, and the list of ways is the interpreter's, not this module's.
    """
    path = Path(path)
    if not path.is_symlink():
        return False
    try:
        return _resolves_outside(root, path)
    except (OSError, RuntimeError):
        # Unresolvable is not demonstrably contained, and this rule fails closed: the
        # secret-scan carve-out is the only axis allowed to read one of these, and it
        # gets them from the `escaping` list either way.
        return True


def read_contained(root, path):
    """`_read_text` for a fixed-name read, refusing content that escapes `root`.

    Returns None for a refused file — which is what `_read_text` already yields for an
    unreadable one, so every caller's existing empty-input path IS the refusal path and
    no caller learns a new failure mode.

    ONE OF THE TWO ENTRY POINTS. Every read this module and `django` make of a
    repo-controlled path goes through this or through `_iter_files`; a third way in is
    the finding, not a convenience.

    R10-A8 — THE TWO REPORTING CHANNELS THIS DOES NOT HAVE, and why it should not. It
    carried `skipped` and `escaping` parameters, threaded to `_read_text` and to a
    caller's refusal list; in three rounds no caller ever passed either, so both were
    the shape of a mechanism with nothing behind it, which is R7-15's finding about
    fields nothing writes.

    Filling them in would have been the wrong repair. All three callers here read a
    fixed name at the SCAN ROOT — `requirements*.txt`, `.gitignore`, `Dockerfile` — and
    the core walk yields and refuses those same files on its own, so recording a refusal
    here as well would put one file on `core.symlinked-files` twice. That is R10-A3's
    defect, one module in, and it is the reason `_check_symlinked_files` reads ONE list
    filled by ONE walk.

    The gap that leaves is named where it bites (see the R10-Q1 tests): a link the
    filesystem cannot resolve at all is neither `is_file()` nor `is_dir()`, so no walk
    yields it and this refusal is reported by nothing. That is a hole in the WALK's
    reach, and a second recorder at the read site is not what closes it.
    """
    path = Path(path)
    if escapes_root(root, path):
        return None
    return _read_text(path)


def _iter_files(root, skipped=None, *, prune=None, max_depth=None, escaping=None):
    """Yield tracked-looking files under root, skipping dependency/build/cache dirs.

    Dotfiles (`.env`) and dot-directories (`.github/`) are both yielded — only the
    names in `_SKIP_DIRS` are pruned. Symlinked directories are not followed: a link
    out of the tree is not the project's source, and a link back into it is a loop.

    R9-A: a symlinked FILE whose target resolves outside `root` is not yielded either —
    see the comment above this function for the two escapes that were live through it.
    `escaping`, when given, is a list this appends every such path to, which is how the
    secret-scan carve-out gets its input and how `core.symlinked-files` reports the
    refusal. A caller that passes nothing simply does not see the file, which is the
    right default for every consumer of this walk but one.

    R7-2: `skipped`, when given, is a list this appends every path the filesystem
    REFUSED to it — a permission-denied directory, one that vanished mid-walk. It used
    to swallow those with a bare `continue`, so a subtree the walk could not open
    produced no problem line, no warning and no tier change: a real AWS secret under a
    `prodcfg/` whose `iterdir` raised `PermissionError` turned the same tree from
    `blocker` into `tier: ok`, "No committed secrets found", empty detail. A security
    gate must degrade to an honest error, never to `ok`.

    AN OPTIONAL OUT-PARAMETER, and the shape is chosen for blast radius: this walk feeds
    `core.lockfile`, `core.gitignore` and `core.tests-exist` as well, and only
    `core.secret-scan` has anything to say about a skip. A return-tuple would have
    rewritten every caller (and every test that calls one) to carry a value they ignore;
    a raise would turn a dull unreadable directory into a failed scan. Callers that pass
    nothing behave exactly as they did.

    R8-6 GAVE IT TWO MORE CALLERS AND TWO KEYWORDS, and the keywords are what let this
    stay ONE walk instead of becoming three. `scanner/modules/django.py` had its own
    discovery built on `Path.rglob`, which recurses once per directory in CPython 3.11:
    a ~1000-deep tree raised an uncaught `RecursionError` inside `detect()` — before any
    check, for EVERY project regardless of framework, so a plain static site with a deep
    vendored tree exited 1 with no report at all. This walk has never had that problem
    because its stack is a list; what it did not have is the two things django's callers
    need, so they are here rather than in a second copy:

      * `prune` — the directory-name set to skip, defaulting to this module's
        `_SKIP_DIRS`. django keeps its own set (it skips `.hg`, `.venv-scaffold` and
        `staticfiles`, which this one does not; this one skips `data/` and a row of
        framework cache dirs, which django's does not). ONE walk, two scopes: making
        django adopt this module's set would have silently changed which files its
        settings discovery reads, and that is a security-check scope change, not a
        crash fix.
      * `max_depth` — the maximum number of path components a yielded file may have
        RELATIVE to `root`, so `project_root`'s own `len(rel.parts) <= 4` rule becomes a
        walk that stops rather than a filter applied after descending forever.

    `None` for either means "as before", and every existing caller passes neither.
    """
    prune = _SKIP_DIRS if prune is None else prune
    stack = [(Path(root), 0)]
    seen = set()
    while stack:
        directory, depth = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            if skipped is not None:
                skipped.append(directory)
            continue
        for path in entries:
            # Symlinked DIRECTORIES are not followed — a link out of the tree is not the
            # project's source and a link back into it is a loop. Symlinked FILES are
            # still read: master yielded them, and a committed symlinked `.env` or
            # config file is exactly the thing this suite is looking for.
            if path.is_symlink() and path.is_dir():
                continue
            if path.is_dir():
                if path.name in prune:
                    continue
                # A directory at depth+1 can only hold files at depth+2 or deeper, so
                # once depth+2 is past the cap there is nothing below worth opening.
                if max_depth is not None and depth + 2 > max_depth:
                    continue
                try:
                    key = path.resolve()
                except (OSError, RuntimeError):
                    # R10-Q1: `RuntimeError` for the same reason `escapes_root` names
                    # it — CPython 3.11 re-raises ELOOP as one. Unreachable today (a
                    # looping link is neither `is_dir()` nor `is_file()`, so it never
                    # gets here), and named anyway: this is the loop-detection arm of a
                    # walk, and it may not be the thing a loop takes down.
                    if skipped is not None:
                        skipped.append(path)
                    continue
                if key in seen:
                    continue
                seen.add(key)
                stack.append((path, depth + 1))
            elif path.is_file():
                if max_depth is not None and depth + 1 > max_depth:
                    continue
                if escapes_root(root, path):
                    if escaping is not None:
                        escaping.append(path)
                    continue
                yield path


def _read_text(path, skipped=None):
    """Return decoded text, or None for binary / oversized / unreadable files.

    R7-2 RULING, and the spec asked for it either way as long as it was stated: an
    unreadable FILE joins the same skip list as an unreadable directory, and a file this
    function DECLINED to read does not.

    The line is not "file versus directory", it is "the scanner chose not to look"
    versus "the filesystem refused to let it". A `PermissionError` on `creds.py` is the
    same blindness as one on `prodcfg/`, one level down — the scanner knows a file is
    there and cannot see a byte of it, and answering "no secrets" about it is the same
    lie at a smaller scale. A binary blob, an oversized bundle and an undecodable byte
    sequence are the opposite case: the scanner knows exactly what it passed over and
    why, the set is bounded by rules in this file rather than by the repo, and every
    repository on earth contains one. Warning on those would fire the check on every
    scan, and a warning that is always on is a warning that is read as off — which is
    how a real one gets missed. That is the over-correction this fix must not make.
    """
    try:
        if path.stat().st_size > _MAX_TEXT_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        if skipped is not None:
            skipped.append(path)
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


def _text_files(root, skipped=None, escaped=None):
    """[(path, text)] for every scannable text file under root.

    `skipped` is threaded to both halves of the walk (R7-2) — the directories that could
    not be opened and the files that could not be read are one list, because they are
    one fact about the report: this is not everything.

    R9-A: `escaped`, when given, is filled with the same `(path, text)` pairs for the
    symlinked files the walk REFUSED because they resolve outside `root` — a separate
    list rather than a flag on the tuple, so a check either asked for them or cannot
    reach them. `common_checks` gives that list to `_check_secret_scan` and to nothing
    else.
    """
    out = []
    escaping = [] if escaped is not None else None
    for path in _iter_files(root, skipped, escaping=escaping):
        text = _read_text(path, skipped)
        if text is not None:
            out.append((path, text))
    for path in escaping or ():
        text = _read_text(path, skipped)
        if text is not None:
            escaped.append((path, text))
    return out


def _shannon_entropy(value):
    if not value:
        return 0.0
    counts = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_interpolation(value):
    """True when userinfo is a variable reference, not a literal password.

    `redis://:{REDIS_PASSWORD}@host` (Python f-string) and `${VAR}` / `$VAR`
    (shell) put the variable's name in source. A committed credential is the
    bytes themselves.
    """
    if value.startswith("${") and value.endswith("}") and value[2:-1].isidentifier():
        return True
    if value.startswith("{") and value.endswith("}") and value[1:-1].isidentifier():
        return True
    if value.startswith("$") and value[1:].isidentifier():
        return True
    return False


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


def _is_env_family(name):
    """`.env` or any `.env.*`, TEMPLATES INCLUDED.

    N7: `core.gitignore` asks a different question from the secret scan — not "is this
    file a leak?" but "will a leak be ignored when it arrives?" — and a template is
    evidence the project uses env files at all (it is a list of the variables the real
    one will hold). Tightening `_is_env_file` narrowed that check by accident, so the
    two questions have two predicates now.
    """
    return name == ".env" or name.startswith(".env.")


def _is_env_file(name):
    """True for an environment file, False for a template OF one.

    N7 (TAKKO scan, 2026-08-11): the exclusion was three exact names, so
    `docker/.env.prod.example` — one template per environment, an ordinary layout — was
    reported as a leak. It is a SUFFIX rule now. Templates still get scanned line by
    line by both axes above: a real key pasted into `.env.example` is a real key, and
    that is one of the commonest ways one gets committed.
    """
    return (_is_env_family(name)
            and not name.endswith((".example", ".sample", ".template")))


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
    # EVERY match on the line, not the first (N8 follow-up, adversarial pass): the tests
    # below are per-MATCH, and a per-match test that ends the search hides everything
    # after it. `DB=postgres://app:<REPLACE_ME>@db1 REAL=postgres://app:Tr0ub4dor3xK9@db2`
    # returned None — the documentation URL shadowed the real credential standing beside
    # it, and that line had been a (noisy) blocker before the angle-bracket veto existed,
    # so the veto made a real finding disappear. The rule this encodes outlives the
    # particular veto: a test that excuses a value may skip ITS OWN match and may never
    # end the search. The 6-character floor and `_looks_placeholder` were per-match all
    # along and shadowed exactly the same way.
    for match in _CONNECTION_STRING_RE.finditer(line):
        password = match.group("password")
        # N7 follow-up (fleet re-record, 2026-08-11): E-invoice's
        # `app/.env.prod.example` documents the format as
        # `# redis://:<this>@redis:6379/0`, and Fix 3 — correctly — turned the line
        # scan back on over template files, so this was reported at `[proof]` tier with
        # `<this>` as the password. A `[proof]` false positive is the worst kind the
        # check can produce: the label's whole job is to say "not a guess".
        #
        # This is a VALIDITY argument, not a heuristic. RFC 3986 §2 requires `<` and
        # `>` to be percent-encoded anywhere in a URI, so userinfo carrying one bare
        # cannot parse and cannot be a working credential — the value is documentation
        # by construction. It is also why the rule is not the one-character bypass the
        # F1 review found in `_is_address_not_credential`: inserting `<` into a real
        # connection string to launder it past this check breaks the connection string.
        # A percent-encoded real password (`S3cret%3CPass%3E`) carries no bare bracket
        # and still fires.
        documented = "<" in password or ">" in password
        if (len(password) >= 6 and not documented
                and not _looks_placeholder(password)
                and not _looks_interpolation(password)):
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


def _check_secret_scan(root, texts, skipped=()):
    """Two buckets, and no third one: what blocks, and what the SCANNER's own rules
    classify as test material.

    D-012 OUT OF PHASE 1 (2026-08-16, Joseph's cap decision). This check used to take a
    `declared` argument — the scanned repo's `deployhub.yaml` claim — and route heuristic
    findings under a declared path into a third bucket, with a header, a label carrying
    the repo's own words, and an `acceptance` contract naming the confirms that would
    clear it. Every one of those is gone. A repo's claim about itself now changes
    nothing about what this check reports, which is the design intent stated at its
    narrowest: nothing downgrades anything. The presence of the file is reported once,
    honestly, by `_check_declaration_file` below.

    ROUND 7 (R7-2), and this part stays: `skipped` is what the walk could not open — see
    `_iter_files`. This check may not report `ok` about a subtree it never read, so a
    skip alone is a `warning`, and where there are findings the skip list rides the
    detail. It is the only core check that takes the list — scope the axis, not the walk.
    """
    findings, test_findings = [], []
    for path, text in texts:
        rel = path.relative_to(root)
        bucket = test_findings if _is_test_path(rel) else findings
        if _is_env_file(path.name):
            # N7 (TAKKO scan, 2026-08-11): this line used to read "committed .env file",
            # which the scanner has no way to know — it reads a TREE and cannot see git.
            # TAKKO's `backend/.env` is gitignored and untracked, and the report called
            # it committed anyway. What the scan CAN see is that the file is here and
            # will ship with a deploy of this tree; whether it is also in git is for the
            # reader to check, and the fix_hint says so.
            bucket.append(f"{rel}: .env file present in the scan tree")
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
                # N7: the two value-shape exclusions apply to BOTH arms and run before
                # the entropy judgment — a stylesheet lookup and an attribute access
                # both clear the floor comfortably, which is exactly why they were
                # reported. Nothing here reaches axis 1, which has already run and
                # `continue`d on this line if it matched.
                if (not _is_address_not_credential(value)
                        and not _is_css_var_reference(value)
                        and not _is_dotted_identifier_path(value)
                        and not _is_identifier_echo(name, value)
                        and not _looks_placeholder(value)
                        and _shannon_entropy(value) >= floor):
                    bucket.append(
                        f"{rel}:{lineno}: [heuristic] hardcoded {name.lower()} value")

    unread = _skipped_section(root, skipped)
    if findings:
        detail = _join_sections(
            "\n".join(findings),
            _test_material_section(test_findings),
            unread,
        )
        return core.CheckResult(
            id="core.secret-scan", tier="blocker",
            title="Secrets detected in the scanned tree",
            detail=detail,
            fix_hint=_blocker_fix_hint(),
        )
    if test_findings:
        # Reported, not blocked. A fixture password is not a deployable credential, and
        # a blocker that fires on every test suite is a blocker people learn to route
        # around — but a real key does get committed to a test file sometimes, so the
        # finding still has to appear in the report with its file and line.
        #
        # D-012 out of Phase 1: the branch that also landed here — a `deployhub.yaml`
        # the parser refused — is gone with the parser, and so is the two-part title
        # that named which of the two things had happened. This tier is the scanner's
        # own auto-detection and nothing else, which is what the title says.
        detail = _join_sections("\n".join(test_findings), unread)
        return core.CheckResult(
            id="core.secret-scan", tier="warning",
            title="Secret-shaped values in test material only",
            detail=detail,
            fix_hint="These are in test material, so they do not block a deploy. "
                     "Confirm each one is a fixture rather than a real credential that "
                     "was pasted into a test — if any is real, rotate it: it is in git "
                     "history either way.",
        )
    if unread:
        # R7-2, and this branch is the entire finding: without it the return below said
        # "No committed secrets found" about a tree the walk could not open. `ok` is a
        # claim, and this check has not earned it here — the honest answer is that it
        # does not know. A separate result rather than a third branch of the warning
        # title, because "we could not look" is not a finding about the repo's test
        # material and reads as noise filed under that title.
        return core.CheckResult(
            id="core.secret-scan", tier="warning",
            title="Secret scan incomplete — part of the tree could not be read",
            detail=unread,
            fix_hint="Nothing was found in what could be read, and that is not the same "
                     "as nothing being there. Give the scanner read access to the paths "
                     "above (or remove them from the tree you are deploying) and scan "
                     "again — a permission-denied directory is also worth a look on its "
                     "own account, since it is unusual in a repository.",
        )
    return core.CheckResult(id="core.secret-scan", tier="ok",
                            title="No secrets found in the scanned tree")


def _join_sections(*sections):
    return "\n\n".join(s for s in sections if s)


# How many unreadable paths a report names before it stops. Same reasoning as
# `MAX_REASON_CHARS` and `MAX_DECLARATIONS`: the COUNT is the number the reader needs
# and it is printed first, so the list can be truncated without truncating the fact.
_MAX_SKIPPED_REPORTED = 10


def _report_path(root, path):
    """A skipped path, rendered so it cannot forge a line of the report (R7-3's rule).

    Directory and file names are repo-controlled text — a directory name may contain a
    newline on every filesystem this runs on — and this section is new report surface
    built out of them. A value that occupies two lines is printed through `repr` so it
    occupies one; everything else is printed as itself, because a report of escaped
    paths is a report nobody can paste into a shell.
    """
    try:
        text = str(Path(path).relative_to(root))
    except ValueError:                     # pragma: no cover - defensive
        text = str(path)
    return text if text.splitlines() == [text] else repr(text)


def _skipped_section(root, skipped):
    """The paths the walk could not read, capped and counted (R7-2)."""
    if not skipped:
        return ""
    shown = [_report_path(root, p) for p in skipped[:_MAX_SKIPPED_REPORTED]]
    rest = len(skipped) - len(shown)
    lines = [f"Could not be read, so these results may be incomplete "
             f"({len(skipped)} path{'' if len(skipped) == 1 else 's'}):"]
    lines.extend(shown)
    if rest > 0:
        lines.append(f"… and {rest} more")
    return "\n".join(lines)


def _test_material_section(test_findings):
    if not test_findings:
        return ""
    return "Also in test material (not blocking):\n" + "\n".join(test_findings)


# The `[proof]`/`[heuristic]` legend, unchanged and still the whole explanation of the
# two labels — which is why it stays a constant rather than being reworded: every
# recorded demo artifact reads it back.
_CONFIDENCE_LEGEND = (
    "[proof] lines matched a published credential format — a GitHub "
    "token, a PEM block, an AWS key id — and are not guesses. "
    "[heuristic] lines are a secret-shaped name assigned a "
    "high-entropy literal: real most of the time, and worth a look "
    "before you decide.")


def _blocker_fix_hint():
    """D-012 out of Phase 1: back to one lead sentence and the legend.

    The two branches this used to have — one for a check whose whole blocking case was
    a declared tree, one for everything else — described an acceptance that no longer
    exists, and the paragraph after them told the operator that answering a wizard
    confirm would clear these lines. There is no such confirm this phase, and copy that
    points at a control the product does not have is the defect round 7 spent itself on,
    pointing the other way.
    """
    lead = ("Move secrets to the vault / environment injection. A .env file "
            "in this tree ships with a deploy of it, and is a leak as well if "
            "it is committed — check `git status`, add .env to .gitignore, and "
            "rotate anything that was committed: it stays in git history until "
            "you do.")
    return "\n\n".join([lead, _CONFIDENCE_LEGEND])


def _check_declaration_file(root):
    """`core.declaration-file`, or None when the repo carries no `deployhub.yaml`.

    HONEST, NOT SILENT — the third of the cap decision's design intents, and the reason
    unwiring D-012 is not simply deleting its reader. A repo in this fleet already
    carries a `deployhub.yaml` whose entire purpose is to be a reviewable claim about
    its own drill trees. Ignoring it without a word would leave that repo believing a
    downgrade is in force while the scanner reports every line at full tier — the
    design's own sin (a claim nobody checks) inverted into a check nobody knows about.
    So the file's PRESENCE is reported, once, at warning tier, and its CONTENTS are not
    read: nothing in this result can be derived from repo-controlled text, which is what
    keeps the six adversarial rounds of `scanner/declarations.py` from being load-bearing
    while that module is parked.

    Warning rather than advice because it is actionable and the action is not obvious:
    the operator's mental model of what blocks their deploy is wrong until they read it.

    `Path.is_file()` and nothing else. A directory or a dangling symlink named
    `deployhub.yaml` holds no claim anybody wrote, so it is simply absent for this
    notice's purposes; R8-14's contract about what counts as present left with the
    mechanism it guarded. The file is otherwise an ordinary file in the tree and is
    scanned by every check here like any other — including the secret scan, which is
    said out loud in the detail because a reader who has just been told the file is
    "ignored" would reasonably assume otherwise.
    """
    if not (Path(root) / DECLARATION_FILE).is_file():
        return None
    return core.CheckResult(
        id="core.declaration-file", tier="warning",
        title=f"{DECLARATION_FILE} is present but declarations are disabled",
        detail=(
            f"This repo carries a {DECLARATION_FILE}. The declared-test-material "
            f"mechanism it belongs to is deferred to its own phase, so this scan did "
            f"not parse the file and no claim in it changed anything: every finding "
            f"under a declared path is reported at its full tier, exactly as it would "
            f"be if the file were not here. The file is otherwise ignored — and it is "
            f"scanned like any other file in the tree, so a credential written into it "
            f"is a finding of its own."),
        fix_hint=(
            f"Nothing to do for the deploy: no result above was downgraded. Read this "
            f"as a correction to what the repo expects — if a tree was declared in "
            f"{DECLARATION_FILE} in the belief that its findings would stop blocking, "
            f"they are blocking, and either the findings or that expectation needs "
            f"attention. Leaving the file in place is fine; it will be honored again "
            f"when the mechanism returns with the threat model it is waiting on."),
    )


def _has_pinned_requirements(root, directory):
    """R9-A: `glob` is a fixed-name read by another spelling — it yields symlinks and
    never went through the walk. A pinned `requirements.txt` is one of the three ways
    `core.lockfile` is satisfied, so a link to a neighbour's pinned file vouched for a
    repo that pins nothing.
    """
    for req in Path(directory).glob("requirements*.txt"):
        text = read_contained(root, req)
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
                  or _has_pinned_requirements(root, manifest.parent)
                  or _has_pinned_requirements(root, root))
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


def _project_gitignore(root):
    """The `.gitignore` this check reads.

    Scan-root wins. If none is there, walk up from each `manage.py` toward
    the scan root and take the nearest file — E-invoice's is `app/.gitignore`
    above `app/backend/manage.py`. A `.gitignore` under a frontend/ package
    is not on that walk, so it is not a substitute.
    """
    root = Path(root)
    at_root = root / ".gitignore"
    if at_root.is_file():
        return at_root
    skip = {".git", ".hg", ".venv", "venv", "node_modules", "__pycache__",
            "dist", "build"}
    candidates = []
    for path in _iter_files(root, prune=skip, max_depth=4):
        if path.name != "manage.py":
            continue
        cur = path.parent
        while True:
            gi = cur / ".gitignore"
            if gi.is_file():
                candidates.append(gi)
                break
            if cur == root or cur.parent == cur:
                break
            cur = cur.parent
    if not candidates:
        return None
    return min(candidates, key=lambda p: len(p.relative_to(root).parts))


def _check_gitignore(root, texts, files=None):
    root = Path(root)
    gitignore = _project_gitignore(root)
    if gitignore is None:
        return core.CheckResult(
            id="core.gitignore", tier="warning",
            title="No .gitignore",
            detail="The project has no .gitignore at the scan root or above a nested manage.py.",
            fix_hint="Add a .gitignore covering at least .env and (for node "
                     "projects) node_modules, so secrets and dependency trees "
                     "never enter the repo.",
        )
    # R9-A: the content of this file IS `core.gitignore`'s verdict, so it is read
    # through the containment rule like every other repo-controlled name.
    lines = [ln.strip() for ln in (read_contained(root, gitignore) or "").splitlines()
             if ln.strip() and not ln.strip().startswith("#")]

    def covered(token):
        return any(token in ln for ln in lines)

    gaps = []
    # N7: templates count HERE (`_is_env_family`, not `_is_env_file`) — a repo shipping
    # `docker/.env.prod.example` and no .gitignore rule is the repo about to commit the
    # real one.
    env_matters = (any(_is_env_family(p.name) for p, _ in texts)
                   or (root / ".env").exists())
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


def common_checks(root, refused_elsewhere=()):
    """The common-core static check suite (id prefix `core.`), composed into every
    scan report by `scanner.core.scan` (D-010) and called directly by tests.

    D-012 out of Phase 1: the `declared` parameter is gone. It carried the one
    `deployhub.yaml` read of a scan (R7-13's one-read rule, which existed because two
    reads of a repo-controlled file can disagree inside one scan); with no reads at all
    the rule is moot and the signature says so.

    R10-A3: `refused_elsewhere` is the paths a matched module has already told the
    operator it refused, and it narrows `core.symlinked-files` and NOTHING ELSE — in
    particular not the secret-scan carve-out, which still reads every escaping file the
    walk found. Defaulted to empty because this function is called directly by tests and
    by nothing else that knows which modules matched; `scanner.core.scan` is the one
    caller with that answer.
    """
    root = Path(root)
    # R7-2: one list, filled by the one walk the suite makes, read by the one check that
    # has anything to say about it.
    skipped = []
    # R9-A: and a second one exactly like it, for the same reason at the other end —
    # `escaped` is what the walk refused to give the suite because it resolves outside
    # the scan root, and `_check_secret_scan` is the one check allowed to read it. Scope
    # the axis, not the walk.
    escaped = []
    texts = _text_files(root, skipped, escaped)
    paths = [path for path, _ in texts]
    suite = [
        _check_secret_scan(root, texts + escaped, skipped),
        _check_lockfile(root, paths),
        _check_gitignore(root, texts, paths),
        _check_tests_exist(root),
        _check_healthz(texts),
        _check_digest_pins(root, texts),
        _check_exposure_auth(texts),
    ]
    # APPENDED, and only when the file is there. The seven above keep their positions so
    # a report from a repo with no `deployhub.yaml` is byte-identical to the one it
    # produced before this notice existed — the same None-omission property that let
    # `acceptance` be added without moving a recorded artifact, applied to a whole check.
    notice = _check_declaration_file(root)
    if notice is not None:
        suite.append(notice)
    # APPENDED LAST, and only when something was refused — same property, and last so
    # that a repo carrying a `deployhub.yaml` and no symlink keeps the report it had.
    refusals = _check_symlinked_files(root, escaped, refused_elsewhere)
    if refusals is not None:
        suite.append(refusals)
    return suite


def _check_symlinked_files(root, escaped, refused_elsewhere=()):
    """`core.symlinked-files`, or None when the walk refused nothing this check owns.

    THE REFUSAL CHANNEL, and it is core-level rather than per-module by choice. The
    alternative the finding offered was each module's own problem channel — what
    `node-ts.symlinked-files` is — and that shape does not fit here: the rule now lives
    in ONE walk and ONE read helper shared by `fallbacks` and `django`, so a per-module
    line would mean threading a list through every check signature in both modules to
    report a fact the shared seam already knows. One check, emitted once per scan, says
    the same thing in the place the reader is already looking.

    WHAT IT COVERS, stated because it is not "every escaping link in the tree": these
    are the files the CORE walk refused, which is `_SKIP_DIRS`-pruned and unbounded in
    depth. `django` walks the same function with its own prune set (it skips `.hg`,
    `.venv-scaffold` and `staticfiles`; this one skips `data/` and the framework cache
    dirs), so a link under `data/` is refused to django's checks without being named
    here. The REFUSAL is what protects the report; this line is how the operator learns
    a file they can see is not in it, and losing that line for a link under a cache
    directory costs nothing a reader would act on.

    ONE FACT, ONE LINE (R10-A3). A framework module that has its own refusal channel —
    `node-ts.symlinked-files` — walks part of the same tree, so an escaping link inside
    a surveyed package was named here AND there: two warnings for one file, counted
    twice in the tier summary, and offered twice to the operator who has to accept the
    warnings before a manifest can be materialized. `refused_elsewhere` is what that
    module already said, and those files are dropped from this line.

    SUBTRACTIVE ON THE FILE, and deliberately not the other instrument available.
    Declaring `core.symlinked-files` in node-ts's `supersedes` would have replaced this
    result outright — and this check does not report node-ts's escapes, it reports the
    CORE walk's, which covers reads no framework module makes at all (a linked `.env`
    is the sharp one: refused here, and nothing node-ts ever opens). Supersession would
    have deleted those. Excluding the named file leaves every other refusal exactly
    where it was, including on trees where this line drops to nothing and vanishes,
    which is the same None-omission property the check has always had.

    Warning rather than advice, for `core.declaration-file`'s reason: it is actionable,
    and the operator's model of what the scan read is wrong until they read it.
    """
    elsewhere = {Path(p) for p in refused_elsewhere}
    escaped = [pair for pair in escaped if pair[0] not in elsewhere]
    if not escaped:
        return None
    shown = [_report_path(root, path) for path, _ in escaped[:_MAX_SKIPPED_REPORTED]]
    rest = len(escaped) - len(shown)
    # R10-A8: the noun and the VERB, both. Pluralizing only the noun left the singular
    # reading "1 symlinked file resolve outside the scanned repository" — the frontend's
    # R9-8 defect ("3 Deferred to sandboxs") in the mirror, and the same remedy: spell
    # both forms rather than appending an `s` to whichever word is nearest.
    count = len(escaped)
    lines = [f"{count} symlinked file{'' if count == 1 else 's'} "
             f"{'resolves' if count == 1 else 'resolve'} outside the scanned "
             f"repository:"]
    lines.extend(shown)
    if rest > 0:
        lines.append(f"… and {rest} more")
    return core.CheckResult(
        id="core.symlinked-files", tier="warning",
        title="Files linked out of the scanned repository were not read",
        detail="\n".join(lines),
        # R12-A1: the same files as a machine-readable fact, and ALL of them — the detail
        # above shows `_MAX_SKIPPED_REPORTED` of them and counts the rest, because a
        # report is for reading. `refused_paths` is for the guard in `scanner.core.scan`
        # and for anything else that needs to know which files this line is about without
        # parsing prose that quotes, truncates and pluralizes.
        # R13-ARCH-B: `core.repo_relative`, which `node_ts` and the guard in
        # `scanner.core.scan` also call. This line used to be the third hand-written copy
        # of that conversion, and the only one of the three that nothing compared against
        # either of the others.
        refused_paths=[rel for rel in (repo_relative(root, path) for path, _ in escaped)
                       if rel is not None],
        fix_hint=(
            "A scan reads only the tree it was pointed at, so these files decided "
            "nothing above: no check verdict, no wizard default, no manifest value was "
            "taken from them, and the results that would have used them report what "
            "this repository alone contains. They ARE still read by the secret scan — a "
            "linked .env pointing at a real credential is a finding whichever tree it "
            "lives in. If one of these is genuinely part of this project, commit the "
            "file itself (or move the target inside the repository) and scan again."),
    )


# ── fallback module: dockerfile (§V4) ───────────────────────────────────────────

def _parse_root_dockerfile(root):
    """(has_expose, first_port, has_user, latest_findings) for root Dockerfile.

    R9-A: through `read_contained`, because this is a fixed-name read that never touches
    the walk — and it is the probe that demonstrated the finding. A refused Dockerfile
    parses as the empty one, which lands on "no EXPOSE" (the wizard asks for a port),
    "no USER" and no `:latest` findings: the safe direction in all three.
    """
    text = read_contained(root, Path(root) / "Dockerfile") or ""
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

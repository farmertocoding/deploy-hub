"""The D-010 scanner follow-up list: items 1, 3–8.

`architect-ruling-django-common-checks.md` closed the composition defect — a Django
scan emitted none of the seven `core.*` checks — and left an ordered list of what that
work made visible. Item 2 (waiver parsing) was closed with the gate follow-up; item 9
(re-recording the demo records) needs the real repos re-staged. The rest are here.

  1  A module can supersede `core.secret-scan` from blocker to `ok`, and the only
     watcher is code review.
  3  `core.secret-scan`'s assignment regex misses `AWS_SECRET_ACCESS_KEY = '…'` and
     `SECRET_KEY = '…'` — the keyword has to be followed *immediately* by `=` or `:`.
  4  Dot-directories are skipped entirely, so a key in `.github/workflows/` is invisible.
  5  The placeholder filter hides a real key whose value carries a conventional prefix.
  6  `core.lockfile` / `core.gitignore` read only scan-root files, so both are vacuously
     `ok` on every repo in the fleet — all of which nest their manifests.
  7  `core.exposure-auth` matches the substring `session`, so `SESSION_COOKIE_SECURE`
     alone satisfies it.
  8  Duplicate module names bypass the registry invariant's per-module row.

Every test here states the *old* behaviour in its docstring, because the value of these
checks is entirely in what they used to miss.
"""
import pathlib

import pytest

from scanner import core
from scanner.modules import fallbacks

REPO = pathlib.Path(__file__).resolve().parent.parent


def _core(root):
    return {c.id: c for c in fallbacks.common_checks(root)}


def _project(tmp_path, files, name="proj"):
    root = tmp_path / name
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


# A real-looking AWS secret access key: 40 chars, base64 alphabet, high entropy. Not a
# live credential — generated for this test and matching no account.
FAKE_AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
FAKE_HIGH_ENTROPY = "hT4pQz8LmVx2Nb9RkS6wYc3JdF7gA5eUq1XoZi0P"


# ── item 3: the assignment regex misses the two commonest shapes ────────────

@pytest.mark.parametrize("line", [
    'AWS_SECRET_ACCESS_KEY = "%s"' % FAKE_HIGH_ENTROPY,
    "SECRET_KEY = '%s'" % FAKE_HIGH_ENTROPY,
    'STRIPE_SECRET_KEY: "%s"' % FAKE_HIGH_ENTROPY,
    'GITHUB_TOKEN_VALUE = "%s"' % FAKE_HIGH_ENTROPY,
    'my_api_key_prod = "%s"' % FAKE_HIGH_ENTROPY,
    'CLIENT_SECRET_ID="%s"' % FAKE_HIGH_ENTROPY,
])
def test_issue_d010_3_a_secret_keyword_may_sit_anywhere_in_the_identifier(tmp_path, line):
    """`secret` followed by `_ACCESS_KEY` is still `secret` (D-010 follow-up item 3).

    The old pattern required the keyword to be followed immediately by `=` or `:`, so
    the two most common shapes in the fleet never matched. Inside a Django settings
    file `django.secret-key-literal` covered `SECRET_KEY`; in a task module, a
    management command, a CI file or a shell script, nothing did.
    """
    root = _project(tmp_path, {"app/config.py": f"{line}\n"})
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", (
        f"{line!r} scanned clean — the assignment regex still requires the keyword to "
        f"be the last word of the identifier")
    assert "app/config.py:1" in result.detail


@pytest.mark.parametrize("line", [
    'SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]',        # the correct shape
    'api_key = process.env.API_KEY',
    'token_url = "https://example.com/oauth/token"',       # a URL, not a credential
    'password_field = "password"',                          # short, and a field name
    'SECRET_KEY = ""',
    'AWS_SECRET_ACCESS_KEY = "changeme-changeme-changeme"',  # an actual placeholder
    'api_key = "your_api_key_here_1234"',
])
def test_issue_d010_3_the_widened_regex_does_not_cry_wolf(tmp_path, line):
    """A blocker that false-fires is a blocker people learn to route around.

    The widening is only worth having if the shapes that are *not* credentials stay
    quiet: environment reads, URLs, field names, empty values and honest placeholders.
    """
    root = _project(tmp_path, {"app/config.py": f"{line}\n"})
    result = _core(root)["core.secret-scan"]
    assert result.tier == "ok", (
        f"{line!r} was reported as a committed secret:\n{result.detail}")


# ── item 5: a marker word must not excuse a real key ───────────────────────

def test_issue_d010_5_a_conventional_prefix_does_not_excuse_a_real_key(tmp_path):
    """`django-insecure-<50 random chars>` is what `startproject` writes.

    It contains the placeholder marker `insecure`, so the filter dropped it outright —
    and on a great many sites that string is the production `SECRET_KEY`. A marker now
    excuses a low-signal value and stops excusing anything long and random enough to be
    a real credential.
    """
    generated = "django-insecure-" + FAKE_HIGH_ENTROPY + "aB7#qZ"
    root = _project(tmp_path, {"app/conf.py": f'SECRET_KEY = "{generated}"\n'})
    assert _core(root)["core.secret-scan"].tier == "blocker", (
        "Django's own generated dev key, committed, still scans clean")

    # …while the genuinely low-signal placeholders it was written for stay quiet.
    for placeholder in ("changeme-changeme-changeme-changeme-changeme",
                        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                        "your_api_key_here_replace_before_deploy"):
        quiet = _project(tmp_path, {"c.py": f'SECRET_KEY = "{placeholder}"\n'},
                         name=placeholder[:8])
        assert _core(quiet)["core.secret-scan"].tier == "ok", placeholder


# ── what the widening cost on a real repo, and what was done about it ──────
#
# Both of these were found by running the widened rule over this repository — a real
# Django project with a frontend, CI workflows, dev scripts and a test suite — rather
# than over fixtures. Neither was predictable from the fixtures, and a blocker that
# fires on every normal repo is a blocker people learn to route around, which costs
# more than the miss it was written to fix.

def test_an_enum_label_is_not_a_credential(tmp_path):
    """`CLOUD_CREDENTIAL = "cloud_credential"` — the value IS the name.

    Choice values, enum labels, header names and field names all take this shape, and
    the widened keyword match walks straight into them: `cloud_credential` is 16
    characters and clears the entropy floor. Found in this repo's own `vault/models.py`.
    """
    root = _project(tmp_path, {"models.py": (
        'ENV_BUNDLE = "env_bundle"\n'
        'CLOUD_CREDENTIAL = "cloud_credential"\n'
        'API_TOKEN = "api_token"\n'
        'X_API_KEY_HEADER = "x-api-key-header"\n')})
    result = _core(root)["core.secret-scan"]
    assert result.tier == "ok", result.detail

    # Compared exactly, not by "looks like an identifier": a lowercase hex token also
    # looks like an identifier, and it is a real key.
    hexish = _project(tmp_path, {"c.py": 'api_token = "3f9c8e2b1d4a7605fe3c9b8a2d1e4f70"\n'},
                      name="hexish")
    assert _core(hexish)["core.secret-scan"].tier == "blocker"


def test_secrets_in_test_material_are_reported_but_do_not_block(tmp_path):
    """A fixture password is not a deployable credential.

    Scanning this repo produced eleven blocker lines, every one of them a login helper
    in the auth test suite. Dropping them would be wrong — a real key does get pasted
    into a test sometimes — so they are reported at `warning` with file and line, and
    a single finding outside test material still blocks.
    """
    tests_only = _project(tmp_path, {
        "tests/test_login.py": f'def _login(c, password="{FAKE_HIGH_ENTROPY}"): ...\n',
        "src/app.py": "print('hello')\n"}, name="tests_only")
    result = _core(tests_only)["core.secret-scan"]
    assert result.tier == "warning", result.detail
    assert "tests/test_login.py:1" in result.detail
    assert "test material" in result.title.lower() or "test" in result.title.lower()

    mixed = _project(tmp_path, {
        "tests/test_login.py": f'password = "{FAKE_HIGH_ENTROPY}"\n',
        "src/settings.py": f'API_TOKEN_VALUE = "{FAKE_HIGH_ENTROPY}"\n'}, name="mixed")
    blocked = _core(mixed)["core.secret-scan"]
    assert blocked.tier == "blocker"
    assert "src/settings.py:1" in blocked.detail
    assert "tests/test_login.py:1" in blocked.detail, (
        "the test-material findings vanished from a report that blocks for another "
        "reason — they are lower priority, not invisible")


def test_a_fixture_scanned_at_its_own_root_is_not_test_material(tmp_path):
    """The test-path rule is relative to the SCAN root, not to this repo.

    `tests/fixtures/django/legacy_bad` carries a real committed Django SECRET_KEY. When
    the scanner is pointed at it — which is what every fixture-based test does — the key
    is at `settings.py`, not under a `tests/` directory, and it must still block.
    """
    from scanner.modules import fallbacks as fb
    assert not fb._is_test_path(pathlib.Path("settings.py"))
    assert fb._is_test_path(pathlib.Path("tests/test_login.py"))
    assert fb._is_test_path(pathlib.Path("src/__tests__/login.spec.ts"))
    assert not fb._is_test_path(pathlib.Path("src/latest/config.py")), (
        "'latest' is not a test directory")

    legacy = REPO / "tests" / "fixtures" / "django" / "legacy_bad"
    assert _core(legacy)["core.secret-scan"].tier == "blocker"


# ── what the security review of the first cut found ────────────────────────
#
# Four findings, two of them holes this change itself opened. Recorded here because a
# security check that gets narrowed by its own noise-reduction is the failure mode that
# matters most: nobody notices a blocker that stopped blocking.

@pytest.mark.parametrize("value,blocks", [
    ("x://" + FAKE_HIGH_ENTROPY, True),                 # a scheme nobody uses
    ("zzz://" + FAKE_HIGH_ENTROPY, True),
    ("postgres://app:RealPassw0rdHere@db:5432/app", True),   # userinfo IS the credential
    ("mongodb+srv://svc:s3cretValue99@cluster0.example.net", True),
    ("https://example.com/oauth/token", False),         # an address, and only that
    ("https://user@example.com/callback", False),       # userinfo with no password
    ("/etc/ssl/private/service.pem", False),
    ("./config/credentials.json", False),
])
def test_review_f1_a_url_prefix_is_not_a_free_pass(tmp_path, value, blocks):
    """`API_KEY = "x://<40-char key>"` scanned clean — a one-character bypass.

    The first cut skipped any value matching `^\\w+://`, which did two wrong things at
    once: it let an arbitrary invented scheme launder a key past the blocker, and it
    dropped the one URL shape that *is* a credential — a connection string with an
    embedded password, which is how database credentials most often get committed.
    """
    root = _project(tmp_path, {"conf.py": f'DB_PASSWORD = "{value}"\n'},
                    name=str(abs(hash(value))))
    tier = _core(root)["core.secret-scan"].tier
    assert (tier == "blocker") is blocks, f"{value!r} -> {tier}"


@pytest.mark.parametrize("rel,blocks", [
    ("api/spec/config.py", True),           # an OpenAPI spec directory, not a test dir
    ("app/fixtures/prod_config.py", True),  # Django fixtures are production data
    ("services/e2e/settings.py", True),     # a service that happens to be called e2e
    ("frontend/cypress/support/env.js", True),
    ("src/latest/config.py", True),         # 'latest' contains 'test'
    ("tests/test_login.py", False),
    ("app/__tests__/helpers.js", False),
    ("src/login.test.ts", False),           # test-shaped FILE, wherever it lives
    ("conftest.py", False),
])
def test_review_f2_a_directory_name_may_not_downgrade_a_real_credential(
        tmp_path, rel, blocks):
    """A real key at `api/spec/config.py` was reported as "test material only".

    The test-material downgrade was written for login helpers in an auth test suite and
    reached far wider than that: `spec`, `specs`, `e2e`, `fixtures` and `cypress` all
    name production directories in ordinary repos, so a credential in one of them
    stopped gating the deploy. What is left is unambiguous, and a file whose own name is
    test-shaped counts wherever it lives.
    """
    root = _project(tmp_path, {rel: f'API_TOKEN_VALUE = "{FAKE_HIGH_ENTROPY}"\n'},
                    name=str(abs(hash(rel))))
    tier = _core(root)["core.secret-scan"].tier
    assert (tier == "blocker") is blocks, f"{rel} -> {tier}"


PEM = ("-----BEGIN RSA PRIVATE KEY-----\n"
       "MIIEowIBAAKCAQEA3Tz2mr7SZiAMfQyuvBjM9Oi8oL0kK1kZ4XxYqK8pDDdVYQmZ\n"
       "-----END RSA PRIVATE KEY-----\n")


@pytest.mark.parametrize("content,label", [
    (PEM, "private key block"),
    ("deploy_key = ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "GitHub token"),
    ("SLACK=xoxb-123456789012-abcdefghijklmnop", "Slack token"),
    ("stripe = sk_live_51H8xQ2eZvKYlo2CkKlmnopqrstu", "Stripe live key"),
    ("google = AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY", "Google API key"),
    ("registry = npm_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", "npm token"),
    ("gitlab = glpat-ABCdefGHIjklMNOpqrst", "GitLab personal access token"),
])
def test_review_f3_a_credential_is_detected_by_its_own_format(tmp_path, content, label):
    """Detection was entirely NAME-driven, with `AKIA…` the single exception.

    So a committed `id_rsa`, a `ghp_…` token or a `sk_live_…` key scanned clean unless
    the variable holding it happened to be called something helpful — which a credential
    pasted into a config file rarely is. These are published, prefixed formats: a match
    is a credential, not a heuristic, so it fires whatever the name and whatever the
    quoting.
    """
    root = _project(tmp_path, {"config/app.conf": content + "\n"}, name=str(abs(hash(label))))
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", f"{label} scanned clean"
    assert label in result.detail


@pytest.mark.parametrize("line", [
    "      - run: AWS_SECRET_ACCESS_KEY=%s ./deploy.sh" % FAKE_HIGH_ENTROPY,
    "  API_KEY: %s" % FAKE_HIGH_ENTROPY,
    "export GITHUB_TOKEN_VALUE=%s" % FAKE_HIGH_ENTROPY,
    "  password: %s" % FAKE_HIGH_ENTROPY,
])
def test_review_f4_an_unquoted_assignment_is_still_an_assignment(tmp_path, line):
    """The motivating case of item 4 was still missed: workflow values are unquoted.

    The first cut required an opening AND closing quote, so making `.github/workflows/`
    reachable achieved nothing for the shape that actually appears there — `run: KEY=…`
    — unless the value happened to be AKIA-shaped.
    """
    root = _project(tmp_path, {".github/workflows/deploy.yml": line + "\n"},
                    name=str(abs(hash(line))))
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", f"{line!r} scanned clean"


@pytest.mark.parametrize("line", [
    "  API_KEY: ${{ secrets.API_KEY }}",
    "  password: ${DB_PASSWORD}",
    "  api_key: !ENV APP_KEY",
    "      - run: export TOKEN_VALUE=$GITHUB_TOKEN",
    "  secret_name: my-app-secrets",
])
def test_review_f4_the_unquoted_arm_does_not_fire_on_references(tmp_path, line):
    """An unquoted value has no delimiter, so this arm has to be the stricter one:
    interpolations, references and kebab-case names must all stay quiet."""
    root = _project(tmp_path, {".github/workflows/deploy.yml": line + "\n"},
                    name=str(abs(hash(line))))
    result = _core(root)["core.secret-scan"]
    assert result.tier == "ok", f"{line!r} was reported:\n{result.detail}"


def test_review_f6_a_symlinked_file_is_still_read(tmp_path):
    """Not following symlinked DIRECTORIES is right; skipping symlinked FILES was not.

    A committed symlinked `.env` or config file is precisely what this suite is looking
    for, and master read them.
    """
    root = _project(tmp_path, {"src/app.py": "print('x')\n"})
    real = tmp_path / "real-config.py"
    real.write_text(f'API_TOKEN_VALUE = "{FAKE_HIGH_ENTROPY}"\n', encoding="utf-8")
    (root / "config.py").symlink_to(real)
    assert _core(root)["core.secret-scan"].tier == "blocker"


def test_review_f7_generated_bundles_do_not_produce_heuristic_findings(tmp_path):
    """A minified bundle is full of high-entropy identifiers and none is a credential.

    The name-and-entropy heuristic is switched off for machine-written files — but the
    published-format patterns keep running there, because a bundler can inline a key and
    `AKIA…` in a bundle is still `AKIA…`.
    """
    noisy = _project(tmp_path, {
        "static/app.min.js": f'var e={{apiKey:"{FAKE_HIGH_ENTROPY}"}};\n',
        "static/app.js.map": f'{{"sourcesContent":["api_key = \\"{FAKE_HIGH_ENTROPY}\\""]}}\n',
    }, name="noisy")
    assert _core(noisy)["core.secret-scan"].tier == "ok"

    inlined = _project(tmp_path, {"static/app.min.js": f'var k="AKIA{"B" * 16}";\n'},
                       name="inlined")
    assert _core(inlined)["core.secret-scan"].tier == "blocker", (
        "a published credential format was skipped because the file was minified")


# ── item 4: dot-directories were skipped entirely ──────────────────────────

@pytest.mark.parametrize("rel", [
    ".github/workflows/deploy.yml",
    ".gitlab-ci.d/deploy.yml",
    ".circleci/config.yml",
    ".devcontainer/devcontainer.json",
    ".aws/credentials",
    ".config/app/settings.py",
])
def test_issue_d010_4_a_key_in_a_dot_directory_is_found(tmp_path, rel):
    """`.github/workflows/deploy.yml` is a classic place to leak one, and it was
    unreachable: `_iter_files` skipped every directory whose name started with a dot."""
    root = _project(tmp_path, {rel: f"aws_key: AKIA{'A' * 16}\n"})
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", f"{rel} scanned clean"
    assert rel in result.detail


def test_issue_d010_4_generated_dot_directories_are_still_skipped(tmp_path):
    """A skip-list, not an allow-list — but the noisy ones still have to be skipped, or
    the scan reads a `.next/` build tree and reports its bundled fixtures."""
    root = _project(tmp_path, {
        ".next/static/chunk.js": f'const secret_value = "{FAKE_HIGH_ENTROPY}";\n',
        ".venv/lib/site.py": f'api_key = "{FAKE_HIGH_ENTROPY}"\n',
        ".git/config": f"token = {FAKE_HIGH_ENTROPY}\n",
        "src/app.py": "print('hello')\n",
    })
    assert _core(root)["core.secret-scan"].tier == "ok", (
        _core(root)["core.secret-scan"].detail)


def test_issue_d010_4_a_symlinked_directory_is_not_followed(tmp_path):
    """Descending into dot-dirs means descending into more links. A link out of the
    tree is not the project's source, and a link back into it is a loop."""
    root = _project(tmp_path, {"src/app.py": "print('hello')\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text(f'api_key = "{FAKE_HIGH_ENTROPY}"\n', encoding="utf-8")
    (root / ".linked").symlink_to(outside, target_is_directory=True)
    (root / "loop").symlink_to(root, target_is_directory=True)
    assert _core(root)["core.secret-scan"].tier == "ok"


# ── item 6: root-only manifest discovery ───────────────────────────────────

def test_issue_d010_6_a_nested_manifest_without_a_lockfile_is_found(tmp_path):
    """Every repo in the fleet nests, so this check was vacuously `ok` on all of them.

    `frontend/package.json` with no lockfile anywhere is exactly the shape the check was
    written for, and exactly the shape it could not see.
    """
    root = _project(tmp_path, {
        "frontend/package.json": '{"name": "web"}\n',
        "backend/pyproject.toml": '[project]\nname = "api"\n',
        "README.md": "# app\n",
    })
    result = _core(root)["core.lockfile"]
    assert result.tier == "warning", "a nested manifest with no lockfile scanned clean"
    assert "frontend/package.json" in result.detail
    assert "backend/pyproject.toml" in result.detail


def test_issue_d010_6_a_workspace_lockfile_above_the_manifest_counts(tmp_path):
    """npm/pnpm/yarn workspaces put ONE lockfile at the workspace root and none beside
    the member packages. Requiring a sibling lock would report every well-run monorepo
    as unlocked, which is how a check earns its way into being ignored."""
    root = _project(tmp_path, {
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
        "packages/server/package.json": '{"name": "server"}\n',
        "packages/web/package.json": '{"name": "web"}\n',
    })
    assert _core(root)["core.lockfile"].tier == "ok"


def test_issue_d010_6_discovery_is_depth_bounded(tmp_path):
    """Unbounded discovery walks a whole monorepo and reports vendored trees.

    Four levels reaches `apps/web/frontend/package.json` and
    `services/api/internal/package.json` — both ordinary shapes, and the reason the
    review raised this from three — and stops before a vendored dependency tree.
    """
    reachable = "services/api/internal/worker/package.json"
    root = _project(tmp_path, {reachable: '{"name": "worker"}\n'}, name="reachable")
    assert _core(root)["core.lockfile"].tier == "warning", (
        f"{reachable} is an ordinary monorepo shape and must be in scope")

    deep = "a/b/c/d/e/package.json"
    buried = _project(tmp_path, {deep: '{"name": "buried"}\n'}, name="buried")
    assert _core(buried)["core.lockfile"].tier == "ok", (
        f"{deep} is {deep.count('/')} directories down and should be out of scope")
    assert fallbacks._MANIFEST_MAX_DEPTH == 4


def test_issue_d010_6_gitignore_sees_a_nested_node_project(tmp_path):
    """Same root cause, second check: a repo whose only package.json is nested is still
    a node project, and its node_modules still must not enter the repo."""
    root = _project(tmp_path, {
        "frontend/package.json": '{"name": "web"}\n',
        "frontend/package-lock.json": "{}\n",
        ".gitignore": "*.pyc\n",
    })
    result = _core(root)["core.gitignore"]
    assert result.tier == "warning" and "node_modules" in result.detail


# ── item 7: exposure-auth was satisfied by a cookie setting ────────────────

def test_issue_d010_7_a_session_cookie_setting_is_not_authentication(tmp_path):
    """`SESSION_COOKIE_SECURE = True` used to satisfy this check, because the pattern
    matched the bare substring `session`.

    The consequence was total: every project that passed `django.security-settings`
    passed `core.exposure-auth` for free, whatever its actual authentication — which is
    to say the check reported on the presence of one hardening setting and called it
    authentication.
    """
    root = _project(tmp_path, {"settings.py": (
        "SESSION_COOKIE_SECURE = True\n"
        "SESSION_COOKIE_HTTPONLY = True\n"
        "CSRF_COOKIE_SECURE = True\n")})
    assert _core(root)["core.exposure-auth"].tier == "warning", (
        "a session-cookie setting still counts as authentication")


@pytest.mark.parametrize("source", [
    "from django.contrib.auth.decorators import login_required\n@login_required\ndef v(r): ...",
    "if request.user.is_authenticated:\n    pass",
    "permission_classes = [IsAuthenticated]",
    "app.use(passport.authenticate('jwt'))",
    "const token = jwt.verify(raw, SECRET)",
    "export async function GET() { const s = await getServerSession(); }",
    "def login(request):\n    return None",
])
def test_issue_d010_7_real_authentication_still_registers(tmp_path, source):
    """The tightening is only worth having if it still recognises the real thing."""
    root = _project(tmp_path, {"app.py": source + "\n"}, name=str(abs(hash(source))))
    assert _core(root)["core.exposure-auth"].tier == "ok", source


def test_issue_d010_7_vocabulary_outside_source_is_not_evidence(tmp_path):
    """A hit in a lockfile or a .gitignore is vocabulary, not an auth decision."""
    root = _project(tmp_path, {
        "package-lock.json": '{"packages": {"node_modules/jsonwebtoken": {}}}\n',
        ".gitignore": "sessions/\n",
        "notes.md": "we should add login one day\n",
    })
    assert _core(root)["core.exposure-auth"].tier == "warning"


# ── item 1: supersession must be declared ──────────────────────────────────

class _GreedyModule:
    name = "greedy-test-module"

    def detect(self, root):
        return True

    def checks(self, root):
        return [core.CheckResult(id="core.secret-scan", tier="ok",
                                 title="nothing to see here")]

    def sandbox_checks(self, root):
        return []

    def wizard_questions(self, root):
        return []

    def manifest_fragment(self, root, answers=None):
        return {}


class _DeclaredModule(_GreedyModule):
    name = "declared-test-module"
    supersedes = frozenset({"core.secret-scan"})


@pytest.fixture
def registry_sandbox():
    """Register modules for one test and put the real registry back afterwards."""
    frameworks, fallback_mods = core.registered_modules()
    yield
    core._FRAMEWORK_MODULES[:] = frameworks
    core._FALLBACK_MODULES[:] = fallback_mods


def test_issue_d010_1_undeclared_supersession_of_a_core_check_raises(
        tmp_path, registry_sandbox):
    """A module could turn `core.secret-scan` from blocker to `ok` in a check body.

    Same-id supersession is the designed mechanism and it is also the way to weaken a
    blocker silently: the registry invariant checks presence and uniqueness, not tier,
    and the replaced result leaves no trace in the report. Declaring it does not stop a
    determined author — it makes the attempt a one-line edit in the diff, on a path that
    is now human-merge-only, instead of a change of tier buried in a check body.
    """
    core._FRAMEWORK_MODULES[:] = [_GreedyModule()]
    root = _project(tmp_path, {"c.py": f'SECRET_KEY = "{FAKE_HIGH_ENTROPY}"\n'})
    with pytest.raises(ValueError, match="without declaring it"):
        core.scan(root)


def test_issue_d010_1_declared_supersession_still_works(tmp_path, registry_sandbox):
    """The mechanism itself is legitimate — node-ts re-deriving `core.lockfile` is the
    precedent, and it is the only way to say "this check does not apply here"."""
    core._FRAMEWORK_MODULES[:] = [_DeclaredModule()]
    root = _project(tmp_path, {"c.py": f'SECRET_KEY = "{FAKE_HIGH_ENTROPY}"\n'})
    checks = {c["id"]: c for c in core.scan(root)["checks"]}
    assert checks["core.secret-scan"]["tier"] == "ok"
    assert checks["core.secret-scan"]["title"] == "nothing to see here"


def test_issue_d010_1_the_declared_supersessions_are_frozen():
    """The union across the live registry, pinned. Adding one is a deliberate edit here
    as well as in the module — and `scanner/modules/**` is on the sensitive-path
    human-merge list precisely so a person sees it."""
    frameworks, fallback_mods = core.registered_modules()
    declared = {m.name: sorted(core.module_supersedes(m))
                for m in frameworks + fallback_mods}
    assert declared == {
        "django": [],
        "node-ts": ["core.lockfile"],
        "dockerfile": [],
        "static": [],
    }, ("a module's declared supersessions changed. A supersession replaces a core "
        f"result outright, tier included: {declared}")

    paths = (REPO / "conformance" / "paths.yaml").read_text(encoding="utf-8")
    assert "scanner/modules/**" in paths, (
        "scanner/modules/ left the sensitive-path list while modules can still "
        "supersede a blocker-tier core check")


# ── item 8: duplicate module names ─────────────────────────────────────────

def test_issue_d010_8_a_duplicate_module_name_is_refused(registry_sandbox):
    """Module names key the report, the registry invariant's per-module row and the
    demo records. The invariant's fixture map dedupes by name, so a second module
    sharing one was checked by nothing."""
    first, second = _GreedyModule(), _DeclaredModule()
    second.name = first.name
    core.register(first)
    with pytest.raises(ValueError, match="already registered"):
        core.register(second)


def test_issue_d010_8_the_live_registry_has_no_duplicates():
    frameworks, fallback_mods = core.registered_modules()
    names = [m.name for m in frameworks + fallback_mods]
    assert len(names) == len(set(names)), names


# ── the whole point, end to end ────────────────────────────────────────────

def test_a_django_repo_with_a_key_in_github_workflows_is_a_blocker(tmp_path):
    """The composite of items 3 and 4, on the shape that motivated the list.

    A Django project — the fleet's dominant framework — with an AWS secret access key
    committed to `.github/workflows/deploy.yml`. Before D-010 the Django module emitted
    no `core.*` checks at all; after it, this file was still unreachable and the
    assignment shape still unmatched. Now it is a blocker.
    """
    root = _project(tmp_path, {
        "manage.py": "import django\n",
        "config/settings.py": 'SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]\n',
        ".github/workflows/deploy.yml": (
            "jobs:\n  deploy:\n    steps:\n"
            f'      - run: AWS_SECRET_ACCESS_KEY="{FAKE_AWS_SECRET}" ./deploy.sh\n'),
    })
    report = core.scan(root)
    checks = {c["id"]: c for c in report["checks"]}
    assert checks["core.secret-scan"]["tier"] == "blocker", report["summary"]
    assert ".github/workflows/deploy.yml" in checks["core.secret-scan"]["detail"]
    assert report["summary"]["blocker"] >= 1

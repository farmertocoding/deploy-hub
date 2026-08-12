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


def test_review2_the_openai_pattern_does_not_match_a_css_class(tmp_path):
    """`sk-[A-Za-z0-9_-]{32,}` matched every kebab-case class name of that length.

    SpinKit's `.sk-chase-dot-…` ships in `public/vendor/` on a great many sites, and
    axis 1 runs inside generated files by design — so a constructed Next.js tree
    scanned as a blocker with two findings, both from one stylesheet and neither a
    credential. The body may not contain `-` now; project keys keep the wider alphabet
    but must carry the `sk-proj-` prefix and 64+ characters.
    """
    css = _project(tmp_path, {"public/vendor/spinkit.min.css": (
        ".sk-chase-dot-before-animation-delay-frames-x{animation-delay:-1.1s}\n"
        ".sk-circle-fade-dot-before-animation-delay-frames{opacity:0}\n")}, name="css")
    assert _core(css)["core.secret-scan"].tier == "ok", _core(css)["core.secret-scan"].detail

    for key in ("sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6",
                # a real project key is ~150 chars of base64url
                "sk-proj-" + "aB3-dE6_gH9jK2mN5pQ8rS1tU4vW7xY0zA3bC6dE9fG2hJ5kL8mN1pQ4rS7t"
                + "uV0wX3yZ6aB9cD2eF5gH8iJ1kL4mN7oP0qR3sT6uV9wX2yZ5"):
        tree = _project(tmp_path, {"conf.py": f'k = "{key}"\n'}, name=key[:12])
        assert _core(tree)["core.secret-scan"].tier == "blocker", key


def test_review2_a_connection_string_is_caught_whatever_it_is_called(tmp_path):
    """`DATABASE_URL = "postgres://user:pass@host"` is the commonest committed database
    credential there is, and the name carries no keyword — so the name-driven axis never
    saw it, while `DB_SECRET = <same value>` blocked. It is a value format now."""
    root = _project(tmp_path, {"settings.py": (
        'DATABASE_URL = "postgres://app:Pr0dPassw0rd99@db.internal:5432/app"\n')})
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker"
    assert "connection string" in result.detail and "[proof]" in result.detail

    # A placeholder password, a short one, and a credential-free URL stay quiet.
    for value in ("postgres://app:changeme@localhost:5432/app",
                  "postgres://app:pw@localhost:5432/app",
                  "postgres://app@localhost:5432/app",
                  "https://example.com/health"):
        quiet = _project(tmp_path, {"s.py": f'DATABASE_URL = "{value}"\n'},
                         name=str(abs(hash(value))))
        assert _core(quiet)["core.secret-scan"].tier == "ok", value


def test_review2_a_docker_registry_auth_blob_is_decoded(tmp_path):
    """`"auth": "<base64>"` in a docker config is `user:password`, and `auth` is not a
    secret keyword. Decoding is what separates it from any other base64 blob."""
    import base64 as b64
    real = b64.b64encode(b"deployer:Pr0dRegistryPassw0rd").decode()
    root = _project(tmp_path, {".docker/config.json": (
        '{"auths": {"registry.example.com": {"auth": "%s"}}}\n' % real)})
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker" and "docker registry auth" in result.detail

    # A base64 blob under `auth` that is not user:password is not this finding.
    other = b64.b64encode(b"just-some-opaque-token-value").decode()
    quiet = _project(tmp_path, {"c.json": '{"auth": "%s"}\n' % other}, name="quiet")
    assert _core(quiet)["core.secret-scan"].tier == "ok"


def test_review2_findings_say_which_are_proof_and_which_are_guesses(tmp_path):
    """The report mixes a matched credential format with a name-and-entropy guess, and
    a reader who cannot tell them apart will discount both equally.

    The security review's own framing: axis 1 is proof, axis 2 is a heuristic, and
    presenting them identically overstates the second.
    """
    root = _project(tmp_path, {
        "a.py": "deploy_key = ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8" + "\n",
        "b.py": f'API_TOKEN_VALUE = "{FAKE_HIGH_ENTROPY}"\n'})
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker"
    assert "[proof] GitHub token" in result.detail
    assert "[heuristic] hardcoded api_token_value value" in result.detail
    assert "[proof]" in result.fix_hint and "[heuristic]" in result.fix_hint, (
        "the labels appear in the findings but nothing tells the reader what they mean")


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



# ── N6: generated output echoed its own source into the report ──────────────
#
# Raised by the R4-10 demo record (2026-08-11) as follow-up 1, from the D-011r noise
# measurement. hr-saas-starter reported a `[heuristic]` finding at
# `frontend/coverage/lcov-report/src/auth.ts.html` — istanbul's HTML rendering of the
# very source line reported one entry above it. One underlying literal, counted twice,
# the second copy in a directory no human has ever reviewed.
#
# THE FIRST CUT OF THIS FIX WAS WRONG, and how it was wrong is the reason these tests
# are shaped as they are. It added the directory names to `_SKIP_DIRS`, which prunes
# the WALK. An adversarial pass that wrote none of it found that this had reproduced
# round-6b's mistake one layer down:
#
#   * `.vercel/.env.production.local` — the file `vercel env pull` writes, holding the
#     live production environment — stopped being reported at all;
#   * `core.gitignore` reads the same walk, so one prune silently cost two checks;
#   * bundlers INLINE `process.env.*`, so a key can live in the artifact and in an
#     ignored `.env` and nowhere in source: "generated output only echoes scanned
#     source" is false for exactly the trees being pruned;
#   * seven of the eleven added names were asserted by no test at all — deleting them
#     left the whole suite green.
#
# The fix is scoped to the AXIS instead. The heuristic axis does not run over generated
# trees; the `[proof]` axis and the `.env` handler still do. That removes the measured
# noise (which was `[heuristic]`) at zero cost in misses.

_N6_TREE = "frontend/coverage/lcov-report/src/auth.ts.html"


def test_n6_coverage_html_no_longer_echoes_its_own_source_line(tmp_path):
    """The measured case: the literal is reported once, from the source file."""
    root = _project(tmp_path, {
        "frontend/src/auth.ts": f'const password = "{FAKE_HIGH_ENTROPY}";\n',
        "frontend/coverage/lcov.info": "TN:\nSF:src/auth.ts\nend_of_record\n",
        _N6_TREE: f'<span>const password = "{FAKE_HIGH_ENTROPY}";</span>\n',
    })
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", "the real source finding must survive"
    lines = [ln for ln in result.detail.splitlines() if ln.strip()]
    assert lines == ["frontend/src/auth.ts:1: [heuristic] hardcoded password value"], \
        result.detail


@pytest.mark.parametrize("name", sorted(fallbacks._GENERATED_DIRS))
def test_n6_every_generated_dir_name_suppresses_the_heuristic_axis(tmp_path, name):
    """Parametrized off the constant itself, so an entry cannot be added without a
    test — seven of the first cut's eleven names were asserted by nothing."""
    root = _project(tmp_path, {
        f"{name}/bundle.js": f'const api_key = "{FAKE_HIGH_ENTROPY}";\n',
        "src/app.py": "print('hello')\n",
    })
    assert _core(root)["core.secret-scan"].tier == "ok", \
        _core(root)["core.secret-scan"].detail


@pytest.mark.parametrize("name", sorted(fallbacks._GENERATED_DIRS))
def test_n6_a_proof_tier_credential_in_generated_output_still_blocks(tmp_path, name):
    """The correction to the first cut, and the property that makes this safe: a
    bundler inlines `process.env.STRIPE_KEY` at build time, so the key exists in the
    artifact and in an ignored `.env` and NOWHERE in source. Pruning the walk missed
    it. Suppressing only the heuristic axis does not."""
    root = _project(tmp_path, {
        f"{name}/bundle.js": f"const k = 'AKIA{'A' * 16}';\n",
        "src/app.py": "print('hello')\n",
    })
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", f"{name} hid a published credential format"
    assert "[proof]" in result.detail


@pytest.mark.parametrize("name", sorted(fallbacks._GENERATED_DIRS | {"coverage"}))
def test_n6_a_committed_env_file_in_generated_output_still_blocks(tmp_path, name):
    """`vercel env pull` writes the live production environment into its own state
    directory, which is gitignored everywhere precisely BECAUSE it holds credentials —
    so the repos where it IS committed are exactly the ones this blocker exists for.
    The first cut reported nothing for this tree."""
    root = _project(tmp_path, {
        f"{name}/.env.production.local":
            "DATABASE_URL=postgres://acme:s3cret-but-real@db/app\n",
        f"{name}/lcov.info": "TN:\n",
        "src/app.py": "print('hello')\n",
    })
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", f"{name} hid an .env file"
    # N7 reworded this line: the scan reads a tree and cannot see git, so it reports
    # presence rather than asserting the file is committed.
    assert ".env file present in the scan tree" in result.detail


def test_n6_a_coverage_app_holding_real_source_is_still_scanned(tmp_path):
    """The over-correction guard, and the round-6b lesson stated as a test: `coverage`
    is an ordinary English word. An insurance product has `apps/coverage/` and it holds
    source. Classifying it by name would be exactly the `spec`/`fixtures`/`e2e`
    mistake."""
    root = _project(tmp_path, {
        "apps/coverage/__init__.py": "",
        "apps/coverage/models.py": "from django.db import models\n",
        "apps/coverage/client.py": f'API_KEY = "{FAKE_HIGH_ENTROPY}"\n',
    })
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", "a real app named coverage must still be scanned"
    assert "apps/coverage/client.py" in result.detail


def test_n6_coverage_needs_a_generator_fingerprint(tmp_path):
    """Jest's html reporter writes straight into `coverage/` with no `lcov-report/`
    below it, so a name-only rule would miss this shape. The marker is the evidence
    that a generator, not a person, made the directory."""
    root = _project(tmp_path, {
        "coverage/coverage-final.json": '{"a":1}\n',
        "coverage/index.html": f'<code>token = "{FAKE_HIGH_ENTROPY}"</code>\n',
        "src/app.py": "print('hello')\n",
    })
    assert _core(root)["core.secret-scan"].tier == "ok", \
        _core(root)["core.secret-scan"].detail


@pytest.mark.parametrize("kind", ["empty-file", "directory", "symlink", "wrong-case"])
def test_n6_a_forged_marker_does_not_silence_a_source_directory(tmp_path, kind):
    """`exists()` accepted all of these. An empty `touch coverage/lcov.info` is
    invisible in a diff and would have switched a blocker off; a `lcov.info/` DIRECTORY
    is a plausible accident; and `exists()` is case-insensitive on macOS and
    case-sensitive on the Linux runner, so `LCOV.INFO` classified differently depending
    on whose machine ran the gate — a gate result that depends on the OS is not a gate
    result. Case is now normalized on both sides, so all four platforms agree."""
    root = _project(tmp_path, {
        "apps/coverage/client.py": f'API_KEY = "{FAKE_HIGH_ENTROPY}"\n',
    })
    target = root / "apps" / "coverage"
    if kind == "empty-file":
        (target / "lcov.info").write_text("", encoding="utf-8")
    elif kind == "directory":
        (target / "lcov.info").mkdir()
    elif kind == "symlink":
        (target / "lcov.info").symlink_to("/etc/hostname")
    else:
        (target / "LCOV.INFO").write_text("TN:\n", encoding="utf-8")
    result = _core(root)["core.secret-scan"]
    if kind == "wrong-case":
        # Normalized: an uppercase marker is a marker, on every platform.
        assert result.tier == "ok", result.detail
    else:
        assert result.tier == "blocker", f"a {kind} marker silenced real source"
        assert "apps/coverage/client.py" in result.detail


def test_n6_the_generated_dir_set_is_frozen():
    """Parametrizing the tests above off the constant means an ADDED name always gets
    a test — but a DELETED name silently deletes its own coverage, which is the same
    hole in a new shape (the mutation `drop .output` left the N6 suite green until
    this test existed). Freezing the set the way round-6b froze the `supersedes` union
    makes both directions a deliberate, reviewed act."""
    assert fallbacks._GENERATED_DIRS == {
        "htmlcov", "lcov-report", ".nyc_output", "storybook-static",
        ".output", ".angular", ".astro", ".docusaurus", ".eggs",
    }
    assert set(fallbacks._GENERATED_IF_MARKED) == {"coverage"}


def test_n6_generated_dirs_and_skip_dirs_stay_disjoint():
    """The two mechanisms mean opposite things — `_SKIP_DIRS` is never read at all,
    `_GENERATED_DIRS` is read with one axis off. A name in both is a bug: the walk
    prune wins and the axis distinction silently stops applying."""
    assert not (fallbacks._GENERATED_DIRS & fallbacks._SKIP_DIRS)
    assert not (set(fallbacks._GENERATED_IF_MARKED) & fallbacks._SKIP_DIRS)
    # `.vercel`/`.netlify` are CLI state directories holding real credentials, not
    # build output. They were on the first cut's list. They belong on neither.
    for tool_state in (".vercel", ".netlify"):
        assert tool_state not in fallbacks._GENERATED_DIRS
        assert tool_state not in fallbacks._SKIP_DIRS


# ── R7-2 (round 7): a subtree the walk cannot open is silently dropped ─────────
#
# `_iter_files` swallowed `OSError` with `continue` and `_read_text` returned `None`, so
# a permission-denied directory — or one that vanished mid-walk — was skipped with no
# problem line, no warning and no tier change. A security gate must degrade to an honest
# error, never to `ok`.
#
# The denial is injected rather than made with `chmod`, for the plain reason that this
# suite runs as root on the CI image and root reads a 0o000 directory happily. What is
# under test is the walk's reaction to `OSError`, and that is what is provoked.

def _deny(monkeypatch, denied, method="iterdir"):
    """Make `Path.<method>` raise PermissionError for exactly the paths in `denied`."""
    real = getattr(pathlib.Path, method)
    denied = {pathlib.Path(p).resolve() for p in denied}

    def guarded(self, *args, **kwargs):
        try:
            here = self.resolve()
        except OSError:                        # pragma: no cover - defensive
            here = self
        if here in denied:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, method, guarded)


def test_issue_r7_2_an_unreadable_directory_never_reports_ok(monkeypatch, tmp_path):
    """The demonstrated case, and it is the whole finding: the same tree reports
    `blocker` when the walk can open `prodcfg/` and reported `tier: ok`, "No committed
    secrets found", empty detail when it could not. A check that answers "clean" about a
    subtree it never opened is worse than one that crashes."""
    root = _project(tmp_path, {
        "prodcfg/creds.py": f'aws_secret_access_key = "{FAKE_AWS_SECRET}"\n',
        "app.py": "print('hello')\n",
    })
    assert _core(root)["core.secret-scan"].tier == "blocker"

    _deny(monkeypatch, [root / "prodcfg"])
    result = _core(root)["core.secret-scan"]
    assert result.tier == "warning", result.detail
    assert "prodcfg" in result.detail
    assert "incomplete" in result.detail.lower() or "incomplete" in result.title.lower()


def test_issue_r7_2_a_skipped_path_rides_the_detail_of_a_real_finding(
        monkeypatch, tmp_path):
    """When something WAS found the tier is already right, and the skip list still has to
    travel: "we found two things and could not look in three places" is a different
    report from "we found two things"."""
    root = _project(tmp_path, {
        "prodcfg/creds.py": f'aws_secret_access_key = "{FAKE_AWS_SECRET}"\n',
        "other/keys.py": f'api_key = "{FAKE_HIGH_ENTROPY}"\n',
    })
    _deny(monkeypatch, [root / "prodcfg"])
    result = _core(root)["core.secret-scan"]
    assert result.tier == "blocker", result.detail
    assert "other/keys.py:1: [heuristic] hardcoded api_key value" in result.detail
    assert "prodcfg" in result.detail


def test_issue_r7_2_an_unreadable_file_counts_too(monkeypatch, tmp_path):
    """THE RULING, stated in the code and pinned here: what joins the skip list is not
    "a directory" but "the filesystem refused". An unreadable FILE is the same blindness
    one level down — the scanner knows a file is there and cannot see a byte of it — so
    it rides the same list. What does NOT join it is a file the scanner DECLINED to read
    (binary, oversized): those are policy, they are bounded, and the scanner knows
    exactly what it passed over and why."""
    root = _project(tmp_path, {
        "prodcfg/creds.py": f'aws_secret_access_key = "{FAKE_AWS_SECRET}"\n',
        "app.py": "print('hello')\n",
    })
    _deny(monkeypatch, [root / "prodcfg" / "creds.py"], method="read_bytes")
    result = _core(root)["core.secret-scan"]
    assert result.tier == "warning", result.detail
    assert "prodcfg/creds.py" in result.detail


@pytest.mark.parametrize("kind", ["binary", "oversized"])
def test_issue_r7_2_a_file_the_scanner_declined_to_read_does_not_warn(tmp_path, kind):
    """The over-correction guard the spec names. A repo with a genuinely binary file —
    every repo — must not start reporting `warning` on a check that exists to find
    secrets. This is the direction the fix must not fail in: a warning that fires on
    every repo is a warning nobody reads, and the next reviewer deletes it."""
    root = _project(tmp_path, {"app.py": "print('hello')\n"})
    if kind == "binary":
        (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00")
    else:
        (root / "big.txt").write_bytes(b"a" * (fallbacks._MAX_TEXT_BYTES + 1))
    result = _core(root)["core.secret-scan"]
    assert result.tier == "ok", result.detail
    assert result.detail == ""


def test_issue_r7_2_the_skipped_list_is_capped_and_counted(monkeypatch, tmp_path):
    """A repo can make the unreadable set as large as it likes, and an error message
    that is 3000 lines long is the same wall of text `MAX_REASON_CHARS` exists to stop.
    The cap keeps the count — which is the number the reader needs — and drops the tail.

    ASSERTED WITH LITERALS, and the first cut of this test is why it is worth saying.
    It bounded the printed lines with `<= fallbacks._MAX_SKIPPED_REPORTED + 1`, derived
    from the constant under test — so raising the cap to 10**9 printed all 40 paths and
    the test still passed, because its own expectation had moved with the mutation. An
    assertion that tracks the thing it is measuring measures nothing (R4-11's class,
    found by the quality reviewer's mutation sweep on this branch)."""
    files = {f"deny{i}/x.py": "print(1)\n" for i in range(40)}
    root = _project(tmp_path, files)
    _deny(monkeypatch, [root / f"deny{i}" for i in range(40)])
    result = _core(root)["core.secret-scan"]
    assert result.tier == "warning", result.detail
    assert "40 paths" in result.detail, result.detail
    named = [ln for ln in result.detail.splitlines() if ln.startswith("deny")]
    assert len(named) == 10, named
    assert "… and 30 more" in result.detail, result.detail


def test_issue_r7_2_the_walk_still_serves_every_other_check(monkeypatch, tmp_path):
    """Blast radius. `_iter_files` is shared by `core.lockfile`, `core.gitignore` and
    `core.tests-exist`; the skip list had to reach one caller without changing the shape
    of any of the others. The suite is the same seven checks, and the ones that do not
    ask about skipping are unmoved by it."""
    files = {"package.json": '{"name": "app"}\n', "package-lock.json": "{}\n",
             ".gitignore": ".env\nnode_modules\n", "tests/test_app.py": "def test(): pass\n",
             "deny/x.py": "print(1)\n"}
    root = _project(tmp_path, files)
    before = _core(root)
    _deny(monkeypatch, [root / "deny"])
    after = _core(root)
    assert set(before) == set(after)
    for check_id in set(before) - {"core.secret-scan"}:
        assert before[check_id].as_dict() == after[check_id].as_dict(), check_id

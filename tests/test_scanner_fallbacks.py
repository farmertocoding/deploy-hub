"""Fallback modules + common-core checks (review3 §V4; scanner/modules/fallbacks.py)."""
import pathlib
import shutil

import pytest

from scanner import core
from scanner.modules import fallbacks

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "fallbacks"
DJANGO_MODULE_SRC = REPO / "scanner" / "modules" / "django.py"


def by_id(results, check_id):
    matches = [r for r in results if r.id == check_id]
    assert len(matches) == 1, f"{check_id} appeared {len(matches)} times"
    return matches[0]


def _scan_results(root):
    """Report-level results as CheckResult-shaped objects, so `by_id` reads the same
    whether the caller is asking a module or a whole scan."""
    return [core.CheckResult(**c) for c in core.scan(root)["checks"]]


def secret_tree(tmp_path):
    """The committed-.env tree. Repo .gitignore ignores `.env` everywhere, so the
    offending file is materialized at test time instead of shipped in the fixture."""
    tree = tmp_path / "secret_tree"
    shutil.copytree(FIXTURES / "secret_tree", tree)
    (tree / ".env").write_text("FAKE_SECRET=abcdef1234567890abcdef\n")
    return tree


# ── dockerfile fallback module ──────────────────────────────────────────────────

def test_dockerfile_detects_and_fires_its_three_warnings():
    project = FIXTURES / "dockerfile_project"
    mod = fallbacks.dockerfile_module
    assert mod.detect(project)
    results = mod.checks(project)
    assert by_id(results, "dockerfile.expose").tier == "warning"
    assert by_id(results, "dockerfile.non-root").tier == "warning"
    assert by_id(results, "dockerfile.latest-tag").tier == "warning"
    # :latest is also unpinned — the common core flags the digest gap too (§6.8).
    # Report-level: the core suite is composed by core.scan, not by the module (D-010).
    assert by_id(_scan_results(project), "core.digest-pins").tier == "warning"
    # §M1: image build is pipeline step 1 — the scan emits NO build spec.
    assert mod.sandbox_checks(project) == []


def test_dockerfile_manifest_takes_port_from_expose(tmp_path):
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12-slim@sha256:0000000000000000000000000000000000000000"
        "000000000000000000000000\nEXPOSE 8080\nUSER app\nCMD [\"app\"]\n")
    mod = fallbacks.dockerfile_module
    frag = mod.manifest_fragment(tmp_path, answers=None)
    assert frag["components"]["service"] == {"kind": "dockerfile", "port": 8080}
    assert "dockerfile.port" not in {q.id for q in mod.wizard_questions(tmp_path)}
    results = mod.checks(tmp_path)
    assert by_id(results, "dockerfile.expose").tier == "ok"
    assert by_id(results, "dockerfile.non-root").tier == "ok"
    assert by_id(results, "dockerfile.latest-tag").tier == "ok"
    assert by_id(_scan_results(tmp_path), "core.digest-pins").tier == "ok"


def test_dockerfile_without_expose_asks_the_port():
    project = FIXTURES / "dockerfile_project"
    mod = fallbacks.dockerfile_module
    frag = mod.manifest_fragment(project, answers=None)
    assert frag["components"]["service"] == {"kind": "dockerfile", "port": None}
    question_ids = {q.id for q in mod.wizard_questions(project)}
    assert {"dockerfile.domain", "dockerfile.exposure",
            "dockerfile.port", "dockerfile.env"} <= question_ids


# ── static fallback module ──────────────────────────────────────────────────────

def test_static_detects_root_index_and_emits_static_route():
    site = FIXTURES / "static_site"
    mod = fallbacks.static_module
    assert mod.detect(site)
    frag = mod.manifest_fragment(site, answers=None)
    assert frag["components"]["static_route"] == {"dir": "."}
    assert mod.sandbox_checks(site) == []


def test_static_detects_dist_index(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>\n")
    mod = fallbacks.static_module
    assert mod.detect(tmp_path)
    frag = mod.manifest_fragment(tmp_path, answers=None)
    assert frag["components"]["static_route"] == {"dir": "dist"}


def test_static_does_not_match_when_server_manifests_exist(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>\n")
    (tmp_path / "manage.py").write_text("import sys\n")
    assert not fallbacks.static_module.detect(tmp_path)
    # A Dockerfile is a server manifest too — that tree belongs to `dockerfile`.
    assert not fallbacks.static_module.detect(FIXTURES / "dockerfile_project")


# ── common core: secret scan ────────────────────────────────────────────────────

def test_an_env_file_in_the_scan_tree_is_a_blocker(tmp_path):
    # N7 reworded the evidence line: the scanner reads a tree, not git, so it reports
    # the file's presence and leaves "is it committed?" to the reader (see
    # test_n7_the_env_finding_does_not_claim_the_file_is_committed).
    tree = secret_tree(tmp_path)
    res = by_id(fallbacks.common_checks(tree), "core.secret-scan")
    assert res.tier == "blocker"
    assert ".env: .env file present in the scan tree" in res.detail
    assert "example" not in res.detail  # .env.example must NOT be flagged


def test_env_example_alone_is_clean():
    res = by_id(fallbacks.common_checks(FIXTURES / "secret_tree"), "core.secret-scan")
    assert res.tier == "ok"


def test_high_entropy_assignment_is_a_blocker_with_file_and_line(tmp_path):
    (tmp_path / "settings.py").write_text(
        "DEBUG = False\nAPI_KEY = \"9fj39fJ2kd93jdkQpz81\"\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.secret-scan")
    assert res.tier == "blocker"
    assert "settings.py:2" in res.detail


def test_aws_key_pattern_is_a_blocker(tmp_path):
    (tmp_path / "deploy.cfg").write_text("key = AKIAABCDEFGHIJKLMNOP\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.secret-scan")
    assert res.tier == "blocker"
    assert "deploy.cfg:1" in res.detail


def test_placeholder_values_are_not_flagged(tmp_path):
    (tmp_path / "settings.py").write_text(
        "SECRET_KEY = \"changeme-changeme-changeme\"\n"
        "TOKEN = \"example_example_example\"\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.secret-scan")
    assert res.tier == "ok"


# ── N7: three false-positive classes the TAKKO scan found (2026-08-11) ──────────
#
# The TAKKO scan — a Django + Vite monorepo, the first real repo with a modern frontend
# in-tree — produced 16 blocking `[heuristic]` lines and 3 "committed .env" lines, and
# triage found NOT ONE of the 16 was a secret. Three classes, none of them predictable
# from a fixture, all of them ordinary in the shape of repo the fleet is moving toward.
#
# Each fix here carries an over-correction guard, because a noise-reduction that quietly
# narrows a security check is the failure mode that costs the most: nobody notices a
# blocker that stopped blocking (the N6 lesson, restated).

_N7_RANDOM = "kQ7pZ2mX9vB4nT6yR1wL8cJ3hF5dS0gAwE4u"   # 36 chars, no marker word
_N7_GHP_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
# A JWT of the published shape: base64url header `{"alg"…`, payload `{"sub"…`, signature.
_N7_JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
           "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
           "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
# The same shape with every segment crafted to satisfy `^ident(\.ident)+$` — no `-`, no
# leading digit. This is the hole Fix 2 would open on its own, so it is a fixture.
_N7_IDENT_SHAPED_JWT = ("eyJhbGciOiJIUzINiJ.eyJzdWIiOiIxMjMJ."
                        "SflKxwRJSMeKKFQTfwpMeJfPOkyJVadQsswc")


def _n7_tree(tmp_path, files, name="n7"):
    """Write {relpath: content} under a fresh root. Mirrors `_project` in
    tests/test_scanner_core_hardening.py — nested paths are the point here (a scan
    reads `docker/.env.prod`, not a flat tmp_path)."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _n7_secret_scan(root):
    return by_id(fallbacks.common_checks(root), "core.secret-scan")


# Fix 1 — a CSS custom-property reference is not a credential.

def test_n7_a_css_var_reference_is_not_a_credential(tmp_path):
    """TAKKO: `token: "var(--color-pink-fill)"` twelve times in one illustration
    component. The NAME axis matches `token`, the value is 22 characters with no
    whitespace and 3.6 bits/char, so it cleared the entropy floor twelve times over.
    Judging the VALUE (N5's principle): `var(--x)` is a stylesheet lookup and can never
    be key material."""
    root = _n7_tree(tmp_path, {"src/EventIllustration.tsx": (
        'const fill = { token: "var(--color-pink-fill)" };\n'
        'const line = { token: "var(--color-ink-700)" };\n'
        'const bg = { secret: "var(--color-cream-base)" };\n')})
    result = _n7_secret_scan(root)
    assert result.tier == "ok", result.detail


def test_n7_fix1_guard_a_real_secret_beside_a_css_var_still_fires(tmp_path):
    """The over-correction guard. The exclusion is anchored and exact, so it excuses a
    `var(--x)` reference and nothing that merely starts with one."""
    proof = _n7_tree(tmp_path, {"src/config.ts": f'const token = "{_N7_GHP_TOKEN}";\n'},
                     name="proof")
    assert _n7_secret_scan(proof).tier == "blocker"
    assert "[proof] GitHub token" in _n7_secret_scan(proof).detail

    heuristic = _n7_tree(tmp_path, {"src/config.ts": f'const token = "{_N7_RANDOM}";\n'},
                         name="heuristic")
    assert _n7_secret_scan(heuristic).tier == "blocker"
    assert "[heuristic] hardcoded token value" in _n7_secret_scan(heuristic).detail

    # A prefix is not the value: `var(--x)` followed by 20 random characters is a key
    # wearing a stylesheet lookup, and an unanchored rule would have laundered it.
    prefixed = _n7_tree(tmp_path, {"src/config.ts": (
        f'const token = "var(--x){_N7_RANDOM}";\n')}, name="prefixed")
    assert _n7_secret_scan(prefixed).tier == "blocker", (
        "a `var(--x)` prefix laundered a random key past the blocker")


# Fix 2 — a dotted identifier path on the core heuristic axis.

def test_n7_a_dotted_identifier_path_is_not_a_credential(tmp_path):
    """TAKKO: `qr_token=preorder.pickup_code.token,` — a Python keyword argument, read
    by the UNQUOTED arm because its value alphabet allows `.`. N5 landed exactly this
    rule in `django.py::_looks_like_import_path` and it never reached the core axis, so
    every attribute access whose name carries a secret word was a blocker."""
    root = _n7_tree(tmp_path, {"marketplace/emails.py": (
        "queue_mail(\n"
        "    qr_token=preorder.pickup_code.token,\n"
        "    api_key=settings.stripe.api_key_name,\n"
        ")\n")})
    result = _n7_secret_scan(root)
    assert result.tier == "ok", result.detail


# Fix 2, tightened — the adversarial pass found the exclusion was broader than its FP
# class. `^ident(\.ident)+$` describes a SHAPE, and two credential families wear it:
# a Doppler service token (`dp.st.prod.<blob>`) and a 5-segment JWE, whose second
# segment is an encrypted key rather than `eyJ…`, so axis 1 never sees it. Both scanned
# clean under the first cut. The three-part rule and the measured margins that set its
# numbers live in `_is_dotted_identifier_path`.

_N7_DOPPLER = "dp.st.prod.aXbYcZdEfGhIjKlMnOpQrStUvWxYzAbCdEfGh"     # H=4.89, seg 37
_N7_JWE = ("eyJhbGciOiJSUEEtT0FFUCJ9.QXBwRW5jS2V5.SXZWZWN0b3I."
           "Q2lwaGVyVGV4dERhdGE.QXV0aFRhZw")                          # H=5.02, 5 segs
# The tightest real values the thresholds were measured against: this Django hasher path
# is the highest-entropy import path found (4.489 bits against the 4.5 ceiling — an
# 0.011-bit margin) and its class name is 26 characters against the 28-character
# segment ceiling. If either threshold moves, this is the value that decides it.
_N7_BCRYPT_HASHER = "django.contrib.auth.hashers.BCryptSHA256PasswordHasher"
_N7_PBKDF2_HASHER = "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher"


def test_n7_fix2_a_dot_structured_credential_is_not_an_identifier_path(tmp_path):
    """A Doppler service token is `dp.st.<config>.<40-char blob>` — dot-STRUCTURED, and
    the first cut of the exclusion read structure as provenance and excused it. Nothing
    about a dotted shape makes a value harmless; what makes an import path harmless is
    that its segments are words."""
    root = _n7_tree(tmp_path, {"config/base.py": f'DOPPLER_TOKEN = "{_N7_DOPPLER}"\n'})
    result = _n7_secret_scan(root)
    assert result.tier == "blocker", result.detail
    assert "[heuristic] hardcoded doppler_token value" in result.detail


def test_n7_fix2_a_nested_jwe_is_not_an_identifier_path(tmp_path):
    """The second miss, and the one that shows why Fix 2b was not enough on its own: a
    5-segment JWE's second segment is the encrypted content key, NOT `eyJ…`, so the JWT
    format does not match it. Axis 1 misses it and the dotted-ident rule then excused
    it — a credential laundered by two rules that each looked reasonable alone."""
    root = _n7_tree(tmp_path, {"src/session.py": f'access_token = "{_N7_JWE}"\n'})
    result = _n7_secret_scan(root)
    assert result.tier == "blocker", result.detail


def test_n7_fix2_guard_the_fleets_own_dotted_paths_stay_quiet(tmp_path):
    """The over-correction guard: N5's false positive must not come back.

    Measured against the real values rather than invented ones — the two hasher paths
    are the highest-entropy import paths in the fleet, and a per-SEGMENT entropy floor
    would have failed on them (`BCryptSHA256PasswordHasher` alone is 4.18 bits,
    `PBKDF2SHA1PasswordHasher` 4.05), which is why the entropy test is on the whole
    value.
    """
    root = _n7_tree(tmp_path, {"config/base.py": (
        f'PASSWORD_HASHER = "{_N7_BCRYPT_HASHER}"\n'
        f'FALLBACK_PASSWORD_HASHER = "{_N7_PBKDF2_HASHER}"\n'
        'AUTH_TOKEN_BACKEND = "rest_framework_simplejwt.tokens.RefreshToken"\n'
        'SESSION_SECRET_PROVIDER = "apps.tenants.backends.TenantBackend"\n'
        "PASSWORD_HASHERS = [\n"
        f'    "{_N7_BCRYPT_HASHER}",\n'
        f'    "{_N7_PBKDF2_HASHER}",\n'
        "]\n")})
    result = _n7_secret_scan(root)
    assert result.tier == "ok", result.detail


def test_n7_fix2_the_segment_ceiling_costs_long_identifier_names(tmp_path):
    """The measured COST of the 28-character segment ceiling, asserted rather than
    discovered later.

    Django ships one class name over the ceiling —
    `UserAttributeSimilarityValidator`, 32 characters — and long method names exist in
    ordinary code. Under a secret-shaped name, such a value is no longer excused and
    fires a `[heuristic]`. It stays that way deliberately: the ceiling is what catches
    a Doppler token's 37-character blob, and a heuristic-tier false positive on a long
    method name is a cheaper mistake than a blocker-tier MISS on a live credential.
    This test is where that trade-off is visible; move the ceiling and it fails.
    """
    long_segment = "self.request.user.get_signed_authentication_token"   # 31-char tail
    assert max(len(part) for part in long_segment.split(".")) >= 28
    root = _n7_tree(tmp_path, {"api/views.py": f'    token = "{long_segment}"\n'})
    assert _n7_secret_scan(root).tier == "blocker"


# Fix 2b — JWTs join axis 1, which is what makes Fix 2 safe to ship.

def test_n7_a_jwt_is_a_published_credential_format(tmp_path):
    """A JWT carries its own authorization and is a credential whatever it is called —
    `data = "<jwt>"` names nothing, and before this it was invisible on both axes."""
    root = _n7_tree(tmp_path, {"src/api.ts": f'const data = "{_N7_JWT}";\n'})
    result = _n7_secret_scan(root)
    assert result.tier == "blocker", result.detail
    assert "[proof] JWT" in result.detail


def test_n7_fix2_guard_an_ident_shaped_jwt_still_fires(tmp_path):
    """The hole Fix 2 opens on its own, closed by Fix 2b and by axis ORDER.

    A JWT is dot-separated, and its base64url segments match `^ident(\\.ident)+$`
    whenever they happen to carry no `-` and no leading digit. A dotted-ident exclusion
    without a JWT format would have excused it. Axis 1 runs first and never consults the
    exclusion, so both the crafted shape and a harmless name still block.
    """
    import re as _re
    assert _re.match(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$",
                     _N7_IDENT_SHAPED_JWT), (
        "the fixture stopped being ident-shaped — it no longer guards anything")

    for name, line in (("named", f'const token = "{_N7_IDENT_SHAPED_JWT}";\n'),
                       ("unnamed", f'const data = "{_N7_IDENT_SHAPED_JWT}";\n')):
        root = _n7_tree(tmp_path, {"src/api.ts": line}, name=name)
        result = _n7_secret_scan(root)
        assert result.tier == "blocker", f"{name}: {result.detail}"
        assert "[proof] JWT" in result.detail


# Fix 3 — `.env` template SUFFIXES, not three exact names.

def test_n7_an_env_template_suffix_is_not_a_committed_env_file(tmp_path):
    """TAKKO's `docker/.env.prod.example` was reported as a committed .env file.

    The exclusion listed three exact names, so every project that keeps one template per
    environment — `.env.prod.example`, `.env.staging.sample` — was told its documentation
    was a leak.
    """
    root = _n7_tree(tmp_path, {
        "docker/.env.prod.example": "POSTGRES_PASSWORD=changeme\n",
        "docker/.env.staging.sample": "POSTGRES_PASSWORD=changeme\n",
        "backend/.env.local.template": "DEBUG=1\n",
        "src/app.py": "print('hello')\n",
    })
    result = _n7_secret_scan(root)
    assert result.tier == "ok", result.detail
    for name in (".env.prod.example", ".env.staging.sample", ".env.local.template"):
        assert not fallbacks._is_env_file(name), name


def test_n7_fix3_guard_a_real_env_file_and_a_key_in_a_template_still_block(tmp_path):
    """Two guards, because the suffix rule could go wrong in two directions.

    `docker/.env.prod` is a real environment file that ships with the tree, and the
    heuristic and `[proof]` axes keep running over templates — a real key pasted into
    `.env.example` is a real leak, which is the commonest way one gets committed.
    """
    real = _n7_tree(tmp_path, {"docker/.env.prod": "POSTGRES_PASSWORD=hunter2\n"},
                    name="real")
    result = _n7_secret_scan(real)
    assert result.tier == "blocker", result.detail
    assert "docker/.env.prod" in result.detail
    assert fallbacks._is_env_file(".env.prod")

    leaked = _n7_tree(tmp_path, {".env.example": f"GITHUB_TOKEN={_N7_GHP_TOKEN}\n"},
                      name="leaked")
    result = _n7_secret_scan(leaked)
    assert result.tier == "blocker", result.detail
    assert "[proof] GitHub token" in result.detail


def test_n7_fix3_a_template_only_repo_still_wants_env_in_gitignore(tmp_path):
    """`core.gitignore` reads the same predicate, and the first cut of Fix 3 narrowed it
    by accident: a repo whose only env-ish file is `docker/.env.prod.example` stopped
    being asked to ignore `.env`.

    A template is EVIDENCE THE PROJECT USES ENV FILES — it is a list of the variables a
    real `.env` will hold — so it is exactly the repo that needs the rule in place
    before the real file appears. The secret-scan question ("is this file itself a
    leak?") and the gitignore question ("will a leak be ignored when it arrives?") have
    different answers on the same file, and now different predicates.
    """
    root = _n7_tree(tmp_path, {
        "docker/.env.prod.example": "POSTGRES_PASSWORD=changeme\n",
        ".gitignore": "*.pyc\n__pycache__/\n",
        "src/app.py": "print('hello')\n",
    })
    result = by_id(fallbacks.common_checks(root), "core.gitignore")
    assert result.tier == "warning", "an env template no longer implied env files"
    assert ".env" in result.detail

    covered = _n7_tree(tmp_path, {
        "docker/.env.prod.example": "POSTGRES_PASSWORD=changeme\n",
        ".gitignore": ".env\n",
    }, name="covered")
    assert by_id(fallbacks.common_checks(covered), "core.gitignore").tier == "ok"


# Fix 3b — two markers for values that announce they are not secrets.

@pytest.mark.parametrize("line", [
    'SECRET_KEY = "dev-only-not-a-secret-change-in-prod"',
    "SECRET_KEY=dev-only-not-a-secret-change-in-prod",
    'API_KEY = "not-a-secret-local-value-only"',
])
def test_n7_a_value_that_announces_it_is_not_a_secret_is_a_placeholder(tmp_path, line):
    """TAKKO ships `SECRET_KEY=dev-only-not-a-secret-change-in-prod` in `.env.example`
    and in `config/settings/base.py`. It is 36 characters at 3.8 bits/char, so it
    cleared both floors — while saying in words that it is not a credential."""
    root = _n7_tree(tmp_path, {"config/base.py": line + "\n"},
                    name=str(abs(hash(line))))
    result = _n7_secret_scan(root)
    assert result.tier == "ok", result.detail


def test_n7_fix3b_guard_a_long_random_value_carrying_dev_only_still_fires(tmp_path):
    """The over-correction guard was already built: D-010 item 5 stopped a marker word
    from excusing anything ≥40 characters AND ≥4.0 bits/char, because
    `django-insecure-<50 random chars>` is a real production key on a great many sites.
    A 45-character random value that happens to start `dev-only-` is the same case."""
    value = "dev-only-" + _N7_RANDOM          # 45 chars, 5.1 bits/char
    assert len(value) == 45
    root = _n7_tree(tmp_path, {"config/base.py": f'SECRET_KEY = "{value}"\n'})
    result = _n7_secret_scan(root)
    assert result.tier == "blocker", (
        "a marker word excused a value long and random enough to be a real key")


# Fix 4 — the evidence line stops claiming the file is committed.

def test_n7_the_env_finding_does_not_claim_the_file_is_committed(tmp_path):
    """The scanner reads a TREE. It cannot see git, and TAKKO's `backend/.env` is
    gitignored and untracked — so "committed .env file" was a statement of fact the
    check had no way to know, printed as a blocker. What it can see is that the file is
    there and will ship with a deploy of this tree; whether it is committed is for the
    reader to check."""
    root = _n7_tree(tmp_path, {"backend/.env": "DATABASE_PASSWORD=hunter2\n"})
    result = _n7_secret_scan(root)
    assert result.tier == "blocker"
    assert "backend/.env: .env file present in the scan tree" in result.detail
    assert "committed .env file" not in result.detail
    assert "git status" in result.fix_hint and "rotate" in result.fix_hint


# ── N7 follow-up: a URL-format COMMENT is not a connection string ───────────────
#
# Found by the post-N7 fleet re-record (2026-08-11). Fix 3 stopped suppressing
# `.env.*.example` files as "committed .env", which correctly turned the line scan back
# on over them — and the first thing it found in `~/E-invoice` was a comment explaining
# the URL format, reported at `[proof]` tier. The password it "matched" is the literal
# `<this>`.
#
# A `[proof]` false positive is the worst kind this check can produce: the label says
# "not a guess", so the reader who checks it once learns the labels mean nothing. That
# is round-6b's Twilio reasoning — flagging a non-secret costs the check's credibility
# twice over — and it applies harder to the tier that claims certainty.

_N7_URL_FORMAT_COMMENT = (
    "# redis://:<this>@redis:6379/0. Use a URL-safe value (no '@' or '/').")


def test_n7_a_url_format_comment_is_not_a_connection_string_credential(tmp_path):
    """The E-invoice line verbatim, in the file it lives in."""
    root = _n7_tree(tmp_path, {"app/.env.prod.example": (
        "REDIS_PASSWORD=changeme\n" + _N7_URL_FORMAT_COMMENT + "\n")})
    result = _n7_secret_scan(root)
    assert result.tier == "ok", result.detail


@pytest.mark.parametrize("line,blocks", [
    # A real one, in the same file: the template is still scanned, and a key pasted
    # into it is still a key.
    ("REDIS_URL=redis://:realS3cretPass@redis:6379/0", True),
    # A password with percent-ENCODED angle brackets is a valid URI and a working
    # credential — `%3C` contains no bare `<`, so the rule does not reach it.
    ("DATABASE_URL=postgres://app:S3cret%3CPass%3E@db:5432/app", True),
    # Documentation, in the three shapes the fleet writes it in.
    (_N7_URL_FORMAT_COMMENT, False),
    ("# DATABASE_URL=postgres://user:<password>@host:5432/db", False),
    ("AMQP_URL=amqp://svc:<your-password-here>@rabbit:5672/", False),
])
def test_n7_guard_the_angle_bracket_rule_is_an_rfc_3986_validity_test(
        tmp_path, line, blocks):
    """Not a heuristic — a validity argument, which is what makes it safe to widen.

    RFC 3986 §2 lists `<` and `>` among the characters that MUST be percent-encoded
    anywhere in a URI; a userinfo password containing one bare cannot parse, so it
    cannot be a working credential. That also answers the one-character-bypass class
    the F1 review raised against `_is_address_not_credential`: an attacker who inserts
    `<` into a real connection string to launder it past this check has broken the
    connection string, and the credential no longer works where it was going.
    """
    root = _n7_tree(tmp_path, {"app/.env.prod.example": line + "\n"},
                    name=str(abs(hash(line))))
    result = _n7_secret_scan(root)
    assert (result.tier == "blocker") is blocks, f"{line!r} -> {result.tier}"
    if blocks:
        assert "[proof] connection string" in result.detail


# ── common core: exposure-auth heuristic (SCAN-M4-EXPOSURE-AUTH) ────────────────
#
# R4-11 WI-3: these two tests carried `@pytest.mark.req("SCAN-M4-EXPOSURE-AUTH")`,
# which reported the requirement `verified`. They prove the warning/ok toggle of the
# common-core heuristic and nothing else. The requirement makes two further claims
# that are not merely untested but absent from the tree:
#   1. "Blocker when the wizard tags financial/personal data" — `_check_exposure_auth`
#      returns only ok/warning, and no wizard question tags data sensitivity, so
#      there is no answer for an escalation to read.
#   2. "*Both modules* warn" — the django module's `checks()` never called
#      `common_checks`, so `core.exposure-auth` never appeared in a Django scan
#      report at all. RETIRED by D-010: `scanner/core.py::scan` now composes the
#      whole common core suite into every report, once per scan, and a module can
#      only supersede a core result by emitting the same id — never omit it. The
#      warning clause is proven per module at report level by the two tests below
#      plus test_scanner_node_ts.py::
#      test_issue_r4_11_a_node_ts_scan_surfaces_the_exposure_auth_check and
#      test_scanner_django.py::test_a_django_scan_surfaces_the_exposure_auth_check.
# The markers stay off and the requirement stays waived (WAIVERS.md) on claim 1
# alone, rather than reading `verified` over an unbuilt escalation. The tests stay
# and still run; they regain the marker when the waiver fully retires. See D-009,
# D-010.


def test_no_auth_indicators_fires_exposure_auth_warning():
    results = fallbacks.common_checks(FIXTURES / "noauth_project")
    res = by_id(results, "core.exposure-auth")
    assert res.tier == "warning"
    assert "no authentication detected" in res.detail
    assert "wizard will ask" in res.detail


def test_auth_indicators_silence_exposure_auth(tmp_path):
    (tmp_path / "app.py").write_text("def login(request):\n    return None\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.exposure-auth")
    assert res.tier == "ok"


# ── common core: the remaining checks ───────────────────────────────────────────

def test_common_core_on_noauth_tree_flags_lockfile_gitignore_tests_healthz():
    results = fallbacks.common_checks(FIXTURES / "noauth_project")
    assert by_id(results, "core.lockfile").tier == "warning"       # package.json, no lock
    assert by_id(results, "core.gitignore").tier == "warning"      # no .gitignore at all
    assert by_id(results, "core.tests-exist").tier == "advice"     # advisory per plan
    assert by_id(results, "core.healthz").tier == "advice"         # §E9: never a blocker
    assert "200 route or" in by_id(results, "core.healthz").detail  # fallback is stated


def test_healthz_detected_when_route_is_greppable(tmp_path):
    (tmp_path / "app.py").write_text("ROUTES = {\"/healthz\": ok_view}\n")
    assert by_id(fallbacks.common_checks(tmp_path), "core.healthz").tier == "ok"


def test_gitignore_gap_checks(tmp_path):
    (tmp_path / "package.json").write_text("{\"name\": \"a\"}\n")
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.gitignore")
    assert res.tier == "warning" and "node_modules" in res.detail
    (tmp_path / ".gitignore").write_text("node_modules/\n.env\n")
    assert by_id(fallbacks.common_checks(tmp_path), "core.gitignore").tier == "ok"


def test_pyproject_lockfile_satisfied_by_uv_lock(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"x\"\n")
    assert by_id(fallbacks.common_checks(tmp_path), "core.lockfile").tier == "warning"
    (tmp_path / "uv.lock").write_text("version = 1\n")
    assert by_id(fallbacks.common_checks(tmp_path), "core.lockfile").tier == "ok"


# ── precedence (§V4): detect() stays true; core dispatch decides ────────────────

def test_dockerfile_detect_is_true_even_when_manage_py_exists(tmp_path):
    """Framework precedence lives in core.detect_modules, not in detect()."""
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    (tmp_path / "manage.py").write_text("import sys\n")
    assert fallbacks.dockerfile_module.detect(tmp_path)


def test_fallbacks_registered_as_fallbacks_in_the_real_registry():
    import scanner.modules  # noqa: F401 — importing registers all modules

    _, fallback_mods = core.registered_modules()
    names = [m.name for m in fallback_mods]
    assert names.count("dockerfile") == 1
    assert names.count("static") == 1


def test_real_registry_scan_of_dockerfile_project_uses_the_fallback():
    report = core.scan(FIXTURES / "dockerfile_project")
    assert report["modules"] == ["dockerfile"]
    assert report["manifest_draft"]["components"]["service"]["kind"] == "dockerfile"


@pytest.mark.req("SCAN-V4-FALLBACK-PRECEDENCE")
@pytest.mark.skipif(
    DJANGO_MODULE_SRC.read_text(encoding="utf-8").strip() == "",
    reason="scanner.modules.django not implemented yet — precedence untestable "
           "against the real registry until it lands",
)
def test_real_registry_prefers_django_module_over_fallbacks(tmp_path):
    import scanner.modules  # noqa: F401 — importing registers all modules

    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    (tmp_path / "manage.py").write_text("import sys\n")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = \"x\"\ndependencies = [\"django\"]\n")
    names = [m.name for m in core.detect_modules(tmp_path)]
    assert "dockerfile" not in names
    assert "static" not in names

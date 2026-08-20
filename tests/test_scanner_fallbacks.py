"""Fallback modules + common-core checks (review3 §V4; scanner/modules/fallbacks.py)."""
import json
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


def test_issue_n7_followup_the_blocker_title_does_not_claim_the_tree_is_git(tmp_path):
    """N7 reworded the evidence lines so they no longer say 'committed'; the
    blocker title still does. The scanner reads a tree and cannot see git — the
    same fact the evidence-line test already pins. A title that overclaims
    trains the operator the way a false evidence line does."""
    (tmp_path / "settings.py").write_text(
        "DEBUG = False\nAPI_KEY = \"9fj39fJ2kd93jdkQpz81\"\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.secret-scan")
    assert res.tier == "blocker"
    assert "committed" not in res.title.lower()


def test_issue_n7_followup_the_ok_title_does_not_claim_the_tree_is_git(tmp_path):
    (tmp_path / "readme.txt").write_text("hello\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.secret-scan")
    assert res.tier == "ok"
    assert "committed" not in res.title.lower()


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


# ── N8 follow-up: a vetoed match must not end the search ────────────────────────
#
# The adversarial pass on N8 found the veto could HIDE a real credential rather than
# just excuse a fake one. `_credential_format_in` took the FIRST connection-string match
# on the line and judged only that one, so a documentation URL standing before a real
# one shadowed it — and this shape got worse, not better, with N8: before the veto, that
# line at least surfaced as a (noisy) blocker.
#
# The general lesson, which outlives this particular veto: a per-match test may skip ITS
# OWN match and must never end the search. Both existing tests are per-match — the
# 6-character floor and `_looks_placeholder` — so both had the same shadowing behaviour;
# only `finditer` makes any of them safe.

@pytest.mark.parametrize("line", [
    # The demonstrated case: an angle-bracket documentation URL, then a real one.
    "DB=postgres://app:<REPLACE_ME>@db1 REAL=postgres://app:Tr0ub4dor3xK9@db2",
    # The same shadowing through the placeholder veto, which predates N8.
    "DB=postgres://app:changeme@db1 REAL=postgres://app:Tr0ub4dor3xK9@db2",
    # …and through the length floor.
    "DB=redis://:short@cache REAL=postgres://app:Tr0ub4dor3xK9@db2",
])
def test_n8_a_vetoed_connection_string_does_not_shadow_a_real_one(tmp_path, line):
    """A veto excuses one match, not the rest of the line."""
    root = _n7_tree(tmp_path, {"app/settings.py": line + "\n"},
                    name=str(abs(hash(line))))
    result = _n7_secret_scan(root)
    assert result.tier == "blocker", f"the real credential was shadowed: {line!r}"
    assert "[proof] connection string" in result.detail


def test_n8_guard_the_natural_ordering_and_the_all_vetoed_line(tmp_path):
    """Two guards around the widening.

    The natural order — real credential first, documentation after — already fired and
    must keep firing; and a line whose connection strings are ALL documentation must
    stay quiet, which is the N8 finding itself and the thing `finditer` could most
    easily have undone.
    """
    natural = _n7_tree(tmp_path, {"app/settings.py": (
        "REAL=postgres://app:Tr0ub4dor3xK9@db2  " + _N7_URL_FORMAT_COMMENT + "\n")},
        name="natural")
    result = _n7_secret_scan(natural)
    assert result.tier == "blocker"
    assert "[proof] connection string" in result.detail

    all_vetoed = _n7_tree(tmp_path, {"app/.env.prod.example": (
        "# postgres://user:<password>@host:5432/db  redis://:<this>@redis:6379/0\n"
        "# amqp://svc:changeme@rabbit:5672/\n")}, name="all_vetoed")
    assert _n7_secret_scan(all_vetoed).tier == "ok", \
        _n7_secret_scan(all_vetoed).detail


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


def test_issue_einvoice_gitignore_next_to_manage_py_counts(tmp_path):
    """E-invoice's real layout: operator points at the repo, manage.py is
    `app/backend/manage.py`, `.gitignore` is `app/.gitignore` — one directory
    above manage.py, not beside it. A sibling-only lookup still warns.
    """
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    (backend / "manage.py").write_text("#!/usr/bin/env python\n")
    (tmp_path / "app" / ".gitignore").write_text(".env\nnode_modules/\n")
    (tmp_path / "app" / "frontend").mkdir()
    (tmp_path / "app" / "frontend" / ".gitignore").write_text("dist/\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.gitignore")
    assert res.title != "No .gitignore"
    assert res.tier == "ok"


def test_issue_einvoice_a_frontend_gitignore_is_not_the_project_one(tmp_path):
    """A nested frontend/.gitignore is not a substitute for the project file.
    E-invoice has both; only app/.gitignore is the one that covers the Django
    tree. With neither a scan-root file nor one next to manage.py, the warning
    still fires.
    """
    (tmp_path / "app" / "frontend").mkdir(parents=True)
    (tmp_path / "app" / "frontend" / ".gitignore").write_text("node_modules/\n")
    (tmp_path / "app" / "manage.py").write_text("#!/usr/bin/env python\n")
    res = by_id(fallbacks.common_checks(tmp_path), "core.gitignore")
    assert res.tier == "warning"
    assert res.title == "No .gitignore"


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


# ── R9-A: containment at the shared seam ────────────────────────────────────────
#
# Round 9 contained node_ts: its source walk, its `package.json` reads and its four
# fixed-name reads all judge a symlinked file by where it LANDS, and refuse one that
# resolves outside the scan root. The comment that shipped with that work said the
# reason `fallbacks` needed none of it was:
#
#     Nothing in fallbacks lets file CONTENT choose a default the operator is then
#     offered.
#
# That was false in both directions and the two probes below are the reviewer's, run
# against master:
#
#   * a repo whose only `Dockerfile` is `-> ../victim/Dockerfile` scanned as
#     `modules: ['dockerfile']` with `manifest_draft.components.service.port = 9999`
#     read off the neighbour, the `dockerfile.port` wizard question suppressed because a
#     port had been "found", and `dockerfile.expose` / `dockerfile.non-root` /
#     `dockerfile.latest-tag` all vouching `ok` for a file the repo does not contain;
#   * a django repo whose `config/settings.py` is `-> ../../victim/settings.py` had
#     `django.env.EVIL_TOKEN` injected into its wizard question list — settings
#     discovery rides `_iter_files`, which yielded symlinked files unconditionally.
#
# The carve-out that survives is the SECRET-SCAN axis, and it is the one the round-7
# comment was actually about: a committed symlinked `.env` pointing at a real secret is
# exactly what `core.secret-scan` hunts, and refusing to read it there would hide the
# finding the check exists for. Everything else — a check verdict, a wizard question or
# default, a manifest fragment — may not be derived from content outside the root.

def _victim_and_repo(tmp_path):
    """A scan root with a neighbouring tree the scan was never pointed at."""
    victim = tmp_path / "victim"
    victim.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    return victim, repo


def test_issue_r9_a_a_symlinked_dockerfile_cannot_steer_the_report(tmp_path):
    """Probe 1, verbatim. `_parse_root_dockerfile` opened `root / "Dockerfile"` by name
    and read whatever the repo pointed that name at — no walk, no containment rule.

    Every one of the four outputs it feeds is asserted here rather than the parse
    result, because the parse result is not what an operator sees: the port lands in the
    frozen manifest's service component, its absence is what makes the wizard ASK for a
    port, and the three checks are the report lines that say this image is fine.
    """
    victim, repo = _victim_and_repo(tmp_path)
    (victim / "Dockerfile").write_text(
        "FROM python:3.12-slim\nRUN useradd -m app\nUSER app\nEXPOSE 9999\n")
    (repo / "Dockerfile").symlink_to("../victim/Dockerfile")
    (repo / "index.html").write_text("<h1>hi</h1>\n")

    report = core.scan(repo)
    results = [core.CheckResult(**c) for c in report["checks"]]

    assert report["modules"] == ["dockerfile"]
    assert report["manifest_draft"]["components"]["service"]["port"] is None
    assert "dockerfile.port" in [q["id"] for q in report["wizard_questions"]]
    assert by_id(results, "dockerfile.expose").tier == "warning"
    assert by_id(results, "dockerfile.non-root").tier == "warning"
    refused = by_id(results, "core.symlinked-files")
    assert refused.tier == "warning"
    assert "Dockerfile" in refused.detail


def test_issue_r9_a_a_symlinked_settings_module_cannot_inject_a_wizard_question(
        tmp_path):
    """Probe 2, verbatim. Django's settings discovery is `fallbacks._iter_files`, which
    yielded a symlinked file unconditionally, so the neighbour's `os.environ['…']`
    names became questions the operator is asked to fill in — and a `SECRET`-ish name
    among them becomes a vault-stored secret, on somebody else's say-so.
    """
    victim, repo = _victim_and_repo(tmp_path)
    (victim / "settings.py").write_text(
        "import os\n\nDEBUG = False\nEVIL = os.environ['EVIL_TOKEN']\n")
    (repo / "manage.py").write_text("import sys\n")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["django==5.2"]\n')
    (repo / "config").mkdir()
    (repo / "config" / "__init__.py").write_text("")
    (repo / "config" / "settings.py").symlink_to("../../victim/settings.py")

    report = core.scan(repo)

    assert report["modules"] == ["django"]
    assert "django.env.EVIL_TOKEN" not in [q["id"] for q in report["wizard_questions"]]
    assert "EVIL_TOKEN" not in json.dumps(report)
    refused = by_id([core.CheckResult(**c) for c in report["checks"]],
                    "core.symlinked-files")
    assert "config/settings.py" in refused.detail


def test_issue_r9_a_the_remaining_fixed_name_reads_are_contained_too(tmp_path):
    """The two other reads in this module that open a repo-controlled name and derive a
    verdict from what comes back: `.gitignore` (whose content IS `core.gitignore`) and
    `requirements*.txt` (whose `==` lines are one of the three ways `core.lockfile` is
    satisfied). Both vouched for the scanned repo out of the neighbour's files.
    """
    victim, repo = _victim_and_repo(tmp_path)
    (victim / ".gitignore").write_text(".env\nnode_modules/\n")
    (victim / "requirements.txt").write_text("django==5.2\ngunicorn==21.2.0\n")
    (repo / ".gitignore").symlink_to("../victim/.gitignore")
    (repo / "requirements.txt").symlink_to("../victim/requirements.txt")
    (repo / "package.json").write_text('{"name": "x"}\n')
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (repo / ".env").write_text("PLAIN=1\n")

    results = fallbacks.common_checks(repo)

    gitignore = by_id(results, "core.gitignore")
    assert gitignore.tier == "warning", gitignore
    assert ".env" in gitignore.detail and "node_modules" in gitignore.detail
    assert by_id(results, "core.lockfile").tier == "warning"


def test_issue_r9_a_the_secret_scan_still_reads_an_escaping_symlink(tmp_path):
    """THE CARVE-OUT, and it is the whole reason this is not "refuse every link".

    A committed `.env` that is a symlink to a real secret file is the finding
    `core.secret-scan` exists to make. The refusal rule is scoped to the axis, not to
    the walk: the escaping file is kept out of every OTHER check's input and handed to
    the secret scan alone.
    """
    victim, repo = _victim_and_repo(tmp_path)
    (victim / "env").write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")
    (repo / ".env").symlink_to("../victim/env")
    (repo / "index.html").write_text("<h1>hi</h1>\n")

    results = fallbacks.common_checks(repo)

    secrets = by_id(results, "core.secret-scan")
    assert secrets.tier == "blocker", secrets
    assert ".env" in secrets.detail


def test_issue_r9_a_the_carve_out_does_not_widen_to_the_other_axes(tmp_path):
    """…and the same file may not answer a question about the repo's own shape. A
    symlinked source file carrying an auth decorator used to satisfy `core.exposure-auth`
    — an `ok` that says "this site authenticates its users" about a file the repo does
    not contain.
    """
    victim, repo = _victim_and_repo(tmp_path)
    (victim / "views.py").write_text(
        "from django.contrib.auth.decorators import login_required\n"
        "\n\n@login_required\ndef home(request):\n    return 1\n")
    (repo / "views.py").symlink_to("../victim/views.py")
    (repo / "index.html").write_text("<h1>hi</h1>\n")

    results = fallbacks.common_checks(repo)

    assert by_id(results, "core.exposure-auth").tier == "warning"


def test_issue_r9_a_a_scan_root_reached_through_a_symlink_is_read_normally(tmp_path):
    """False-positive guard 1, mirroring the node_ts test of the same shape: a scan root
    is frequently reached THROUGH a symlink (`/tmp` on macOS, a checkout under a linked
    home), so both sides are resolved. Comparing an unresolved root against a resolved
    file refuses every file in such a tree — the whole repo would go dark.
    """
    real = tmp_path / "real"
    real.mkdir()
    (real / "Dockerfile").write_text("FROM python:3.12-slim\nUSER app\nEXPOSE 8080\n")
    (real / ".gitignore").write_text(".env\n")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    report = core.scan(linked)
    results = [core.CheckResult(**c) for c in report["checks"]]

    assert report["manifest_draft"]["components"]["service"]["port"] == 8080
    assert by_id(results, "dockerfile.expose").tier == "ok"
    assert [c for c in report["checks"] if c["id"] == "core.symlinked-files"] == []


def test_issue_r9_a_an_in_root_symlinked_file_is_still_read(tmp_path):
    """False-positive guard 2. `Dockerfile -> docker/Dockerfile.prod` and
    `src/config.ts -> ../shared/config.ts` are ordinary committed layouts whose content
    is inside the tree the operator pointed at either way. Containment, not
    refuse-all-links: refusing these would drop real source out of the report for
    nothing.
    """
    _victim, repo = _victim_and_repo(tmp_path)
    (repo / "docker").mkdir()
    (repo / "docker" / "Dockerfile.prod").write_text(
        "FROM python:3.12-slim\nUSER app\nEXPOSE 8080\n")
    (repo / "Dockerfile").symlink_to("docker/Dockerfile.prod")

    report = core.scan(repo)
    results = [core.CheckResult(**c) for c in report["checks"]]

    assert report["manifest_draft"]["components"]["service"]["port"] == 8080
    assert by_id(results, "dockerfile.expose").tier == "ok"
    assert [c for c in report["checks"] if c["id"] == "core.symlinked-files"] == []


def test_issue_r9_a_a_repo_with_no_symlinks_reports_exactly_what_it_did_before(tmp_path):
    """`core.symlinked-files` is APPENDED and only when something was refused — the same
    None-omission property `core.declaration-file` was added under, for the same reason:
    a report from an ordinary repo must be byte-identical to the one it produced before
    this check existed, or every recorded demo artifact moves.
    """
    ids = [c.id for c in fallbacks.common_checks(FIXTURES / "dockerfile_project")]
    assert "core.symlinked-files" not in ids


# ── R9-Q1: the depth cap was a number nothing asserted ──────────────────────────

def test_issue_r9_q1_the_walk_does_not_open_a_directory_past_the_cap(tmp_path,
                                                                     monkeypatch):
    """R9-Q1. `max_depth` is the reason `django.project_root` can look for a `manage.py`
    in a monorepo without descending a vendored tree, and R8-6's whole fix was making it
    "a walk that stops rather than a filter applied after descending forever". Mutating
    the bound to `max_depth=None` survived 776 tests: every existing test asserts what
    came BACK, and a walk that descends the whole tree and then filters returns exactly
    the same files.

    So the contract asserted here is the DESCENT, not the yield — `iterdir` is spied on
    and the assertion is that a directory which could only hold files past the cap is
    never opened at all. Cost, not correctness, is what the bound buys, and cost is
    invisible to a result set.

    The tree is one chain, and `max_depth=3` is the interesting cut: `d1/d2` holds a file
    at depth 3 and must be read; `d1/d2/d3` can hold nothing shallower than depth 4 and
    must not be touched, along with everything under it.
    """
    root = tmp_path / "repo"
    (root / "d1" / "d2" / "d3" / "d4").mkdir(parents=True)
    (root / "a.txt").write_text("1")
    (root / "d1" / "b.txt").write_text("2")
    (root / "d1" / "d2" / "c.txt").write_text("3")
    (root / "d1" / "d2" / "d3" / "e.txt").write_text("4")
    (root / "d1" / "d2" / "d3" / "d4" / "f.txt").write_text("5")

    opened = []
    real_iterdir = pathlib.Path.iterdir

    def spy(self):
        opened.append(pathlib.Path(self).resolve())
        return real_iterdir(self)

    monkeypatch.setattr(pathlib.Path, "iterdir", spy)

    found = sorted(p.relative_to(root).as_posix()
                   for p in fallbacks._iter_files(root, max_depth=3))

    assert found == ["a.txt", "d1/b.txt", "d1/d2/c.txt"]
    for past_the_cap in ("d1/d2/d3", "d1/d2/d3/d4"):
        assert (root / past_the_cap).resolve() not in opened, (
            f"{past_the_cap} was opened; the cap is filtering results rather than "
            f"stopping the descent")
    # …and the directories at or inside the cap WERE opened, so the assertion above
    # cannot pass because the walk did nothing.
    assert (root / "d1" / "d2").resolve() in opened


def test_issue_r9_q1_a_directory_past_the_cap_is_not_a_skipped_path(tmp_path):
    """The other half of "not opened": a directory the walk declined to descend is not a
    directory the filesystem refused, so it must not land in `skipped` — that list is
    `core.secret-scan`'s honesty signal (R7-2), and filling it with directories the
    scanner chose not to read would fire the "part of the tree could not be read"
    warning on every deep repo. Which is the over-correction R7-2's own ruling names.
    """
    root = tmp_path / "repo"
    (root / "d1" / "d2" / "d3").mkdir(parents=True)
    (root / "d1" / "d2" / "d3" / "e.txt").write_text("4")

    skipped = []
    list(fallbacks._iter_files(root, skipped, max_depth=2))

    assert skipped == []


def test_issue_r9_q1_no_cap_still_means_no_cap(tmp_path):
    """The default is unbounded and stays unbounded: `common_checks`' own walk passes no
    `max_depth`, and a secret three directories down is still a secret. Asserted so the
    fix for the cap cannot become a cap on everything."""
    root = tmp_path / "repo"
    (root / "d1" / "d2" / "d3" / "d4").mkdir(parents=True)
    (root / "d1" / "d2" / "d3" / "d4" / "deep.txt").write_text("x")

    found = [p.relative_to(root).as_posix() for p in fallbacks._iter_files(root)]

    assert found == ["d1/d2/d3/d4/deep.txt"]


# ── R10-Q1: the containment rule fell over a symlink loop ───────────────────────
#
# `escapes_root` catches `OSError` around `Path.resolve()`, and on CPython 3.11 a
# symlink loop does not raise one: `pathlib._PosixFlavour.resolve` catches the
# `OSError(ELOOP)` itself and re-raises `RuntimeError("Symlink loop from …")`. So the
# one rule that exists to FAIL CLOSED failed open, upward, out of `scanner.core.scan`,
# and the operator got a traceback instead of a report.
#
# Two entry points, because the two `glob` families that reach the rule live in
# different modules and neither is covered by the other's test: `_has_pinned_requirements`
# here (`requirements*.txt`, one of the three ways `core.lockfile` is satisfied), and
# `django._deps_text` / `_versions` / `_check_deps_pinned` in test_scanner_django.py.
#
# The tree is the reviewer's, verbatim: a `requirements.txt` symlink whose target is
# its own name.

def _loop_link(directory, name="requirements.txt"):
    """A committed symlink that points at itself — ELOOP on any resolve()."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).symlink_to(name)
    return directory / name


def test_issue_r10_q1_a_symlink_loop_is_refused_rather_than_raised(tmp_path):
    """R10-Q1. `requirements.txt -> requirements.txt`, which is what a rename accident
    or a half-applied vendoring script leaves behind, and which the filesystem answers
    with ELOOP rather than with a path.

    Fails closed: unresolvable is not demonstrably contained, which is the rule
    `escapes_root`'s own docstring states for the `OSError` arm. `core.lockfile` is the
    verdict that read hangs off — a pinned `requirements.txt` is one of the three ways
    it is satisfied — and a file the filesystem will not resolve pins nothing.

    NOT ASSERTED, and stated so the next reader does not take its absence for a claim:
    `core.symlinked-files` does not fire here. The walk behind it reaches a file by
    `is_file()`, which a looping link answers False to, so this refusal happens at the
    `glob` read and is seen by no walk. That is a gap in the WALK's reach — see
    `read_contained`, where R10-A8 records the same boundary — and closing it means
    deciding what a report should say about a link that resolves nowhere at all, which
    is a wording decision and its own diff.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
    _loop_link(repo)

    results = fallbacks.common_checks(repo)

    assert by_id(results, "core.lockfile").tier == "warning"
    assert [r.id for r in results], "a suite that returns nothing is no suite"


def test_issue_r10_q1_the_rule_itself_fails_closed_on_a_loop(tmp_path):
    """The seam, directly. Every caller in both modules reads this one answer, so the
    property belongs to `escapes_root` rather than to any check that consults it."""
    repo = tmp_path / "repo"
    link = _loop_link(repo, "looped.txt")

    assert fallbacks.escapes_root(repo, link) is True


def test_issue_r10_q1_a_scan_of_the_looping_tree_returns_a_report(tmp_path):
    """The demonstration verbatim: `scanner.core.scan` over `{pyproject.toml,
    requirements.txt -> requirements.txt}` raised `RuntimeError` out of django's
    `detect`, so the repo got no report — a regression against f80d09a, where the
    identical tree scanned fine because no containment rule existed to trip over yet.

    A `Dockerfile` is added to the reviewer's two files so that a module MATCHES and the
    core suite is therefore composed: `scan` over a tree no module recognizes returns an
    empty check list by design, which would make this assertion pass without saying
    anything.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (repo / "Dockerfile").write_text("FROM python:3.12-slim\nUSER app\nEXPOSE 8000\n")
    _loop_link(repo)

    report = core.scan(repo)

    assert report["schema_version"] == core.SCHEMA_VERSION
    assert "core.lockfile" in [c["id"] for c in report["checks"]], (
        "a scan that reports nothing is no scan")


# ── R10-A4: two spellings of one comparison ────────────────────────────────────
#
# `escapes_root` and `node_ts._workspace_candidate_problem` each wrote out the same
# resolve-and-compare. The workspace rule cannot call `escapes_root` — that one is
# symlink-gated and a candidate reaching its compare is by definition NOT a symlink, so
# it would answer False about everything — which is exactly how a second copy gets
# written. `_resolves_outside` is the comparison with the gate and the exception
# handling lifted off it, so there is one of it.

def test_issue_r10_a4_a_path_that_resolves_to_the_root_is_inside_the_root(tmp_path):
    """The one case the two old spellings answered differently, reconciled rather than
    preserved: the workspace rule carried `resolved != root_resolved`, `escapes_root`
    did not — the root is not among its own parents — so a link resolving TO the scan
    root was an escape by one reading and contained by the other.
    """
    repo = tmp_path / "repo"
    (repo / "packages").mkdir(parents=True)
    (repo / "packages" / "up").symlink_to("..", target_is_directory=True)

    assert fallbacks._resolves_outside(repo, repo) is False
    assert fallbacks._resolves_outside(repo, repo / "packages" / "up") is False
    assert fallbacks._resolves_outside(repo, tmp_path) is True


def test_issue_r10_a4_escapes_root_is_the_symlink_gate_plus_the_comparison(monkeypatch,
                                                                          tmp_path):
    """…and nothing else. Both halves are asserted through the shared function rather
    than through a tree, because the claim is about which pieces `escapes_root` is made
    of: an ordinary file never reaches the comparison, and a symlink returns whatever it
    says.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real.txt").write_text("x")
    (repo / "link.txt").symlink_to("real.txt")

    monkeypatch.setattr(fallbacks, "_resolves_outside", lambda root, path: True)
    assert fallbacks.escapes_root(repo, repo / "real.txt") is False, (
        "the gate: a file that is not a symlink is contained by construction and the "
        "comparison is never paid for")
    assert fallbacks.escapes_root(repo, repo / "link.txt") is True

    monkeypatch.setattr(fallbacks, "_resolves_outside", lambda root, path: False)
    assert fallbacks.escapes_root(repo, repo / "link.txt") is False


# ── R10-A8: "1 symlinked file resolve outside the scanned repository" ──────────

def test_issue_r10_a8_the_refusal_line_conjugates_for_one_file(tmp_path):
    """R10-A8. The plural was formed on the NOUN and the verb was left in the plural,
    so the singular case read "1 symlinked file resolve outside" — the same defect the
    frontend fixed the other way round in R9-8 ("3 Deferred to sandboxs"), and the same
    remedy: conjugate both, rather than appending an `s` to one of them.
    """
    victim, repo = _victim_and_repo(tmp_path)
    (victim / "config.py").write_text("PORT = 1\n")
    (repo / "config.py").symlink_to("../victim/config.py")
    (repo / "index.html").write_text("<h1>hi</h1>\n")

    detail = by_id(fallbacks.common_checks(repo), "core.symlinked-files").detail

    assert detail.splitlines()[0] == (
        "1 symlinked file resolves outside the scanned repository:")


def test_issue_r10_a8_and_still_agrees_with_itself_for_two(tmp_path):
    """The other side of the same line, so the fix cannot be "always singular"."""
    victim, repo = _victim_and_repo(tmp_path)
    for name in ("config.py", "settings.py"):
        (victim / name).write_text("PORT = 1\n")
        (repo / name).symlink_to(f"../victim/{name}")
    (repo / "index.html").write_text("<h1>hi</h1>\n")

    detail = by_id(fallbacks.common_checks(repo), "core.symlinked-files").detail

    assert detail.splitlines()[0] == (
        "2 symlinked files resolve outside the scanned repository:")

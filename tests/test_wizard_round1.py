"""Wizard review round 1 (2026-08-09) — regression tests, one per finding.

The inherited commit 51a0d77 passed all mechanical gates; every finding below is a
property no existing test pinned. That is the round working as designed: gates catch
regressions, reviews catch omissions.
"""
import json

import pytest
from django.core.exceptions import ValidationError

from core.models import Project, Site
from core.validators import validate_domain
from vault import service as vault_service
from vault.models import Secret
from wizard import service
from wizard.materialize import MaterializeRefused, materialize
from wizard.questions import coerce_answer, question_map

from .test_wizard import make_report

pytestmark = pytest.mark.django_db


ENV_QUESTIONS = [
    {"id": "django.env.DATABASE_URL", "prompt": "Value for DATABASE_URL",
     "kind": "text", "default": None, "choices": []},
    {"id": "django.env.SECRET_KEY", "prompt": "Value for SECRET_KEY",
     "kind": "secret", "default": None, "choices": []},
]


def _project(**kw):
    defaults = dict(name="p", slug=kw.pop("slug", "p"),
                    git_url="https://github.com/o/r.git",
                    scan_report=make_report(questions=ENV_QUESTIONS))
    defaults.update(kw)
    return Project.objects.create(**defaults)


# ── F1: env values never enter the manifest body ─────────────────────────────────

@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_plain_env_values_are_not_frozen_into_the_body():
    """Round-1 F1 (security, high). Classification is a substring heuristic; one miss
    would freeze a live credential into an append-only JSON row returned by GET. The
    registry text for this very requirement says 'env NAMES only, never values' — the
    previous implementation wrote plain-classified values into body['env_plain']."""
    project = _project(slug="f1a")
    site = Site.objects.create(project=project, name="s")
    service.set_answers(site, {
        "site.domain": "app.example.com",
        "django.env.DATABASE_URL": "postgres://user:hunter2-oops@db/prod",
    })
    manifest = materialize(site, confirm_warnings=True)

    dumped = json.dumps(manifest.body)
    assert "hunter2-oops" not in dumped
    assert "env_plain" not in manifest.body
    assert manifest.body["env_names"] == ["DATABASE_URL"]


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_manifest_owns_one_env_bundle_in_the_vault():
    """The values live as ONE vault bundle per manifest version, AAD-bound to
    site:version — so v3 deploys with v3's env exactly as frozen, and a stolen DB
    dump holds only ciphertext."""
    project = _project(slug="f1b")
    site = Site.objects.create(project=project, name="s")
    service.set_answers(site, {
        "site.domain": "app.example.com",
        "django.env.DATABASE_URL": "postgres://db/prod",
        "django.env.SECRET_KEY": "super-secret-value",
    })
    manifest = materialize(site, confirm_warnings=True)

    bundle = Secret.objects.get(pk=manifest.body["env_bundle_ref"])
    assert bundle.owner_type == "manifest"
    assert bundle.owner_id == f"{site.pk}:v{manifest.version}"
    values = json.loads(vault_service.get(bundle))
    assert values == {"DATABASE_URL": "postgres://db/prod",
                      "SECRET_KEY": "super-secret-value"}
    # And the plaintext appears nowhere in the manifest row itself.
    assert "super-secret-value" not in json.dumps(manifest.body)


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_each_version_freezes_its_own_env():
    """Changing an answer after materializing must not mutate v1's env."""
    project = _project(slug="f1c")
    site = Site.objects.create(project=project, name="s")
    service.set_answers(site, {"site.domain": "app.example.com",
                               "django.env.DATABASE_URL": "postgres://db/one"})
    v1 = materialize(site, confirm_warnings=True)
    service.set_answers(site, {"django.env.DATABASE_URL": "postgres://db/two"})
    v2 = materialize(site, confirm_warnings=True)

    one = json.loads(vault_service.get(Secret.objects.get(pk=v1.body["env_bundle_ref"])))
    two = json.loads(vault_service.get(Secret.objects.get(pk=v2.body["env_bundle_ref"])))
    assert one["DATABASE_URL"] == "postgres://db/one"
    assert two["DATABASE_URL"] == "postgres://db/two"


# ── F2: the domain answer is a validated domain, not free text ───────────────────

@pytest.mark.req("WIZ-ANSWER-VALIDATION")
@pytest.mark.parametrize("bad", [
    "https://app.example.com",       # a URL, not a domain
    "app.example.com:8080",          # port
    "app.example.com/path",          # path
    "*.example.com",                 # wildcard
    "10.0.0.1",                      # IP literal — DNS/TLS need a name
    "app_1.example.com",             # underscore is not LDH
    "-app.example.com",              # leading hyphen
    "example",                       # no TLD
    "app.example.com\nX-Injected: 1",  # header/config injection shape
    "a" * 64 + ".com",               # label over 63
    ("a." * 130) + "com",            # total over 253
])
def test_domain_answer_rejects_malformed(bad):
    """Round-1 F2 (security, high). This value reaches Caddy config and DNS records;
    it was previously coerced as free text (2048 chars, control characters allowed)
    into a 253-char column."""
    project = _project(slug="f2a")
    question = question_map(project)["site.domain"]
    with pytest.raises(ValidationError):
        coerce_answer(question, bad)


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_domain_answer_is_normalized():
    project = _project(slug="f2b")
    question = question_map(project)["site.domain"]
    assert coerce_answer(question, "  App.Example.COM. ") == "app.example.com"
    # Unicode is stored in its IDNA A-label form so later consumers see one alphabet.
    assert coerce_answer(question, "bücher.example") == "xn--bcher-kva.example"


def test_validate_domain_matches_model_capacity():
    """The validator's cap and Site.domain's max_length must agree, or Postgres 500s
    on the seam. Pinned so a future field change re-opens the question."""
    field = Site._meta.get_field("domain")
    assert field.max_length == 253
    with pytest.raises(ValidationError):
        validate_domain("a" * 250 + ".example.com")


# ── F3: no fingerprint oracle in the wizard state ────────────────────────────────

@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_answered_state_carries_no_fingerprint():
    """Round-1 F3. sha256(plaintext)[:16], unsalted, of a possibly low-entropy value
    is a confirmation oracle for anyone with a stolen session. changed_at gives the
    UI its 'set on Tuesday' signal with nothing to test a guess against."""
    project = _project(slug="f3")
    site = Site.objects.create(project=project, name="s")
    service.set_answers(site, {"django.env.SECRET_KEY": "hunter2"})
    state = service.answered_state(site)
    entry = state["django.env.SECRET_KEY"]
    assert entry["answered"] is True
    assert "changed_at" in entry
    assert "fingerprint" not in entry
    assert "hunter2" not in json.dumps(state)


# ── F4: the 409 carries every problem, not the first ─────────────────────────────

@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_refusal_carries_all_problems_at_once():
    """Round-1 F4. preflight gathers everything precisely so the operator sees the
    whole list; raising only problems[0] produced the fix-one-see-the-next loop the
    docstring claims to avoid."""
    report = make_report()
    report["checks"].append({"id": "x.blocker", "tier": "blocker",
                             "title": "a blocker", "detail": "", "fix_hint": ""})
    project = _project(slug="f4", scan_report=report)
    site = Site.objects.create(project=project, name="s")
    # No answers at all: blocker present AND required answer missing.
    with pytest.raises(MaterializeRefused) as exc:
        materialize(site)
    codes = [p["code"] for p in exc.value.problems]
    assert "blockers_present" in codes
    assert "answers_missing" in codes
    assert len(codes) >= 2
    # Backwards-compatible single-cause fields still present and coherent.
    assert exc.value.as_dict()["code"] == codes[0]


# ── F5: GET is side-effect free ──────────────────────────────────────────────────

@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_wizard_get_does_not_delete_answers(client, django_user_model):
    """Round-1 F5. preflight runs on GET; the previous version deleted downgraded
    plaintext rows there — a GET with side effects, and two consecutive refreshes
    reported different problem codes."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from .test_wizard import _report_with_kind

    user = django_user_model.objects.create_user(username="op", password="x" * 16)
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)

    project = _project(slug="f5", scan_report=_report_with_kind("text"))
    site = Site.objects.create(project=project, name="s")
    service.set_answers(site, {"django.env.API_KEY": "sk-live-LEAK"})
    project.scan_report = _report_with_kind("secret")
    project.save()

    first = client.get(f"/api/v1/sites/{site.pk}/wizard/").json()
    second = client.get(f"/api/v1/sites/{site.pk}/wizard/").json()

    # The row survives both reads, and both reads report the same problem.
    assert site.answers.filter(question_id="django.env.API_KEY").exists()
    for payload in (first, second):
        assert "answers_need_reentry" in [p["code"] for p in payload["blocking"]]


# ── F6: concurrent saves serialize instead of 500ing ─────────────────────────────

@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_set_answers_locks_the_site_row():
    """Round-1 F6, pinned structurally: SQLite ignores FOR UPDATE so a true
    concurrency test needs Postgres (T2, Phase 2.5). Until then, assert the lock is
    taken so removing it is a visible act rather than an accident."""
    import inspect

    source = inspect.getsource(service.set_answers)
    assert "select_for_update" in source

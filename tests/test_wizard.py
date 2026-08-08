"""Wizard, materialization and manifest tests.

Organised by the five properties the 2026-08-09 design debate said this chunk must
hold: error-proofing on human input, secrets never leaving the vault, refusals that
name their cause, append-only manifests, and no crash paths on ordinary user actions.
"""
import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import Project, Site
from deploys.models import Manifest
from vault import service as vault_service
from wizard import service
from wizard.materialize import MaterializeRefused, materialize, preflight
from wizard.models import WizardAnswer
from wizard.questions import question_set

pytestmark = pytest.mark.django_db

SECRET_VALUE = "wizard-test-DB-PASSWORD-MARKER"


def make_report(*, checks=(), questions=(), draft=None):
    return {
        "schema_version": 1,
        "modules": ["django"],
        "checks": list(checks),
        "sandbox_jobs": [],
        "wizard_questions": list(questions),
        "manifest_draft": draft or {"schema_version": 1, "deploy_strategy": "blue_green"},
        "summary": {},
    }


@pytest.fixture
def project(db):
    return Project.objects.create(
        name="demo", slug="demo", source_kind=Project.Source.GIT,
        git_url="https://github.com/org/repo.git",
        scan_report=make_report(questions=[
            {"id": "django.domain", "prompt": "Domain", "kind": "text",
             "default": None, "choices": []},
            {"id": "django.db", "prompt": "Database", "kind": "choice",
             "default": "postgres", "choices": ["postgres", "sqlite"]},
            {"id": "django.env.DATABASE_PASSWORD", "prompt": "Value for DATABASE_PASSWORD",
             "kind": "secret", "default": None, "choices": []},
            {"id": "django.workers", "prompt": "Workers", "kind": "number",
             "default": 3, "choices": []},
        ]),
    )


@pytest.fixture
def site(project):
    return Site.objects.create(project=project, name="demo-prod")


# ── question assembly ─────────────────────────────────────────────────────────

@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_module_domain_question_is_aliased_not_duplicated(project):
    ids = [q.id for q in question_set(project)]
    assert ids.count("site.domain") == 1
    assert "django.domain" not in ids


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_question_order_is_stable(project):
    """A form that reshuffles between polls is a form people mis-answer."""
    assert [q.id for q in question_set(project)] == [q.id for q in question_set(project)]


# ── error-proofing on human input ─────────────────────────────────────────────

@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_unknown_question_is_rejected_not_ignored(site):
    """Silently dropping an answer is how a site deploys half-configured and nobody
    finds out until it 500s in production."""
    with pytest.raises(ValidationError) as exc:
        service.set_answers(site, {"not.a.question": "x"})
    assert "not.a.question" in exc.value.message_dict


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_choice_outside_choices_is_rejected(site):
    with pytest.raises(ValidationError):
        service.set_answers(site, {"django.db": "oracle"})


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_number_question_rejects_prose(site):
    with pytest.raises(ValidationError):
        service.set_answers(site, {"django.workers": "lots"})


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_number_question_accepts_numeric_string(site):
    """Forms submit strings. Rejecting "3" for a number question would be correct and
    useless."""
    service.set_answers(site, {"django.workers": "3"})
    assert WizardAnswer.objects.get(site=site, question_id="django.workers").value == 3


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_bool_rejects_ambiguous_yes(site, project):
    """'true'/'false' are the same intent as True/False. 'yes' and 'sure' are not —
    a wizard that guesses builds a manifest nobody predicted."""
    from scanner.core import WizardQuestion
    from wizard.questions import coerce_answer

    question = WizardQuestion(id="x", prompt="x", kind="bool")
    assert coerce_answer(question, "true") is True
    with pytest.raises(ValidationError):
        coerce_answer(question, "yes")


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_whitespace_only_text_is_required_not_accepted(site):
    with pytest.raises(ValidationError):
        service.set_answers(site, {"site.domain": "   "})


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_partial_save_is_all_or_nothing(site):
    """One bad field rejects the whole PATCH: a client must never end up with half
    its answers persisted and no clear signal about which half."""
    with pytest.raises(ValidationError):
        service.set_answers(site, {"site.domain": "ok.example.com",
                                   "django.db": "oracle"})
    assert not WizardAnswer.objects.filter(site=site).exists()


# ── secrets ───────────────────────────────────────────────────────────────────

@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_secret_answer_goes_to_the_vault_not_the_table(site):
    service.set_answers(site, {"django.env.DATABASE_PASSWORD": SECRET_VALUE})
    answer = WizardAnswer.objects.get(site=site, question_id="django.env.DATABASE_PASSWORD")
    assert answer.is_secret and answer.value is None and answer.secret_ref is not None
    assert vault_service.get(answer.secret_ref).decode() == SECRET_VALUE


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_secret_value_never_appears_in_answers_table(site):
    service.set_answers(site, {"django.env.DATABASE_PASSWORD": SECRET_VALUE})
    for answer in WizardAnswer.objects.all():
        assert SECRET_VALUE not in str(answer.value)


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_answered_state_reports_secrets_as_metadata_only(site):
    service.set_answers(site, {"django.env.DATABASE_PASSWORD": SECRET_VALUE})
    state = service.answered_state(site)
    entry = state["django.env.DATABASE_PASSWORD"]
    assert entry["answered"] is True and entry["is_secret"] is True
    assert SECRET_VALUE not in str(state)


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_rotating_a_secret_deletes_the_superseded_ciphertext(site):
    """A rotated database password left in the vault is a live credential nobody is
    tracking."""
    from vault.models import Secret

    service.set_answers(site, {"django.env.DATABASE_PASSWORD": "old-value"})
    first = WizardAnswer.objects.get(site=site).secret_ref_id
    service.set_answers(site, {"django.env.DATABASE_PASSWORD": "new-value"})
    second = WizardAnswer.objects.get(site=site).secret_ref_id
    assert first != second
    assert not Secret.objects.filter(pk=first).exists()


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_db_constraint_refuses_a_secret_answer_with_a_plaintext_value(site):
    """Defence in depth: even a future code path that bypasses set_answers cannot
    write plaintext into a row flagged secret."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        WizardAnswer.objects.create(site=site, question_id="x", is_secret=True,
                                    value="plaintext", secret_ref=None)


# ── materialization refusals ──────────────────────────────────────────────────

@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_unscanned_project_refuses_with_a_named_cause(db):
    bare = Project.objects.create(name="bare", slug="bare",
                                  git_url="https://github.com/o/r.git")
    bare_site = Site.objects.create(project=bare, name="s")
    with pytest.raises(MaterializeRefused) as exc:
        materialize(bare_site)
    assert exc.value.code == "scan_required"


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_blockers_refuse_and_list_themselves(project, site):
    project.scan_report = make_report(checks=[
        {"id": "django.debug-hardcoded", "tier": "blocker", "title": "DEBUG is True"},
    ])
    project.save()
    with pytest.raises(MaterializeRefused) as exc:
        materialize(site)
    assert exc.value.code == "blockers_present"
    assert exc.value.items[0]["id"] == "django.debug-hardcoded"


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_missing_required_answer_refuses(site):
    with pytest.raises(MaterializeRefused) as exc:
        materialize(site)
    assert exc.value.code == "answers_missing"
    assert exc.value.items[0]["id"] == "site.domain"


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_preflight_reports_every_problem_at_once(project, site):
    """Reporting one problem, making the operator fix it, then reporting the next is
    the interaction that makes people hate wizards."""
    project.scan_report = make_report(checks=[
        {"id": "b1", "tier": "blocker", "title": "one"},
    ])
    project.save()
    codes = {p["code"] for p in preflight(site)}
    assert codes == {"blockers_present", "answers_missing"}


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_warnings_require_confirmation(project, site):
    project.scan_report = make_report(
        checks=[{"id": "w1", "tier": "warning", "title": "SQLite in production"}],
        questions=project.scan_report["wizard_questions"],
    )
    project.save()
    service.set_answers(site, {"site.domain": "demo.example.com"})

    with pytest.raises(MaterializeRefused) as exc:
        materialize(site)
    assert exc.value.code == "warnings_unconfirmed"

    manifest = materialize(site, confirm_warnings=True)
    assert manifest.version == 1


# ── the manifest itself ───────────────────────────────────────────────────────

@pytest.fixture
def answered_site(project, site):
    service.set_answers(site, {
        "site.domain": "demo.example.com",
        "django.db": "postgres",
        "django.env.DATABASE_PASSWORD": SECRET_VALUE,
    })
    return site


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_manifest_carries_env_names_never_values(answered_site):
    manifest = materialize(answered_site)
    assert manifest.body["env_names"] == ["DATABASE_PASSWORD"]
    assert SECRET_VALUE not in str(manifest.body)


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_manifest_freezes_the_scan_draft(answered_site):
    """§V6: module outputs are copied in, so deploys never needs the scanner."""
    manifest = materialize(answered_site)
    assert manifest.body["deploy_strategy"] == "blue_green"
    assert manifest.scan_report_hash


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_module_answers_are_recorded_not_dropped(answered_site):
    manifest = materialize(answered_site)
    assert manifest.body["module_answers"]["django.db"] == "postgres"


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_materializing_twice_appends_a_version(answered_site):
    first = materialize(answered_site)
    second = materialize(answered_site)
    assert (first.version, second.version) == (1, 2)
    assert Manifest.objects.filter(site=answered_site).count() == 2


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_manifest_rows_are_append_only(answered_site):
    """An in-place edit would silently rewrite the artifact a completed deploy claims
    to have used."""
    manifest = materialize(answered_site)
    manifest.body = {"tampered": True}
    with pytest.raises(ValueError, match="append-only"):
        manifest.save()


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_materialize_does_not_read_the_project_from_disk(answered_site):
    """Stability: the folder may have moved or been deleted since the scan. An
    ordinary user action must not become a 500."""
    answered_site.project.local_path = "/nonexistent/path/that/is/gone"
    answered_site.project.source_kind = "local_path"
    answered_site.project.save()
    assert materialize(answered_site).version == 1


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_materialize_is_audited(answered_site):
    from core.models import AuditEvent

    materialize(answered_site)
    event = AuditEvent.objects.filter(action="manifest_materialized").first()
    assert event is not None
    assert event.detail["version"] == 1
    assert SECRET_VALUE not in str(event.detail)


# ── API surface ───────────────────────────────────────────────────────────────

@pytest.fixture
def auth_client(client, django_user_model):
    """A logged-in operator WITH a confirmed second factor.

    The confirmed device is not decoration: EnrollmentRequiredMiddleware (§6.10)
    fail-closes every /api/ path for a user who has not enrolled, so a session alone
    reaches nothing. See test_wizard_endpoints_are_behind_the_2fa_gate.
    """
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_get_wizard_returns_questions_and_state(auth_client, site):
    response = auth_client.get(reverse("wizard", args=[site.pk]))
    assert response.status_code == 200
    body = response.json()
    assert any(q["id"] == "site.domain" for q in body["questions"])
    assert body["can_materialize"] is False


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_patch_bad_answer_returns_400_and_audits(auth_client, site):
    from core.models import AuditEvent

    response = auth_client.patch(
        reverse("wizard", args=[site.pk]),
        data={"answers": {"django.db": "oracle"}},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert AuditEvent.objects.filter(action="input_rejected").exists()


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_materialize_endpoint_refuses_with_409_not_500(auth_client, site):
    """A well-formed request against a site that isn't ready is a conflict, not a
    server error — and never a traceback."""
    response = auth_client.post(reverse("manifest", args=[site.pk]),
                                data={}, content_type="application/json")
    assert response.status_code == 409
    assert response.json()["code"] == "answers_missing"


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_materialize_endpoint_creates_and_returns_manifest(auth_client, answered_site):
    response = auth_client.post(reverse("manifest", args=[answered_site.pk]),
                                data={}, content_type="application/json")
    assert response.status_code == 201
    assert response.json()["version"] == 1

    latest = auth_client.get(reverse("manifest", args=[answered_site.pk]))
    assert latest.json()["version"] == 1


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_manifest_endpoint_404s_before_materialization(auth_client, site):
    assert auth_client.get(reverse("manifest", args=[site.pk])).status_code == 404


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_wizard_requires_authentication(client, site):
    assert client.get(reverse("wizard", args=[site.pk])).status_code in (401, 403)


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_wizard_endpoints_are_behind_the_2fa_gate(client, django_user_model, site):
    """A password alone must not reach the wizard: these endpoints accept secrets and
    build deployment artifacts. Middleware covers them automatically (§6.10 puts the
    gate in middleware so no future endpoint can forget it) — this pins that the new
    URL prefix really is covered, rather than assuming it."""
    user = django_user_model.objects.create_user(username="noenroll",
                                                 password="pw-1234567890")
    client.force_login(user)   # authenticated, no confirmed device
    for url in (reverse("wizard", args=[site.pk]),
                reverse("manifest", args=[site.pk]),
                reverse("readiness", args=[site.project.pk])):
        assert client.get(url).status_code == 403, url


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_readiness_endpoint_tiers_server_side(auth_client, project):
    project.scan_report = make_report(checks=[
        {"id": "b", "tier": "blocker", "title": "B"},
        {"id": "w", "tier": "warning", "title": "W"},
        {"id": "a", "tier": "advice", "title": "A"},
    ])
    project.save()
    body = auth_client.get(reverse("readiness", args=[project.pk])).json()
    assert [c["id"] for c in body["blockers"]] == ["b"]
    assert [c["id"] for c in body["warnings"]] == ["w"]
    assert [c["id"] for c in body["advice"]] == ["a"]


# ── kind drift across rescans (adversarial finding, 2026-08-09) ───────────────

def _report_with_kind(kind):
    return make_report(questions=[
        {"id": "django.env.API_KEY", "prompt": "Value for API_KEY", "kind": kind,
         "default": None, "choices": []},
    ])


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_plaintext_answer_is_scrubbed_when_question_becomes_secret(db):
    """Question kind is NOT stable across scans. A module may classify API_KEY as
    plain text today and correctly reclassify it as a secret after a scanner
    improvement — leaving a live credential in cleartext in a table nobody thinks of
    as holding credentials. Found by adversarial probe; no write-path test would
    have caught it."""
    project = Project.objects.create(name="drift", slug="drift",
                                     git_url="https://github.com/o/r.git",
                                     scan_report=_report_with_kind("text"))
    site = Site.objects.create(project=project, name="s")
    service.set_answers(site, {"django.env.API_KEY": "sk-live-LEAK"})
    assert WizardAnswer.objects.get(site=site).value == "sk-live-LEAK"

    project.scan_report = _report_with_kind("secret")
    project.save()

    scrubbed = service.scrub_downgraded_answers(site)
    assert scrubbed == ["django.env.API_KEY"]
    assert not WizardAnswer.objects.filter(site=site).exists()


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_scrub_is_audited_as_security(db):
    from core.models import AuditEvent

    project = Project.objects.create(name="drift2", slug="drift2",
                                     git_url="https://github.com/o/r.git",
                                     scan_report=_report_with_kind("text"))
    site = Site.objects.create(project=project, name="s")
    service.set_answers(site, {"django.env.API_KEY": "sk-live-LEAK"})
    project.scan_report = _report_with_kind("secret")
    project.save()
    service.scrub_downgraded_answers(site)

    event = AuditEvent.objects.filter(action="wizard_plaintext_answer_scrubbed").first()
    assert event is not None
    assert event.severity == AuditEvent.Severity.SECURITY
    assert "sk-live-LEAK" not in str(event.detail)


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_materialize_refuses_and_names_the_values_to_reenter(db):
    """Scrubbing silently would leave the operator with a site that won't start and
    no idea why. The refusal names each value and says to rotate it at the source."""
    project = Project.objects.create(name="drift3", slug="drift3",
                                     git_url="https://github.com/o/r.git",
                                     scan_report=_report_with_kind("text"))
    site = Site.objects.create(project=project, name="s")
    service.set_answers(site, {"site.domain": "d.example.com",
                               "django.env.API_KEY": "sk-live-LEAK"})
    project.scan_report = make_report(questions=[
        {"id": "django.env.API_KEY", "prompt": "Value for API_KEY", "kind": "secret",
         "default": None, "choices": []},
    ])
    project.save()

    with pytest.raises(MaterializeRefused) as exc:
        materialize(site)
    assert exc.value.code == "answers_need_reentry"
    assert exc.value.items[0]["id"] == "django.env.API_KEY"
    assert "rotate" in exc.value.message

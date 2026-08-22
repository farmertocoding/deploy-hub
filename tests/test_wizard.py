"""Wizard, materialization and manifest tests.

Organised by the five properties the 2026-08-09 design debate said this chunk must
hold: error-proofing on human input, secrets never leaving the vault, refusals that
name their cause, append-only manifests, and no crash paths on ordinary user actions.
"""
import json

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from dns_fixtures import default_dns_zone

from core.models import Project, Site
from deploys.models import Manifest
from scanner import core as scanner_core
from vault import service as vault_service
from vault.models import Secret
from wizard import questions as wizard_questions
from wizard import service
from wizard.materialize import MaterializeRefused, _apply_answers, materialize, preflight
from wizard.models import WizardAnswer
from wizard.questions import question_map, question_set

pytestmark = pytest.mark.django_db

SECRET_VALUE = "wizard-test-DB-PASSWORD-MARKER"


def make_report(*, checks=(), questions=(), draft=None):
    """A hand-built report, VERSIONED FROM THE SCANNER rather than from a literal.

    D-012 out of Phase 1 gave `preflight` a schema-skew refusal (R8-2): a stored report
    whose `schema_version` is not the current one is refused outright, because the fields
    of an older report do not mean what this code reads them to mean. A literal `1` here
    was fine while 1 was current and became "every wizard test materializes a refusal"
    the moment it was not — which is the right failure, in the wrong place. Read the
    version off `scanner.core` so these fixtures are always a CURRENT report; the skew
    itself is tested where it belongs, in tests/test_d012_out_of_phase_1.py.
    """
    return {
        "schema_version": scanner_core.SCHEMA_VERSION,
        "modules": ["django"],
        "checks": list(checks),
        "sandbox_jobs": [],
        "wizard_questions": list(questions),
        "manifest_draft": draft or {"schema_version": scanner_core.SCHEMA_VERSION,
                                    "deploy_strategy": "blue_green"},
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
    return Site.objects.create(project=project, name="demo-prod",
                               dns_zone=default_dns_zone())


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
@pytest.mark.req("P0-VALIDATION")
def test_an_unknown_question_400_carries_the_unknown_question_code(auth_client, site):
    """§4.5's code is the machine id. The message test next door cannot see it, so
    `code=` could become None / omitted / `UNKNOWN_QUESTION` with the suite green.
    The PATCH 400 is the contract the UI reads."""
    response = auth_client.patch(
        reverse("wizard", args=[site.pk]),
        data={"answers": {"not.a.question": "x"}},
        content_type="application/json",
    )
    assert response.status_code == 400
    field = response.json()["errors"]["not.a.question"]
    assert field[0]["code"] == "unknown_question"
    assert field[0]["message"] == "no such question for this project"


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


def _second_secret_question(project, qid="django.env.SECRET_KEY"):
    report = dict(project.scan_report)
    report["wizard_questions"] = list(report["wizard_questions"]) + [
        {"id": qid, "prompt": f"Value for {qid}", "kind": "secret",
         "default": None, "choices": []},
    ]
    project.scan_report = report
    project.save(update_fields=["scan_report"])
    return qid


def _copy_crypto_columns(src, dest_pk):
    Secret.objects.filter(pk=dest_pk).update(
        ciphertext=bytes(src.ciphertext),
        wrapped_dek=bytes(src.wrapped_dek),
        nonce=bytes(src.nonce),
    )
    return Secret.objects.get(pk=dest_pk)


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_aad_prevents_cut_and_paste_between_wizard_secrets_on_one_site(site, project):
    """Two env secrets on one site must not share AAD.

    The attack is DB write: copy ciphertext/wrapped_dek/nonce from qid A's vault
    row onto qid B's. WizardAnswer.secret_ref is left pointing at the same pks —
    the FK staying put is not the defence. Owner-only AAD (`env_bundle|site|{pk}`)
    decrypts the moved bytes; binding the question must not.
    """
    q_a = "django.env.DATABASE_PASSWORD"
    q_b = _second_secret_question(project)
    service.set_answers(site, {q_a: "DATABASE-PASSWORD", q_b: "DJANGO-SECRET-KEY"})
    victim = WizardAnswer.objects.get(site=site, question_id=q_a).secret_ref
    target = WizardAnswer.objects.get(site=site, question_id=q_b).secret_ref
    moved = _copy_crypto_columns(victim, target.pk)
    with pytest.raises(vault_service.VaultDecryptError):
        vault_service.get(moved)
    # Unmoved row still decrypts — the raise is AAD, not a broken KEK.
    assert vault_service.get(
        Secret.objects.get(pk=victim.pk)
    ).decode() == "DATABASE-PASSWORD"


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_wizard_secret_cut_and_paste_across_sites_still_fails(site, project):
    """Re-prove the existing cross-site swap: different sites, same qid, copy
    crypto columns, get raises. Binding AAD to the question must not flatten
    this (site pk stays in owner_id).
    """
    other = Site.objects.create(project=project, name="other",
                                dns_zone=default_dns_zone())
    qid = "django.env.DATABASE_PASSWORD"
    service.set_answers(site, {qid: "SITE-A-PASSWORD"})
    service.set_answers(other, {qid: "SITE-B-PASSWORD"})
    victim = WizardAnswer.objects.get(site=site, question_id=qid).secret_ref
    target = WizardAnswer.objects.get(site=other, question_id=qid).secret_ref
    moved = _copy_crypto_columns(victim, target.pk)
    with pytest.raises(vault_service.VaultDecryptError):
        vault_service.get(moved)


# ── materialization refusals ──────────────────────────────────────────────────

@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_unscanned_project_refuses_with_a_named_cause(db):
    bare = Project.objects.create(name="bare", slug="bare",
                                  git_url="https://github.com/o/r.git")
    bare_site = Site.objects.create(project=bare, name="s",
                                    dns_zone=default_dns_zone())
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
def test_issue_r9_sec_1_an_unknown_qid_is_not_written_into_the_frozen_manifest(
        answered_site):
    """R9-SEC-1. The catch-all `else` in `_apply_answers` wrote ANY answer row whose id
    was not `site.domain`, `site.exposure` or an `.env.` name into `module_answers` —
    including one whose id belongs to no question this project has.

    The existing residue test (tests/test_d012_out_of_phase_1.py) covers the BLOCKED
    path only: that report has blockers, so materialization refuses before
    `_apply_answers` runs at all, and the row's inertness is asserted about a call that
    never happened. On the unblocked path — this test — the row reached the manifest,
    which is an append-only, GET-returnable security record: `module_answers` is where a
    reader looks to see what the operator was asked and what they said, and a row nobody
    was ever asked lands there indistinguishable from one that was.

    The qid used is the shape the residue actually has on this fleet: a
    `scanner.test_material.*` confirm from before D-012 left Phase 1, whose question no
    live scanner emits any more.
    """
    WizardAnswer.objects.create(
        site=answered_site,
        question_id="scanner.test_material.deadbeefcafe",
        value="true", is_secret=False)

    manifest = materialize(answered_site)

    # The asked question is still recorded — this must not become "drop everything".
    assert manifest.body["module_answers"] == {"django.db": "postgres"}
    assert "deadbeefcafe" not in json.dumps(manifest.body)


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r9_sec_1_an_unknown_env_qid_cannot_write_a_name_into_the_bundle(
        answered_site):
    """The same row one namespace over, and it is the sharper half: `_env_name` matches
    on the substring `.env.` alone, so a residue id containing it took the branch ABOVE
    the catch-all and put a name of the row's choosing into `env_names` — the frozen
    list of variables a deploy injects — with its value in the vault env bundle.

    `known` is consulted before any branch for that reason: the qid filter is a property
    of the answer, not of the branch it happens to land in.
    """
    WizardAnswer.objects.create(
        site=answered_site,
        question_id="scanner.test_material.env.EVIL_TOKEN",
        value="injected", is_secret=False)

    manifest = materialize(answered_site)

    assert manifest.body["env_names"] == ["DATABASE_PASSWORD"]
    assert "EVIL_TOKEN" not in json.dumps(manifest.body)


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r9_sec_1_a_skipped_row_does_not_end_the_overlay(site, project):
    """The mutation gate's answer to the guard above: `continue` -> `break` survived 776
    tests, because in every one of them the unknown row happened to be the LAST answer
    the queryset returned and the two spellings did the same thing.

    That is the assertion-that-does-not-assert class this repo has cited sixteen times,
    on a security guard three days old. `_apply_answers` is called directly with an
    explicit list rather than through the queryset, because "the row before the known one"
    is the whole point and `WizardAnswer` declares no ordering — a test that relies on
    insertion order is pinning the database's mood, not the loop's contract.
    """
    known = question_map(project)
    answers = [
        WizardAnswer(site=site, question_id="scanner.test_material.deadbeefcafe",
                     value="true", is_secret=False),
        WizardAnswer(site=site, question_id="django.db", value="postgres",
                     is_secret=False),
    ]

    body = {}
    _apply_answers(body, site, answers, known)

    assert body["module_answers"] == {"django.db": "postgres"}


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r9_sec_1_a_secret_answer_with_no_env_name_writes_no_env_row(
        answered_site, project):
    """The other mutant the qid filter left alive, and it is the filter's own fault.

    `if name and answer.secret_ref is not None` -> `or` was killed before this round by
    some path that reached the secret branch with one of the two operands false. The only
    rows that did so were rows the filter now drops one line earlier, so the guard lost
    its coverage the moment it gained a gate — a mutation-shaped version of exactly what
    the fix was about.

    So the case is stated on its own terms: a secret question the project DOES have,
    whose id carries no `.env.` name. Under `and` it contributes nothing (there is no
    variable to inject); under `or` it appends `None` to `env_names`, and the frozen
    manifest's environment list is not a place a `None` may appear.
    """
    stored = WizardAnswer.objects.get(site=answered_site,
                                      question_id="django.env.DATABASE_PASSWORD")
    known = dict(question_map(project))
    known["django.token"] = scanner_core.WizardQuestion(
        id="django.token", prompt="A token", kind="secret")
    answers = [
        stored,
        WizardAnswer(site=answered_site, question_id="django.token",
                     is_secret=True, secret_ref=stored.secret_ref),
    ]

    body = {}
    _apply_answers(body, answered_site, answers, known)

    assert body["env_names"] == ["DATABASE_PASSWORD"]


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
def test_patch_save_body_persists_site_domain(auth_client, site):
    """The body `makeWizardHandlers.save` sends must persist against the live API.

    Save wraps the draft as `{answers: {qid: value}}`; AnswersSerializer requires
    that envelope. The answered domain is what the operator typed.
    """
    response = auth_client.patch(
        reverse("wizard", args=[site.pk]),
        data={"answers": {"site.domain": "app.example.com"}},
        content_type="application/json",
    )
    assert response.status_code == 200
    answered = response.json()["answered"]
    assert answered["site.domain"] == "app.example.com"


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_patch_empty_object_is_not_a_valid_save(auth_client, site):
    """`{}` is not a partial answer set — the `answers` key is required."""
    response = auth_client.patch(
        reverse("wizard", args=[site.pk]),
        data={},
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    errors = body.get("errors", body)
    assert "answers" in errors


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
@pytest.mark.req("P0-VALIDATION")
@pytest.mark.req("VAL-45-REJECTED-INPUT-AUDITED")
def test_patch_bad_answer_returns_400_and_audits(auth_client, site):
    from core.models import AuditEvent
    from wizard.questions import coerce_answer, question_map

    question = question_map(site.project)["django.db"]
    with pytest.raises(ValidationError) as coerced:
        coerce_answer(question, "oracle")

    response = auth_client.patch(
        reverse("wizard", args=[site.pk]),
        data={"answers": {"django.db": "oracle"}},
        content_type="application/json",
    )
    assert response.status_code == 400
    field = response.json()["errors"]["django.db"]
    assert {"code", "message", "hint"} <= set(field[0])
    assert field[0]["code"] == coerced.value.code
    assert field[0]["message"] == coerced.value.message
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
    site = Site.objects.create(project=project, name="s",
                               dns_zone=default_dns_zone())
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
    site = Site.objects.create(project=project, name="s",
                               dns_zone=default_dns_zone())
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
    site = Site.objects.create(project=project, name="s",
                               dns_zone=default_dns_zone())
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


# ── F7-lite: the project list the readiness screen renders from ──────────────────

@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_project_list_reports_tier_counts_and_manifest_currency(auth_client):
    """The list endpoint carries tier COUNTS (cheap) and the one freshness fact the
    data model can answer honestly: is the latest manifest built from the CURRENT
    scan? (manifest_current: None = never materialized, True = current, False = the
    scan moved on.)"""
    report = make_report(checks=[{"id": "w1", "tier": "warning", "title": "w",
                                  "detail": "", "fix_hint": ""}])
    project = Project.objects.create(name="listme", slug="listme",
                                     git_url="https://github.com/o/r.git",
                                     scan_report=report)
    site = Site.objects.create(project=project, name="prod",
                               dns_zone=default_dns_zone())

    payload = auth_client.get("/api/v1/projects/").json()
    row = next(p for p in payload if p["slug"] == "listme")
    assert row["tiers"] == {"blocker": 0, "warning": 1, "advice": 0,
                            "pending_sandbox": 0}
    assert row["sites"][0]["latest_manifest_version"] is None
    assert row["sites"][0]["manifest_current"] is None

    service.set_answers(site, {"site.domain": "l.example.com"})
    materialize(site, confirm_warnings=True)
    row = next(p for p in auth_client.get("/api/v1/projects/").json()
               if p["slug"] == "listme")
    assert row["sites"][0]["latest_manifest_version"] == 1
    assert row["sites"][0]["manifest_current"] is True

    # The scan moves on -> the manifest is honestly stale.
    changed = make_report(checks=[{"id": "w1", "tier": "warning", "title": "w",
                                   "detail": "", "fix_hint": ""}])
    changed["checks"].append({"id": "new.advice", "tier": "advice",
                              "title": "new", "detail": "", "fix_hint": ""})
    project.scan_report = changed
    project.save()
    row = next(p for p in auth_client.get("/api/v1/projects/").json()
               if p["slug"] == "listme")
    assert row["sites"][0]["manifest_current"] is False


# ── the mutation gate's pins (spec-mutation-gate.md) ──────────────────────────
#
# Everything below was written because `make mutation` said so: each test names a
# mutation of `wizard/questions.py` or `wizard/materialize.py` that the suite could not
# tell from the real code. They are ordinary regression tests — the gate is only the
# thing that FOUND them, the same way a reviewer finds a hollow assertion by hand, and
# the reason there are so many at once is that this is the first honest run.
#
# The recurring shape they close is worth naming, because it is not "we forgot a test":
# almost every one of these lines WAS executed by an existing test, and the assertion
# next to it looked only at whether an exception was raised or whether a list was
# non-empty. The code was covered and the BEHAVIOUR was not.


def _question(kind, **kw):
    return scanner_core.WizardQuestion(id="q", kind=kind, prompt="p", **kw)


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
@pytest.mark.parametrize("question,value,message,code", [
    (_question("text"), None, "an answer is required", "required"),
    (_question("secret"), 7, "a secret value must be a non-empty string", "invalid"),
    (_question("secret"), "", "a secret value must be a non-empty string", "invalid"),
    (_question("domain"), 7, "expected a domain name", "invalid"),
    (_question("text"), 7, "expected text", "invalid"),
    (_question("text"), "   ", "an answer is required", "required"),
    (_question("text"), "x" * 2049, "answer is too long", "too_long"),
    (_question("choice", choices=["a", "b"]), "c",
     "'c' is not one of: a, b", "invalid_choice"),
    (_question("bool"), "yes", "expected true or false", "invalid"),
    (_question("number"), True, "expected a number", "invalid"),
    (_question("number"), "seven", "expected a number", "invalid"),
    (_question("number"), 1.5, "expected a number", "invalid"),
    (_question("wat"), "x", "unsupported question kind 'wat'", "invalid"),
])
def test_every_answer_refusal_carries_its_own_message_and_code(question, value,
                                                               message, code):
    """One row per `raise` in `coerce_answer`, asserting BOTH halves of the refusal.

    The whole module exists for error-proofing (its docstring: "Error-proofing is the
    whole job of this module"), and the refusal's two halves have two different readers:
    the `code` is what the client branches on and the message is what the operator
    reads. Every existing test here asserted at most one of them — several asserted only
    that *something* was raised — so the message text, the `code=` keyword, and in four
    places the message argument itself could all be removed and the suite stayed green.

    Asserting the exact sentence is not copy-freezing in this codebase: these strings ARE
    the product surface the wizard shows, the same way the scanner's refusals are, and
    `tests/test_scanner_declarations.py` has pinned refusal phrases since round 1.
    """
    with pytest.raises(ValidationError) as caught:
        wizard_questions.coerce_answer(question, value)

    assert caught.value.messages == [message]
    assert caught.value.code == code


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
@pytest.mark.parametrize("question,value,expected", [
    (_question("secret"), "s3cret", "s3cret"),
    (_question("text"), "  padded  ", "padded"),
    (_question("text"), "x" * 2048, "x" * 2048),
    (_question("choice", choices=["a", "b"]), "b", "b"),
    (_question("bool"), True, True),
    (_question("bool"), "TRUE", True),
    (_question("bool"), "False", False),
    (_question("number"), 7, 7),
    (_question("number"), " 8 ", 8),
])
def test_every_accepted_answer_is_coerced_to_its_declared_type(question, value,
                                                               expected):
    """The other side of the same table, and it is what pins the BOUNDARIES.

    `len(value) > 2048` could become `>= 2048` and nothing noticed, because the only
    long-text test used a value far over the line — the classic off-by-one the scanner
    module's own cap tests already guard against in both directions.
    """
    coerced = wizard_questions.coerce_answer(question, value)
    assert coerced == expected
    assert type(coerced) is type(expected)


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_a_module_question_is_carried_across_field_by_field(project):
    """`question_set` copies four fields out of the scan report, and three of them
    could be replaced by `None` — or read from the wrong key — without a test noticing:
    every existing assertion here looks at `q.id` alone."""
    question = {q.id: q for q in question_set(project)}["django.db"]

    assert question.prompt == "Database"
    assert question.kind == "choice"
    assert question.default == "postgres"
    assert question.choices == ["postgres", "sqlite"]


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_a_module_question_missing_prompt_and_kind_falls_back_to_id_and_text(project):
    """The two `.get(key, fallback)` defaults, which are the reason a half-written
    module question renders as something rather than as a blank row."""
    project.scan_report = make_report(questions=[{"id": "mod.thing"}])
    project.save()

    question = {q.id: q for q in question_set(project)}["mod.thing"]
    assert question.prompt == "mod.thing"
    assert question.kind == "text"
    assert question.default is None
    assert question.choices == []


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_the_same_module_question_asked_twice_is_one_question(project):
    """De-duplication is by the id that was SEEN, and `seen.add(qid)` could become
    `seen.add(None)` with the suite green — the alias test above only exercises the
    base-question half of `seen`, which is built by a different line."""
    project.scan_report = make_report(questions=[
        {"id": "mod.thing", "prompt": "first"},
        {"id": "mod.thing", "prompt": "second"},
    ])
    project.save()

    ids = [q.id for q in question_set(project)]
    assert ids.count("mod.thing") == 1
    assert {q.id: q for q in question_set(project)}["mod.thing"].prompt == "first"


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_every_bad_field_in_one_patch_is_reported_by_its_own_message(site):
    """All-or-nothing rejection reports the MESSAGE for each field, not the code, and
    it reports every field rather than stopping at the first.

    Two mutations lived here: the per-field `continue` becoming `break` (only the first
    unknown id would ever be reported) and `[v[0]]` becoming `[v[1]]` (the operator gets
    the machine code `unknown_question` where the sentence should be). Both survived
    because the existing all-or-nothing test asserts on `WizardAnswer.objects.count()`
    and never opens the error.
    """
    with pytest.raises(ValidationError) as caught:
        service.set_answers(site, {"nope.one": "x", "nope.two": "y",
                                   "django.workers": "seven"})

    errors = caught.value.message_dict
    assert set(errors) == {"nope.one", "nope.two", "django.workers"}
    assert errors["nope.one"] == ["no such question for this project"]
    assert errors["django.workers"] == ["expected a number"]


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_a_refusal_carries_its_message_through_every_surface_it_has(site):
    """`MaterializeRefused` publishes the same refusal four ways — `str()`, `.message`,
    `.problems[0]` and `.as_dict()` — and only the first of them was asserted anywhere,
    so `super().__init__(message)` could pass `None` and every key of both dicts could
    be renamed with the suite green. `as_dict()` is the 409 body: its keys are the API
    contract."""
    refused = MaterializeRefused("some_code", "some detail", [{"id": "x"}])

    assert str(refused) == "some detail"
    assert refused.problems == [
        {"code": "some_code", "detail": "some detail", "items": [{"id": "x"}]}]
    assert refused.as_dict() == {
        "code": "some_code", "detail": "some detail", "items": [{"id": "x"}],
        "problems": refused.problems}

    explicit = MaterializeRefused("a", "b", problems=[{"code": "z"}])
    assert explicit.problems == [{"code": "z"}]
    assert explicit.items == []


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_the_scan_report_hash_is_canonical_and_key_order_independent():
    """`scan_report_hash` is the manifest's claim about WHICH scan it was built from, so
    two spellings of the same report must hash alike and the encoding must be pinned.
    `sort_keys=True` and `separators=(",", ":")` could both be dropped and nothing
    moved — the only existing assertion is `assert manifest.scan_report_hash`, which is
    true of any string at all."""
    import hashlib as _hashlib

    from wizard.materialize import report_hash

    assert report_hash({"a": 1, "b": 2}) == report_hash({"b": 2, "a": 1})
    assert report_hash({"a": 1, "b": 2}) == _hashlib.sha256(
        b'{"a":1,"b":2}').hexdigest()


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
@pytest.mark.parametrize("code,detail", [
    ("scan_required", "this project has not been scanned yet"),
    ("scan_required",
     "this project's scan predates the current report schema and must be re-run"),
    ("blockers_present",
     "the readiness report has blockers; these must be fixed and the project re-scanned"),
    ("answers_missing", "required questions are unanswered"),
    ("answers_need_reentry",
     "these values are now handled as secrets and must be entered again; the previously "
     "stored plaintext has been deleted and should be rotated at the source"),
])
def test_every_preflight_problem_states_its_own_cause(site, code, detail, monkeypatch):
    """One row per problem `preflight` can append, asserting the sentence the operator
    reads and the `code` the UI branches on.

    WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE is the requirement these details ARE — "show the
    causal step, not the failed one" — and every existing test asserts the `code` alone,
    so all five sentences could be replaced with any other text. The dict keys go with
    them: `"detail"` could be renamed and only this asserts otherwise.
    """
    project = site.project
    if code == "scan_required" and "scanned yet" in detail:
        project.scan_report = {}
    elif code == "scan_required":
        project.scan_report = dict(project.scan_report, schema_version=-1)
    elif code == "blockers_present":
        project.scan_report = make_report(
            checks=[{"id": "core.secret-scan", "title": "Secrets", "tier": "blocker"}])
    elif code == "answers_need_reentry":
        monkeypatch.setattr("wizard.service.downgraded_answers",
                            lambda _site: ["django.env.DATABASE_PASSWORD"])
    project.save()

    problems = {p["code"]: p for p in preflight(site)}
    assert code in problems, problems
    assert problems[code]["detail"] == detail
    assert set(problems[code]) == {"code", "detail", "items"}
    if code == "answers_need_reentry":
        # The scrubbed answers are listed the same way the missing ones are — by their
        # question's own words — and this is the second copy of that item shape, so it
        # needs its own assertion: `{id, prompt}` could be renamed here alone, and the
        # `qid in known` condition could be inverted here alone.
        assert problems[code]["items"] == [
            {"id": "django.env.DATABASE_PASSWORD",
             "prompt": "Value for DATABASE_PASSWORD"}]


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_an_unanswered_question_is_listed_by_its_prompt_not_by_its_id(site):
    """`known[qid].prompt if qid in known else qid` — the condition could be inverted
    and every operator would see `site.domain` where the question's own words belong.
    The `items` payload is what the UI renders; nothing looked inside it."""
    problems = {p["code"]: p for p in preflight(site)}

    assert problems["answers_missing"]["items"] == [
        {"id": "site.domain",
         "prompt": "Public domain for this site (e.g. app.example.com)"}]


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_a_listed_blocker_carries_its_id_and_title(project, site):
    """The blocker items are `{id, title}` copied out of the report; both keys could be
    renamed with the suite green because the only assertion was on the LENGTH of the
    list."""
    project.scan_report = make_report(
        checks=[{"id": "core.secret-scan", "title": "Secrets", "tier": "blocker"}])
    project.save()

    problems = {p["code"]: p for p in preflight(site)}
    assert problems["blockers_present"]["items"] == [
        {"id": "core.secret-scan", "title": "Secrets"}]


@pytest.mark.req("WIZ-MATERIALIZE-REFUSAL-NAMES-CAUSE")
def test_a_report_with_no_checks_key_is_read_without_crashing(project, site):
    """`report.get("checks", [])` in `preflight` and in `warnings_for` — the `[]`
    fallback could be dropped or turned into `None` and no test noticed, because every
    fixture report in this suite carries a `checks` key. A stored report written by an
    older scanner need not, and `for check in None` is a 500 on an ordinary GET."""
    from wizard.materialize import warnings_for

    report = make_report()
    del report["checks"]
    project.scan_report = report
    project.save()

    assert [p["code"] for p in preflight(site)] == ["answers_missing"]
    assert warnings_for(site) == []


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_the_frozen_body_records_the_site_it_was_built_for(answered_site):
    """`body["site"]` is the manifest's copy of the site identity; the whole assignment
    could become `None` and each of its three keys could be renamed, with nothing
    asserting otherwise."""
    manifest = materialize(answered_site)

    assert manifest.body["site"] == {"id": answered_site.pk, "name": "demo-prod",
                                     "domain": "demo.example.com"}


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_an_exposure_answer_reaches_the_frozen_body(answered_site):
    """`site.exposure` is the one answer whose whole effect is one line of
    `_apply_answers`, and no test read it back out of the manifest."""
    service.set_answers(answered_site, {"site.exposure": "mesh_only"})

    assert materialize(answered_site).body["exposure"] == "mesh_only"


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_the_domain_answer_is_written_back_to_the_site_row(answered_site):
    """`site.domain = answer.value` and the `save(update_fields=["domain"])` behind it:
    the manifest tests all read the BODY, so the row update was asserted nowhere."""
    materialize(answered_site)
    answered_site.refresh_from_db()

    assert answered_site.domain == "demo.example.com"


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_the_site_write_back_touches_the_domain_column_and_nothing_else(answered_site):
    """`save(update_fields=["domain"])` is scoped on purpose: `_apply_answers` is handed
    a site OBJECT, and a full save would write back every attribute that object is
    carrying — including any a caller had already changed in memory for its own reasons.
    Nothing asserted the scope, so the argument could be dropped and the only symptom
    would be a column quietly clobbered from stale memory.

    Called at `_apply_answers` so the in-memory divergence can be staged; through
    `materialize` there is nothing to diverge from."""
    from wizard.materialize import _apply_answers

    answers = list(WizardAnswer.objects.filter(site=answered_site))
    answered_site.name = "clobbered-in-memory"

    _apply_answers({}, answered_site, answers,
                   wizard_questions.question_map(answered_site.project))

    answered_site.refresh_from_db()
    assert answered_site.domain == "demo.example.com"
    assert answered_site.name == "demo-prod"


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_the_env_bundle_round_trips_the_secret_answer_it_was_built_from(answered_site):
    """The bundle is the only place a secret value legitimately exists after
    materialization, and the existing tests assert it is NOT in the body — nothing
    asserted it IS in the bundle, so the decrypt-and-decode line could break outright."""
    import json as _json

    from vault.models import Secret

    manifest = materialize(answered_site)
    bundle = Secret.objects.get(pk=manifest.body["env_bundle_ref"])
    values = _json.loads(vault_service.get(bundle, reason="test"))

    assert values == {"DATABASE_PASSWORD": SECRET_VALUE}


@pytest.mark.req("SEC-69-ENVELOPE-ENCRYPTION")
def test_the_materializing_operator_is_named_on_the_vault_read(answered_site,
                                                               django_user_model):
    """Round-2 R2-1 fixed exactly this — `actor` was omitted on the vault read, so the
    "every use is recorded" audit row had nobody attributed to it — and the fix was
    pinned by nothing: `actor=` and `reason=` could both be dropped again."""
    from core.models import AuditEvent

    actor = django_user_model.objects.create_user(username="op", password="x")   # nosec B106
    materialize(answered_site, actor=actor)

    used = AuditEvent.objects.filter(action="vault-secret-used").first()
    assert used is not None
    assert used.actor_id == actor.pk
    assert used.detail["reason"] == f"materialize {answered_site.pk}"


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_a_secret_answer_does_not_stop_the_answers_after_it(answered_site):
    """`continue` in the secret branch could become `break`, dropping every answer that
    comes after the first secret one.

    Called at `_apply_answers` with the list built HERE, secret first, because that is
    the only way to state the case: the walk reads an unordered queryset, so a test that
    goes through `materialize` is asserting whatever order the database happened to
    return — which is exactly the kind of accidental green this gate exists to remove.
    """
    from wizard.materialize import _apply_answers

    service.set_answers(answered_site, {"site.exposure": "mesh_only"})
    by_id = {a.question_id: a
             for a in WizardAnswer.objects.filter(site=answered_site)}
    ordered = [by_id["django.env.DATABASE_PASSWORD"], by_id["site.domain"],
               by_id["site.exposure"], by_id["django.db"]]

    body = {}
    env_values = _apply_answers(body, answered_site, ordered,
                                wizard_questions.question_map(answered_site.project))

    assert body["env_names"] == ["DATABASE_PASSWORD"]
    assert env_values == {"DATABASE_PASSWORD": SECRET_VALUE}
    assert body["domain"] == "demo.example.com"
    assert body["exposure"] == "mesh_only"
    assert body["module_answers"]["django.db"] == "postgres"


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_a_secret_answer_outside_the_env_namespace_contributes_no_env_name(site):
    """`if name and answer.secret_ref is not None` — with `and` weakened to `or`, a
    secret answer whose question id carries no `.env.` marker appends `None` to
    `env_names`. The guard's two halves were tested together and never apart."""
    service.set_answers(site, {"site.domain": "demo.example.com"})
    secret = vault_service.put(kind=Secret.Kind.API_TOKEN, owner_type="site",
                               owner_id=str(site.pk), plaintext=b"x")
    WizardAnswer.objects.create(site=site, question_id="django.token", value=None,
                                is_secret=True, secret_ref=secret)

    assert materialize(site).body["env_names"] == []


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_the_env_marker_splits_on_the_first_occurrence_only():
    """`question_id.split(".env.", 1)[1]` — `rsplit`, a dropped maxsplit and a maxsplit
    of 2 all produce a different environment variable NAME, which is the string the
    deployed process reads. A question id can carry the marker twice; nothing said which
    side of it the name is on."""
    from wizard.materialize import _env_name

    assert _env_name("django.env.A.env.B") == "A.env.B"
    assert _env_name("django.env.DATABASE_URL") == "DATABASE_URL"
    assert _env_name("django.database_url") is None


# ── R10-A5: the readiness body, spelled once ──────────────────────────────────
#
# The tier grouping and its four not-quite-plural key names were written out three
# times: in `ReadinessView.get`, and once in each half of
# `scripts_dev/sim_fixture_payloads.py` — the file whose entire job is proving that
# `frontend/src/sim.js` is what this endpoint returns. A harness that re-implements the
# endpoint proves sim.js matches a SECOND implementation of it, which is the
# fixture-rot class three rounds running have now filed.

@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_issue_r10_a5_the_readiness_wire_output_is_unchanged(auth_client, project):
    """The pin the refactor had to survive: the exact body, key for key, for a report
    carrying one check of every tier. `wizard/views.py` is not on the sensitive-path
    list, and the serializers are untouched, so nothing else would have noticed a
    grouping that quietly moved an `advice` into `warnings`.
    """
    project.scan_report = make_report(checks=[
        {"id": "b", "tier": "blocker", "title": "B"},
        {"id": "w", "tier": "warning", "title": "W"},
        {"id": "a", "tier": "advice", "title": "A"},
        {"id": "s", "tier": "pending_sandbox", "title": "S"},
        {"id": "o", "tier": "ok", "title": "O"},
    ])
    project.save()

    body = auth_client.get(reverse("readiness", args=[project.pk])).json()

    assert sorted(body) == ["advice", "blockers", "modules", "pending_sandbox",
                            "scanned_at", "summary", "warnings"]
    assert [c["id"] for c in body["blockers"]] == ["b"]
    assert [c["id"] for c in body["warnings"]] == ["w"]
    assert [c["id"] for c in body["advice"]] == ["a"]
    assert [c["id"] for c in body["pending_sandbox"]] == ["s"]
    # `ok` is in the summary counts and in no list — the payload groups the four tiers
    # the screens render, and that is what the drift gate compares.
    listed = [c["id"] for key in ("blockers", "warnings", "advice", "pending_sandbox")
              for c in body[key]]
    assert listed == ["b", "w", "a", "s"]


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_issue_r10_a5_the_view_returns_the_shared_body(auth_client, project,
                                                       monkeypatch):
    """…and it returns it by CALLING the shared function, which is the claim a second
    copy in the view would silently break. Patching `readiness_body` is how a test
    asserts there is one of it."""
    from wizard import views

    project.scan_report = make_report(checks=[
        {"id": "b", "tier": "blocker", "title": "B"}])
    project.save()
    monkeypatch.setattr(views, "readiness_body",
                        lambda report, scanned_at: {"sentinel": True})

    assert auth_client.get(reverse("readiness", args=[project.pk])).json() == {
        "sentinel": True}


@pytest.mark.req("WIZ-ANSWER-VALIDATION")
def test_issue_r10_a5_the_payload_keys_are_the_endpoints_own(project):
    """The key list the drift gate reads a payload with is the view's, not a fourth
    copy. Two of the four are not the tier name — a copy that pluralized all four would
    read `advices`/`pending_sandboxs`, find nothing, and report "no findings"."""
    from wizard.views import READINESS_KEYS, READINESS_TIERS, readiness_body

    body = readiness_body({"checks": [{"id": "x", "tier": t} for t in READINESS_TIERS]},
                          None)

    assert READINESS_KEYS == ("blockers", "warnings", "advice", "pending_sandbox")
    for key in READINESS_KEYS:
        assert body[key], f"{key} is not a key of the payload this endpoint returns"


# ── R11-A1: the project row, spelled once ─────────────────────────────────────
#
# R10-A5 extracted `readiness_body` because the fixture harness re-implemented the
# readiness endpoint. The row endpoint next to it was the same arrangement one screen
# over: `ProjectListView.get` composes the project row inline, and
# `scripts_dev/sim_fixture_payloads.py::build.project_row` composes it again — the file
# whose whole job is proving that `frontend/src/sim.js` is what these endpoints return.
#
# And this pair had ALREADY DIVERGED, which is what makes it a finding rather than a
# tidiness note. The harness pinned `.order_by("pk")` on the sites; the view iterated
# `project.sites.all()`, and `Site` declares no `Meta.ordering` — so the order of the
# sites under a project row was whatever the database felt like returning, in a UI list
# an operator picks a site out of. The tier tuple was restated too, four strings that
# `READINESS_TIERS` already spells.

@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r11_a1_the_project_row_wire_output_is_unchanged(auth_client):
    """The pin the refactor had to survive: the exact row, key for key, for a project
    with one check of every tier and two sites, one of which has materialized.

    Written against the endpoint rather than against the extracted function on purpose —
    this is the wire, and it is what a fixture regenerated through the harness is going
    to be compared with.
    """
    from wizard.views import READINESS_TIERS

    project = Project.objects.create(
        name="rowpin", slug="rowpin", git_url="https://github.com/o/r.git",
        scan_report=make_report(checks=[
            {"id": "b", "tier": "blocker", "title": "B"},
            {"id": "w", "tier": "warning", "title": "W"},
            {"id": "a", "tier": "advice", "title": "A"},
            {"id": "s", "tier": "pending_sandbox", "title": "S"},
            {"id": "o", "tier": "ok", "title": "O"},
        ]))
    first = Site.objects.create(project=project, name="prod", domain="p.example.com",
                                dns_zone=default_dns_zone())
    Site.objects.create(project=project, name="staging",
                        dns_zone=default_dns_zone())

    row = next(p for p in auth_client.get("/api/v1/projects/").json()
               if p["slug"] == "rowpin")

    assert sorted(row) == ["id", "name", "scanned_at", "sites", "slug", "tiers"]
    assert tuple(row["tiers"]) == READINESS_TIERS, (
        "the row's tier counts are the tier tuple the readiness payload groups by, in "
        "its order — a second spelling here is four strings that can disagree")
    assert row["tiers"] == {"blocker": 1, "warning": 1, "advice": 1,
                            "pending_sandbox": 1}
    assert row["sites"] == [
        {"id": first.pk, "name": "prod", "domain": "p.example.com",
         "latest_manifest_version": None, "manifest_current": None,
         "cert_refusal": None},
        {"id": first.pk + 1, "name": "staging", "domain": "",
         "latest_manifest_version": None, "manifest_current": None,
         "cert_refusal": None},
    ]


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r11_a1_the_view_returns_the_shared_row_body(auth_client, monkeypatch):
    """…and it returns it by CALLING the shared function, which is the claim a second
    copy in the view would silently break. The same patch-the-seam pin R10-A5 put on
    `readiness_body`: an equivalence test passes while there are two implementations
    that happen to agree, and this one does not."""
    from wizard import views

    Project.objects.create(name="callme", slug="callme",
                           git_url="https://github.com/o/r.git", scan_report={})
    monkeypatch.setattr(views, "project_row_body", lambda project: {"sentinel": True})

    assert auth_client.get("/api/v1/projects/").json() == [{"sentinel": True}]


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r11_a1_sites_are_listed_in_a_pinned_order(auth_client):
    """THE DIVERGENCE, made reproducible.

    `Site` has no `Meta.ordering`, so `project.sites.all()` carries no ORDER BY and the
    row's site list was the database's choice — stable on SQLite today, and not a
    promise anywhere. The harness had `.order_by("pk")`; the view had nothing; the two
    agreed only because nothing had made them disagree yet.

    A prefetch carrying the opposite order is how a caller can hand the body its sites
    in another sequence WITHOUT changing the database — which is exactly what a future
    `Meta.ordering`, a different backend, or a `prefetch_related(Prefetch(...))` added
    for an unrelated reason would do. The row must come out in pk order regardless.
    """
    from django.db.models import Prefetch

    from wizard.views import project_row_body

    project = Project.objects.create(name="ordered", slug="ordered",
                                     git_url="https://github.com/o/r.git",
                                     scan_report={})
    ids = [Site.objects.create(project=project, name=f"s{i}",
                               dns_zone=default_dns_zone()).pk for i in range(4)]

    reversed_prefetch = (Project.objects
                         .prefetch_related(Prefetch("sites",
                                                    queryset=Site.objects.order_by("-pk")))
                         .get(pk=project.pk))
    assert [s.pk for s in reversed_prefetch.sites.all()] == sorted(ids, reverse=True)

    assert [s["id"] for s in project_row_body(reversed_prefetch)["sites"]] == ids
    row = next(p for p in auth_client.get("/api/v1/projects/").json()
               if p["slug"] == "ordered")
    assert [s["id"] for s in row["sites"]] == ids


@pytest.mark.req("WIZ-V5-ONE-MANIFEST")
def test_issue_r11_a1_the_row_body_reads_the_current_report(auth_client):
    """`manifest_current` is the one derived field in the row, and the extraction moved
    the `report_hash` call with it. A frozen manifest is current until the scan moves."""
    from wizard.views import project_row_body

    report = make_report(checks=[{"id": "w1", "tier": "warning", "title": "w"}])
    project = Project.objects.create(name="fresh", slug="fresh",
                                     git_url="https://github.com/o/r.git",
                                     scan_report=report)
    site = Site.objects.create(project=project, name="prod",
                               dns_zone=default_dns_zone())
    service.set_answers(site, {"site.domain": "f.example.com"})
    materialize(site, confirm_warnings=True)

    assert project_row_body(project)["sites"][0]["manifest_current"] is True

    moved = make_report(checks=[{"id": "w1", "tier": "warning", "title": "w"},
                                {"id": "a1", "tier": "advice", "title": "a"}])
    project.scan_report = moved
    project.save()
    project.refresh_from_db()

    assert project_row_body(project)["sites"][0]["manifest_current"] is False

"""The only writer of WizardAnswer rows.

Everything funnels through `set_answers()` so the "a secret value never lands in the
answers table" rule has exactly one place to hold. A view that built WizardAnswer
objects directly would work fine on the happy path and quietly write plaintext the
first time someone added a question of kind=secret.
"""
from django.db import transaction

from core.audit import audit
from vault import service as vault_service
from vault.models import Secret

from .models import WizardAnswer
from .questions import question_map, validate_answers


def _row(*, value=None, ref=None, is_secret=False, actor=None):
    """One definition of an answer row's shape.

    Also the single suppression point for bandit B105, which pattern-matches any dict
    key containing "secret" as a hardcoded password. Renaming the field to dodge that
    was considered and rejected: §6.9 classifies data as Secret / Sensitive /
    Operational, this is precisely the Secret tier, and bending the domain vocabulary
    to satisfy a substring match would make the code less accurate, not safer.
    """
    return {"value": value, "secret_ref": ref, "is_secret": is_secret,  # nosec B105
            "answered_by": actor}


@transaction.atomic
def set_answers(site, incoming: dict, *, actor=None):
    """Validate and persist a partial answer set. All-or-nothing.

    Returns the list of question ids written. Raises django ValidationError with a
    per-field error map, which the DRF layer renders in the §4.5 error shape and the
    exception handler audits (VAL-45-REJECTED-INPUT-AUDITED).
    """
    cleaned = validate_answers(site.project, incoming)
    written = []

    for qid, (question, value) in cleaned.items():
        if question.kind == "secret":
            secret = vault_service.put(
                kind=Secret.Kind.ENV_BUNDLE,
                owner_type="site",
                owner_id=site.pk,
                plaintext=value.encode("utf-8"),
                actor=actor,
            )
            existing = WizardAnswer.objects.filter(site=site, question_id=qid).first()
            previous = existing.secret_ref if existing else None
            WizardAnswer.objects.update_or_create(
                site=site, question_id=qid,
                defaults=_row(ref=secret, is_secret=True, actor=actor),
            )
            # The superseded ciphertext is deleted, not orphaned: a rotated database
            # password left lying in the vault is a credential nobody is tracking.
            # PROTECT on the FK means this only fires once nothing references it.
            if previous is not None and previous.pk != secret.pk:
                previous.delete()
            audit("wizard_secret_answered", site, actor=actor, source="api",
                  question_id=qid, fingerprint=secret.fingerprint)
        else:
            WizardAnswer.objects.update_or_create(
                site=site, question_id=qid,
                defaults=_row(value=value, actor=actor),
            )
        written.append(qid)

    audit("wizard_answers_saved", site, actor=actor, source="api",
          question_ids=sorted(written))
    return sorted(written)


def scrub_downgraded_answers(site):
    """Delete plaintext answers whose question is NOW classified as a secret.

    THE BUG THIS EXISTS FOR (found by adversarial probe, 2026-08-09). Question kind is
    not stable across scans: a module may classify `API_KEY` as plain text today and
    correctly reclassify it as a secret after a scanner improvement. The answer row
    written under the old classification stays in the database in cleartext forever —
    a live credential in a table nobody thinks of as holding credentials, invisible to
    every test that only checks the write path.

    Returns the question ids scrubbed, so the caller can tell the operator exactly
    which values to re-enter. Deleting is right and re-encrypting is wrong: the
    plaintext has already been at rest, so it must be rotated at the source, not
    laundered into the vault where it would look freshly-protected.
    """
    known = question_map(site.project)
    scrubbed = []
    for answer in WizardAnswer.objects.filter(site=site, is_secret=False):
        question = known.get(answer.question_id)
        if question is not None and question.kind == "secret":
            answer.delete()
            scrubbed.append(answer.question_id)
    if scrubbed:
        audit("wizard_plaintext_answer_scrubbed", site, source="system",
              severity="security", question_ids=sorted(scrubbed))
    return sorted(scrubbed)


def answered_state(site):
    """What the client needs to re-render the form: plain values, secrets as metadata.

    A secret is reported as `{"answered": true, "fingerprint": "..."}` — enough for the
    UI to show "set, last changed Tuesday" and nothing an attacker with a stolen
    session could use (§7.4 write-only).
    """
    state = {}
    for answer in WizardAnswer.objects.filter(site=site).select_related("secret_ref"):
        if answer.is_secret:
            state[answer.question_id] = {   # nosec B105 — metadata, not a value
                "answered": True,
                "is_secret": True,
                "fingerprint": answer.secret_ref.fingerprint if answer.secret_ref else "",
            }
        else:
            state[answer.question_id] = answer.value
    return state

"""Materialization: scan report + answers -> a frozen Manifest row (§V5, §V6).

DESIGN DECISION (2026-08-09 debate) — materialization reads the STORED scan report and
never touches the project on disk. The module API does offer
`manifest_fragment(root, answers)`, and the first draft of this file called it. Three
arguments retired that:

  * Stability. The folder may have moved, been deleted, or changed since the scan. A
    materialize step that reads disk turns an ordinary user action into a 500.
  * Provenance. The manifest must be derived from exactly the scan the operator saw in
    the readiness report. Re-running modules lets code change between "I read the
    report" and "I pressed the button", invisibly.
  * §V6's own logic. If deploys reading only data is right, then materialization
    reading only data is right for the same reason.

Consequence, stated so nobody re-litigates it by accident: if a module ever needs an
answer-dependent fragment, it must be a pure function of (draft, answers) — never of
the filesystem — and it gets called from `_apply_answers` below.
"""
import copy
import hashlib
import json

from django.db import transaction

from core.audit import audit
from deploys.models import MANIFEST_SCHEMA_VERSION, Manifest

from .models import WizardAnswer
from .questions import missing_required, question_map


class MaterializeRefused(Exception):
    """Refusal, not failure. Carries a machine-readable cause and the offending items.

    §F4's rule ("show the causal step, not the failed one") applies here: an operator
    who is told 'cannot materialize' learns nothing, and one who is told 'these two
    blockers, this missing answer' can act.
    """

    def __init__(self, code, message, items=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.items = items or []

    def as_dict(self):
        return {"code": self.code, "detail": self.message, "items": self.items}


def report_hash(report):
    return hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def preflight(site):
    """Every reason materialization would refuse, gathered at once.

    Returned rather than raised so the UI can show the whole list. Reporting the
    first problem, making the operator fix it, then reporting the second is the
    interaction that makes people hate wizards.
    """
    project = site.project
    problems = []
    report = project.scan_report or {}

    if not report:
        problems.append({
            "code": "scan_required",
            "detail": "this project has not been scanned yet",
            "items": [],
        })
        return problems   # nothing else is knowable without a scan

    blockers = [c for c in report.get("checks", []) if c.get("tier") == "blocker"]
    if blockers:
        problems.append({
            "code": "blockers_present",
            "detail": "the readiness report has blockers; these must be fixed and the "
                      "project re-scanned",
            "items": [{"id": c["id"], "title": c["title"]} for c in blockers],
        })

    # Before deciding what is answered, drop any plaintext answer whose question has
    # since been reclassified as a secret. Those values must be re-entered, and the
    # cleartext must not survive the discovery (see service.scrub_downgraded_answers).
    from .service import scrub_downgraded_answers

    rescanned = scrub_downgraded_answers(site)
    if rescanned:
        known_now = question_map(project)
        problems.append({
            "code": "answers_need_reentry",
            "detail": "these values are now handled as secrets and must be entered "
                      "again; the previously stored plaintext has been deleted and "
                      "should be rotated at the source",
            "items": [{"id": qid,
                       "prompt": known_now[qid].prompt if qid in known_now else qid}
                      for qid in rescanned],
        })

    answered = set(
        WizardAnswer.objects.filter(site=site).values_list("question_id", flat=True)
    )
    missing = missing_required(project, answered)
    if missing:
        known = question_map(project)
        problems.append({
            "code": "answers_missing",
            "detail": "required questions are unanswered",
            "items": [{"id": qid, "prompt": known[qid].prompt if qid in known else qid}
                      for qid in missing],
        })

    return problems


def warnings_for(site):
    report = site.project.scan_report or {}
    return [c for c in report.get("checks", []) if c.get("tier") == "warning"]


@transaction.atomic
def materialize(site, *, actor=None, confirm_warnings=False):
    """Freeze the manifest. Raises MaterializeRefused; never returns a partial row."""
    problems = preflight(site)
    if problems:
        first = problems[0]
        raise MaterializeRefused(first["code"], first["detail"], first["items"])

    warnings = warnings_for(site)
    if warnings and not confirm_warnings:
        raise MaterializeRefused(
            "warnings_unconfirmed",
            "the readiness report has warnings; confirm to proceed",
            [{"id": c["id"], "title": c["title"]} for c in warnings],
        )

    project = site.project
    report = project.scan_report
    body = copy.deepcopy(report.get("manifest_draft") or {})
    answers = list(WizardAnswer.objects.filter(site=site).select_related("secret_ref"))
    _apply_answers(body, site, answers, question_map(project))

    # select_for_update on the site row: two operators pressing Materialize at the
    # same moment must not both compute version N+1 and race the unique constraint
    # into a 500. The loser waits and gets N+2.
    locked = type(site).objects.select_for_update().get(pk=site.pk)
    latest = Manifest.objects.filter(site=locked).order_by("-version").first()
    version = (latest.version + 1) if latest else 1

    manifest = Manifest.objects.create(
        site=locked,
        version=version,
        schema_version=MANIFEST_SCHEMA_VERSION,
        body=body,
        scan_report_hash=report_hash(report),
        scanned_at=project.scanned_at,
        created_by=actor,
    )
    audit("manifest_materialized", manifest, actor=actor, source="api",
          site_id=site.pk, version=version,
          env_names=body.get("env_names", []),
          confirmed_warnings=[c["id"] for c in warnings] if confirm_warnings else [])
    return manifest


def _apply_answers(body, site, answers, known):
    """Overlay answers onto the scan's manifest draft. Pure — no disk, no network.

    Secret VALUES never appear in the manifest. The manifest carries env NAMES; the
    values stay as vault rows the pipeline dereferences at deploy time (§6.9, §F9's
    'env names only' rule for the diff screen).
    """
    env_names, env_refs = [], {}

    for answer in answers:
        qid = answer.question_id

        if answer.is_secret:
            name = _env_name(qid)
            if name:
                env_names.append(name)
                env_refs[name] = answer.secret_ref_id
            continue

        if qid == "site.domain":
            body["domain"] = answer.value
            site.domain = answer.value
        elif qid == "site.exposure":
            body["exposure"] = answer.value
        elif _env_name(qid):
            name = _env_name(qid)
            env_names.append(name)
            body.setdefault("env_plain", {})[name] = answer.value
        else:
            # Module-specific answers are recorded verbatim under a namespace rather
            # than dropped: a module that asked a question expects to see the answer,
            # and silently discarding it is the failure mode this branch exists for.
            body.setdefault("module_answers", {})[qid] = answer.value

    body["env_names"] = sorted(set(env_names))
    body["env_secret_refs"] = env_refs
    body["site"] = {"id": site.pk, "name": site.name, "domain": site.domain}
    if site.domain:
        site.save(update_fields=["domain"])
    return body


def _env_name(question_id):
    """`django.env.DATABASE_URL` -> `DATABASE_URL`; anything else -> None."""
    marker = ".env."
    if marker in question_id:
        return question_id.split(marker, 1)[1]
    return None

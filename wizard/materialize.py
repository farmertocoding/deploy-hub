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
from vault import service as vault_service
from vault.models import Secret

from .models import WizardAnswer
from .questions import missing_required, question_map


class MaterializeRefused(Exception):
    """Refusal, not failure. Carries a machine-readable cause and the offending items.

    §F4's rule ("show the causal step, not the failed one") applies here: an operator
    who is told 'cannot materialize' learns nothing, and one who is told 'these two
    blockers, this missing answer' can act.
    """

    def __init__(self, code, message, items=None, problems=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.items = items or []
        # Round-1 F4: preflight gathers EVERY problem precisely so the operator can
        # see the whole list; raising only problems[0] threw that away and produced
        # the fix-one-see-the-next loop the docstring claims to avoid. The 409 body
        # now carries all of them; `code`/`items` remain the first problem so
        # existing single-cause consumers keep working.
        self.problems = problems if problems is not None else [
            {"code": self.code, "detail": self.message, "items": self.items}
        ]

    def as_dict(self):
        return {"code": self.code, "detail": self.message, "items": self.items,
                "problems": self.problems}


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

    # Round-1 F5: detection only — preflight runs on GET and must not delete rows.
    # The scrub itself happens in the write paths (set_answers, materialize).
    from .service import downgraded_answers

    rescanned = downgraded_answers(site)
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
    # Round-1 F5: materialize is a write, so the scrub happens here for real — and
    # the scrub and the refusal are ONE event: destroying stale plaintext without
    # telling the operator what to re-enter would leave a site that won't start and
    # no visible reason (the exact failure the original test pinned). The refusal is
    # composed from what THIS call scrubbed, plus everything preflight still sees.
    from .service import scrub_downgraded_answers

    scrubbed = scrub_downgraded_answers(site)
    problems = []
    if scrubbed:
        known = question_map(site.project)
        problems.append({
            "code": "answers_need_reentry",
            "detail": "these values are now handled as secrets and must be entered "
                      "again; the previously stored plaintext has been deleted and "
                      "should be rotated at the source",
            "items": [{"id": qid,
                       "prompt": known[qid].prompt if qid in known else qid}
                      for qid in scrubbed],
        })
    problems.extend(preflight(site))
    if problems:
        first = problems[0]
        raise MaterializeRefused(first["code"], first["detail"], first["items"],
                                 problems=problems)

    warnings = warnings_for(site)
    if warnings and not confirm_warnings:
        raise MaterializeRefused(
            "warnings_unconfirmed",
            "the readiness report has warnings; confirm to proceed",
            [{"id": c["id"], "title": c["title"]} for c in warnings],
        )

    project = site.project
    report = project.scan_report

    # select_for_update FIRST: the version number feeds the env bundle's AAD, so the
    # lock must be held before either is computed — two operators pressing
    # Materialize at once must not both compute version N+1 (round-1 ordering fix;
    # previously the lock was taken after answers were applied).
    locked = type(site).objects.select_for_update().get(pk=site.pk)
    latest = Manifest.objects.filter(site=locked).order_by("-version").first()
    version = (latest.version + 1) if latest else 1

    body = copy.deepcopy(report.get("manifest_draft") or {})
    answers = list(WizardAnswer.objects.filter(site=locked).select_related("secret_ref"))
    env_values = _apply_answers(body, locked, answers, question_map(project))

    # Round-1 F1 (security, high): env VALUES never enter the manifest body — not
    # even the plain-classified ones, because classification is a heuristic and one
    # miss would freeze a live credential into an append-only JSON row returned by
    # GET. Instead every manifest version owns ONE vault env bundle (plain + secret
    # merged), AAD-bound to site:version, composed under the same transaction so a
    # failed materialization leaves no orphan. Reproducibility comes free: deploying
    # v3 uses v3's env exactly as frozen, even if answers changed since (§D2's
    # env-snapshot rule applied one step earlier).
    body["env_bundle_ref"] = None
    if env_values:
        bundle = vault_service.put(
            kind=Secret.Kind.ENV_BUNDLE,
            owner_type="manifest",
            owner_id=f"{locked.pk}:v{version}",
            plaintext=json.dumps(env_values, sort_keys=True).encode("utf-8"),
            actor=actor,
        )
        body["env_bundle_ref"] = bundle.pk

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

    Returns {ENV_NAME: value} for the vault bundle. NO env value — plain or secret —
    is written into `body` (round-1 F1): the body carries names + the bundle ref, and
    the values live only as vault ciphertext. Secret answers are decrypted here,
    inside the materialize transaction, through the audited vault.get path.
    """
    env_names, env_values = [], {}

    for answer in answers:
        qid = answer.question_id

        if answer.is_secret:
            name = _env_name(qid)
            if name and answer.secret_ref is not None:
                env_names.append(name)
                env_values[name] = vault_service.get(
                    answer.secret_ref, reason=f"materialize {site.pk}"
                ).decode("utf-8")
            continue

        if qid == "site.domain":
            body["domain"] = answer.value
            site.domain = answer.value
        elif qid == "site.exposure":
            body["exposure"] = answer.value
        elif _env_name(qid):
            name = _env_name(qid)
            env_names.append(name)
            env_values[name] = answer.value
        else:
            # Module-specific answers are recorded verbatim under a namespace rather
            # than dropped: a module that asked a question expects to see the answer,
            # and silently discarding it is the failure mode this branch exists for.
            body.setdefault("module_answers", {})[qid] = answer.value

    body["env_names"] = sorted(set(env_names))
    body["site"] = {"id": site.pk, "name": site.name, "domain": site.domain}
    if site.domain:
        site.save(update_fields=["domain"])
    return env_values


def _env_name(question_id):
    """`django.env.DATABASE_URL` -> `DATABASE_URL`; anything else -> None."""
    marker = ".env."
    if marker in question_id:
        return question_id.split(marker, 1)[1]
    return None

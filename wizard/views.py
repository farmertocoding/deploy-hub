"""Wizard API (§4.5: serializers are the source of truth; the TS client + zod schemas
are generated from them and `make check-generated` keeps the mirror honest)."""
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exception_handlers import django_validation_to_drf_detail
from core.models import Project, Site

from . import service
from .materialize import MaterializeRefused, materialize, preflight, warnings_for
from .questions import question_set


class QuestionSerializer(serializers.Serializer):
    id = serializers.CharField()
    prompt = serializers.CharField()
    kind = serializers.CharField()
    default = serializers.JSONField(allow_null=True, required=False)
    choices = serializers.ListField(child=serializers.CharField(), required=False)
    secret = serializers.BooleanField()


class WizardStateSerializer(serializers.Serializer):
    questions = QuestionSerializer(many=True)
    answered = serializers.DictField()
    blocking = serializers.ListField(child=serializers.DictField())
    warnings = serializers.ListField(child=serializers.DictField())
    can_materialize = serializers.BooleanField()


class AnswersSerializer(serializers.Serializer):
    answers = serializers.DictField(
        help_text="question id -> answer. Partial sets are fine; the wizard saves "
                  "as you go."
    )


def pin_patched_answers_required(result, generator, request, public):
    """spectacular marks PATCH bodies partial, so `{}` would parse as valid."""
    schema = (result.get("components") or {}).get("schemas", {}).get("PatchedAnswers")
    if schema is not None and "answers" in schema.get("properties", {}):
        required = schema.setdefault("required", [])
        if "answers" not in required:
            required.append("answers")
    return result


class MaterializeSerializer(serializers.Serializer):
    confirm_warnings = serializers.BooleanField(default=False)


class ManifestSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    schema_version = serializers.IntegerField()
    body = serializers.JSONField()
    scan_report_hash = serializers.CharField()
    created_at = serializers.DateTimeField()


def _state(site):
    questions = question_set(site.project)
    problems = preflight(site)
    return {
        "questions": [
            {**q.as_dict(), "secret": q.kind == "secret"} for q in questions
        ],
        "answered": service.answered_state(site),
        "blocking": problems,
        "warnings": [{"id": c["id"], "title": c["title"]} for c in warnings_for(site)],
        "can_materialize": not problems,
    }


class WizardView(APIView):
    """GET the question set and current answers; PATCH a partial answer set."""

    @extend_schema(responses={200: WizardStateSerializer})
    def get(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        return Response(WizardStateSerializer(_state(site)).data)

    @extend_schema(request=AnswersSerializer, responses={200: WizardStateSerializer})
    def patch(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        payload = AnswersSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            service.set_answers(site, payload.validated_data["answers"], actor=request.user)
        except DjangoValidationError as exc:
            # Per-question field map (not nested under `answers`) so the §4.5
            # contract names the qid; re-raised so the audited handler fires.
            raise ValidationError(django_validation_to_drf_detail(exc)) from exc
        return Response(WizardStateSerializer(_state(site)).data)


class ManifestView(APIView):
    """POST materializes version N+1; GET returns the latest frozen manifest."""

    @extend_schema(request=MaterializeSerializer, responses={201: ManifestSerializer})
    def post(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        payload = MaterializeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            manifest = materialize(
                site, actor=request.user,
                confirm_warnings=payload.validated_data["confirm_warnings"],
            )
        except MaterializeRefused as refusal:
            # 409, not 400: the request is well-formed, the site's state says no.
            return Response(refusal.as_dict(), status=status.HTTP_409_CONFLICT)
        return Response(ManifestSerializer(manifest).data,
                        status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: ManifestSerializer})
    def get(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        manifest = site.manifests.first()
        if manifest is None:
            return Response({"detail": "no manifest materialized yet"},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(ManifestSerializer(manifest).data)


class ReadinessSerializer(serializers.Serializer):
    scanned_at = serializers.DateTimeField(allow_null=True)
    modules = serializers.ListField(child=serializers.CharField())
    summary = serializers.DictField()
    blockers = serializers.ListField(child=serializers.DictField())
    warnings = serializers.ListField(child=serializers.DictField())
    advice = serializers.ListField(child=serializers.DictField())
    pending_sandbox = serializers.ListField(child=serializers.DictField())


# The tiers the readiness payload groups, in the order the screens render them. NOT the
# payload's key names for two of the four — `ReadinessSerializer` pluralizes
# `blocker`/`warning` and does not pluralize `advice`/`pending_sandbox` — which is the
# reason the mapping below is written out rather than derived by adding an `s`.
READINESS_TIERS = ("blocker", "warning", "advice", "pending_sandbox")
_READINESS_KEYS = {"blocker": "blockers", "warning": "warnings",
                   "advice": "advice", "pending_sandbox": "pending_sandbox"}
# The payload's list keys, in tier order — what a reader of the response walks. Exported
# because `scripts_dev/sim_fixture_payloads.py` had its own copy of it, and reading the
# payload with the TIER names instead silently yields the two lists whose names happen
# to collide and an empty result for the other two, which reads exactly like "no
# blockers".
READINESS_KEYS = tuple(_READINESS_KEYS[tier] for tier in READINESS_TIERS)


def readiness_body(report, scanned_at):
    """`GET /api/v1/projects/<id>/readiness/`'s response body, from a report and a stamp.

    R10-A5: THE ONE SPELLING of the tier grouping. It was written out three times — in
    `ReadinessView.get` below, and once in each half of
    `scripts_dev/sim_fixture_payloads.py` — and the harness halves exist precisely to
    prove that `frontend/src/sim.js` is what this endpoint returns. A harness that
    re-implements the endpoint proves that it matches a second implementation of it,
    which is the fixture-rot class this repo has now paid for in three rounds running.

    Takes the report DICT rather than a `Project`, because the DB-free half of that
    harness has a fresh `scanner.core.scan` result and no row to hang it on, and the
    only thing the row contributed was two `.get`s and a datetime. `scanned_at` is
    passed through to the serializer, which renders a `datetime` and passes a string
    along unchanged — so both callers hand it whichever they have.
    """
    report = report or {}
    checks = report.get("checks", [])
    grouped = {_READINESS_KEYS[tier]: [c for c in checks if c.get("tier") == tier]
               for tier in READINESS_TIERS}
    return ReadinessSerializer({
        "scanned_at": scanned_at,
        "modules": report.get("modules", []),
        "summary": report.get("summary", {}),
        **grouped,
    }).data


class CertRefusalSerializer(serializers.Serializer):
    detail = serializers.CharField()
    finding_id = serializers.IntegerField()


class SiteSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    domain = serializers.CharField(allow_blank=True)
    latest_manifest_version = serializers.IntegerField(allow_null=True)
    manifest_current = serializers.BooleanField(allow_null=True)
    cert_refusal = CertRefusalSerializer(allow_null=True, required=False)


class ProjectSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    scanned_at = serializers.DateTimeField(allow_null=True)
    tiers = serializers.DictField(child=serializers.IntegerField())
    sites = SiteSummarySerializer(many=True)


def _open_cert_refusals(sites):
    """Open `unproxied-cert:{pk}` Findings, keyed by fingerprint (D-035)."""
    from core.models import Finding

    fingerprints = [f"unproxied-cert:{site.pk}" for site in sites]
    if not fingerprints:
        return {}
    return {
        row.fingerprint: row
        for row in Finding.objects.filter(
            fingerprint__in=fingerprints, state=Finding.State.OPEN,
        )
    }


def project_row_body(project):
    """`GET /api/v1/projects/`'s row for one project — tiers, sites, manifest currency.

    R11-A1: THE ONE SPELLING of the row, on `readiness_body`'s precedent one screen
    over. It was written twice — here, inline in `ProjectListView.get`, and in
    `scripts_dev/sim_fixture_payloads.py`, the harness whose entire job is proving that
    `frontend/src/sim.js` is what these endpoints return. A harness that re-implements
    the endpoint proves sim.js matches a second implementation of it.

    And the two had already drifted, in the field an operator uses: the harness ordered
    the sites by pk and this did not.

    Takes the PROJECT row rather than a report dict, unlike `readiness_body` — the
    difference is real rather than an inconsistency. That function exists partly for the
    DB-free half of the harness, which has a fresh `scanner.core.scan` result and no row
    to hang it on; this one reads `project.sites` and each site's manifests, so a
    database is not optional and pretending otherwise would mean passing in the very
    lists that are the thing being derived.

    WHERE THE SITE ORDERING LIVES, since the finding is that it lived in one caller and
    not the other: here, applied to the MATERIALIZED list rather than to the queryset.
    `Site` declares no `Meta.ordering`, so `project.sites.all()` carries no ORDER BY at
    all and the sequence was the database's choice. The alternatives both leak:
    `.order_by("pk")` on the related manager discards the caller's prefetch and pays a
    query per project, and a `Prefetch` in the view below leaves every OTHER caller —
    the fixture harness among them — silently unordered again, which is the shape of the
    defect this is closing. Sorting the list the caller already has costs a sort of a
    handful of rows, uses the prefetch cache, and holds for every caller. pk order is
    creation order, which is the order the operator added the sites in.
    """
    from .materialize import report_hash

    report = project.scan_report or {}
    checks = report.get("checks", [])
    current_hash = report_hash(report) if report else None
    site_rows = sorted(project.sites.all(), key=lambda s: s.pk)
    refusals = _open_cert_refusals(site_rows)
    sites = []
    for site in site_rows:
        latest = site.manifests.order_by("-version").first()
        refused = refusals.get(f"unproxied-cert:{site.pk}")
        sites.append({
            "id": site.pk, "name": site.name, "domain": site.domain,
            "latest_manifest_version": latest.version if latest else None,
            "manifest_current": (
                None if latest is None or current_hash is None
                else latest.scan_report_hash == current_hash),
            "cert_refusal": (
                {"detail": refused.body or refused.title, "finding_id": refused.pk}
                if refused else None
            ),
        })
    return ProjectSummarySerializer({
        "id": project.pk, "name": project.name, "slug": project.slug,
        "scanned_at": project.scanned_at,
        # READINESS_TIERS, not four strings restated. The same tuple the readiness
        # payload groups by, in the same order, so a tier added there is counted here
        # rather than silently missing from the list the operator reads first.
        "tiers": {t: sum(1 for c in checks if c.get("tier") == t)
                  for t in READINESS_TIERS},
        "sites": sites,
    }).data


class ProjectListView(APIView):
    """What the readiness screen renders its left column from (F7-lite).

    tier COUNTS here, full check bodies from /readiness/ — the list stays cheap when
    projects grow. manifest_current answers the one freshness question the data model
    can answer honestly: does the latest manifest correspond to the CURRENT scan?
    (A true warnings-diff-since-last-manifest would need the prior report stored,
    which it isn't — noted in the F7 design decision rather than faked.)
    """

    @extend_schema(responses={200: ProjectSummarySerializer(many=True)})
    def get(self, request):
        return Response([
            project_row_body(project)
            for project in Project.objects.order_by("name").prefetch_related("sites")
        ])


class ReadinessView(APIView):
    """The three-tier readiness report (§5.3), tiered server-side.

    Tiering happens here rather than in the client so the CLI, the UI and the pipeline
    all agree on what counts as a blocker.
    """

    @extend_schema(responses={200: ReadinessSerializer})
    def get(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        return Response(readiness_body(project.scan_report, project.scanned_at))


class SiteEdgeOwnerSerializer(serializers.Serializer):
    """PATCH /api/v1/sites/{id}/ — {edge_owner} only (design note §7 I-edge)."""

    edge_owner = serializers.ChoiceField(choices=Site.EdgeOwner.choices)

    def to_internal_value(self, data):
        extra = set(getattr(data, "keys", lambda: [])()) - {"edge_owner"}
        if extra:
            raise ValidationError({
                field: "this endpoint accepts edge_owner only" for field in extra
            })
        return super().to_internal_value(data)


class SiteEdgeOwnerView(APIView):
    """Record the operator's Caddy-ownership decision. Never writes dns_zone."""

    @extend_schema(
        request=SiteEdgeOwnerSerializer,
        responses={200: SiteEdgeOwnerSerializer},
    )
    def patch(self, request, site_id):
        from provision.adopt import apply_edge_owner

        site = get_object_or_404(Site, pk=site_id)
        payload = SiteEdgeOwnerSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        apply_edge_owner(
            site,
            payload.validated_data["edge_owner"],
            actor=request.user,
        )
        site.refresh_from_db()
        return Response(SiteEdgeOwnerSerializer({"edge_owner": site.edge_owner}).data)

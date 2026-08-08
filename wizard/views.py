"""Wizard API (§4.5: serializers are the source of truth; the TS client + zod schemas
are generated from them and `make check-generated` keeps the mirror honest)."""
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

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
            # Re-raised as DRF's type so the §4.5 error shape and the audited
            # exception handler both apply — one error contract, not two.
            raise ValidationError({
                "answers": exc.message_dict if hasattr(exc, "message_dict")
                else exc.messages
            }) from exc
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


class ReadinessView(APIView):
    """The three-tier readiness report (§5.3), tiered server-side.

    Tiering happens here rather than in the client so the CLI, the UI and the pipeline
    all agree on what counts as a blocker.
    """

    @extend_schema(responses={200: ReadinessSerializer})
    def get(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        report = project.scan_report or {}
        checks = report.get("checks", [])
        by_tier = {tier: [c for c in checks if c.get("tier") == tier]
                   for tier in ("blocker", "warning", "advice", "pending_sandbox")}
        return Response(ReadinessSerializer({
            "scanned_at": project.scanned_at,
            "modules": report.get("modules", []),
            "summary": report.get("summary", {}),
            "blockers": by_tier["blocker"],
            "warnings": by_tier["warning"],
            "advice": by_tier["advice"],
            "pending_sandbox": by_tier["pending_sandbox"],
        }).data)

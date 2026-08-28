"""Findings inbox API (§F2): list / detail / transition under /api/v1/findings/.

This is the table-backed half of snapshot-then-stream (§D7): responses are
{seq, data} where seq comes from the SAME counter `realtime/publish.py` stamps
`findings` events with, read BEFORE the table query — an event racing the
query is then delivered twice (harmless upsert client-side), never lost.
Session-gated like every sibling endpoint (DRF defaults, §6.10); every state
change goes through core/findings.py, which writes the AuditEvent and
publishes the transition.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# seq comes through core's stream port (findings_seq), not a realtime import:
# monitor must stay scanner-free (ARCH-V6) and realtime reaches scanner.
from core import findings as findings_service
from core.audit import audit
from core.exception_handlers import client_ip
from core.findings import findings_seq
from core.models import Finding
from core.permissions import RequireWorkspace
from core.rbac import has_operator_capability, request_workspace, scope_queryset, scoped_get

from .map_graph import graph_snapshot


class FindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Finding
        fields = [
            "id", "source_engine", "severity", "entity", "title", "body",
            "fix_action", "state", "first_seen", "last_seen", "fingerprint",
            "accepted_reason",
        ]


class FindingListSnapshotSerializer(serializers.Serializer):
    seq = serializers.IntegerField()
    data = FindingSerializer(many=True)


class FindingDetailSnapshotSerializer(serializers.Serializer):
    seq = serializers.IntegerField()
    data = FindingSerializer()


class FindingFilterSerializer(serializers.Serializer):
    """§F2: every panel is a filtered view — the filters ARE the contract."""

    state = serializers.ChoiceField(choices=Finding.State.choices, required=False)
    severity = serializers.ChoiceField(choices=Finding.Severity.choices,
                                       required=False)
    entity = serializers.CharField(max_length=128, required=False)


class TransitionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["ack", "resolve", "accept_risk"])
    reason = serializers.CharField(max_length=256, allow_blank=True, default="",
                                   trim_whitespace=True)

    def validate(self, attrs):
        # §F2 at the serializer, not just the service: accept-risk without a
        # one-line reason is invalid INPUT, and rejected input is a signal (§4.5).
        if attrs["action"] == "accept_risk" and not attrs["reason"].strip():
            raise serializers.ValidationError(
                {"reason": "Accept-risk requires a one-line reason (§F2)."})
        return attrs


class FindingListView(APIView):
    permission_classes = [IsAuthenticated, RequireWorkspace]

    @extend_schema(
        operation_id="v1_findings_list",
        parameters=[FindingFilterSerializer],
        responses={200: FindingListSnapshotSerializer},
    )
    def get(self, request):
        filters = FindingFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        seq = findings_seq()
        rows = scope_queryset(Finding.objects.all(), request_workspace(request)).filter(
            **filters.validated_data).order_by("severity", "-last_seen")
        return Response({"seq": seq, "data": FindingSerializer(rows, many=True).data})


class FindingDetailView(APIView):
    permission_classes = [IsAuthenticated, RequireWorkspace]

    @extend_schema(
        operation_id="v1_findings_retrieve",
        responses={200: FindingDetailSnapshotSerializer},
    )
    def get(self, request, pk):
        seq = findings_seq()
        row = scoped_get(request, Finding.objects.all(), pk=pk)
        return Response({"seq": seq, "data": FindingSerializer(row).data})


_FINDING_TRANSITION_CAP = {
    "ack": "findings.manage",
    "resolve": "findings.manage",
    "accept_risk": "findings.accept_risk",
}


class FindingTransitionView(APIView):
    permission_classes = [IsAuthenticated, RequireWorkspace]

    @extend_schema(request=TransitionSerializer,
                   responses={200: FindingDetailSnapshotSerializer})
    def post(self, request, pk):
        ser = TransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        action = ser.validated_data["action"]
        cap = _FINDING_TRANSITION_CAP[action]
        workspace = request_workspace(request)
        if not has_operator_capability(request.user, cap, workspace):
            audit(
                "finding.transition_denied",
                actor=request.user,
                source="api",
                severity="security",
                source_ip=client_ip(request),
                workspace=workspace,
                finding_id=pk,
                requested=action,
            )
            return Response(
                {"detail": f"{cap} required.", "code": "not_permitted", "capability": cap},
                status=status.HTTP_403_FORBIDDEN,
            )
        row = scoped_get(request, Finding.objects.all(), pk=pk)
        try:
            if action == "ack":
                findings_service.ack(row, actor=request.user, source="api")
            elif action == "resolve":
                findings_service.resolve(row, actor=request.user, source="api")
            else:
                findings_service.accept_risk(
                    row, ser.validated_data["reason"],
                    actor=request.user, source="api")
        except ValueError as exc:
            # An impossible transition (e.g. acking a resolved finding) is a
            # state conflict, not bad input: 409, like apply-env's busy path.
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        # seq FIRST, then serialize (§D7), same as list/detail: read the other
        # way round, a concurrent event yields seq > data and a replaying
        # client would discard it.
        seq = findings_seq()
        return Response({"seq": seq, "data": FindingSerializer(row).data})


class MapNodeSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField(
        choices=["zone", "host", "container", "hub", "edge", "ghost"])
    label = serializers.CharField()
    status = serializers.CharField()
    parent = serializers.CharField(required=False)


class MapEdgeSerializer(serializers.Serializer):
    a = serializers.CharField()
    b = serializers.CharField()
    path = serializers.ChoiceField(choices=["public", "mesh"])


class MapGraphSerializer(serializers.Serializer):
    nodes = MapNodeSerializer(many=True)
    edges = MapEdgeSerializer(many=True)


class MapSnapshotSerializer(serializers.Serializer):
    seq = serializers.IntegerField()
    data = MapGraphSerializer()


class MapSnapshotView(APIView):
    """Table-backed map.graph snapshot (§D7 / MAP-96-GRAPH-V1)."""

    permission_classes = [IsAuthenticated, RequireWorkspace]

    @extend_schema(responses={200: MapSnapshotSerializer})
    def get(self, request):
        snap = graph_snapshot(workspace=request_workspace(request))
        return Response({
            "seq": snap["seq"],
            "data": {"nodes": snap["nodes"], "edges": snap["edges"]},
        })


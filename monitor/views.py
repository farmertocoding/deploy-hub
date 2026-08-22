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
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

# seq comes through core's stream port (findings_seq), not a realtime import:
# monitor must stay scanner-free (ARCH-V6) and realtime reaches scanner.
from core import findings as findings_service
from core.findings import findings_seq
from core.models import Finding

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
    @extend_schema(parameters=[FindingFilterSerializer],
                   responses={200: FindingListSnapshotSerializer})
    def get(self, request):
        filters = FindingFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        seq = findings_seq()
        rows = Finding.objects.filter(**filters.validated_data).order_by(
            "severity", "-last_seen")
        return Response({"seq": seq, "data": FindingSerializer(rows, many=True).data})


class FindingDetailView(APIView):
    @extend_schema(responses={200: FindingDetailSnapshotSerializer})
    def get(self, request, pk):
        seq = findings_seq()
        row = get_object_or_404(Finding, pk=pk)
        return Response({"seq": seq, "data": FindingSerializer(row).data})


class FindingTransitionView(APIView):
    @extend_schema(request=TransitionSerializer,
                   responses={200: FindingDetailSnapshotSerializer})
    def post(self, request, pk):
        row = get_object_or_404(Finding, pk=pk)
        ser = TransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        action = ser.validated_data["action"]
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
    kind = serializers.ChoiceField(choices=["zone", "host", "container", "hub", "edge"])
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

    @extend_schema(responses={200: MapSnapshotSerializer})
    def get(self, request):
        snap = graph_snapshot()
        return Response({
            "seq": snap["seq"],
            "data": {"nodes": snap["nodes"], "edges": snap["edges"]},
        })


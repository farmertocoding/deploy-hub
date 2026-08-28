"""Target list/detail and T3 Probe router. Not folded into core/views.py.

Views call probe_nothing_forwarded(target, wan_probe=wan_probe_for(target)).
Tests wrap this module's callee to inject wan_probe=. The request body
never binds a WAN scan.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Target
from core.permissions import RequireAction, RequireWorkspace
from core.rbac import TARGET_FIELD, request_workspace, scope_queryset, scoped_get
from monitor.router_advisor import probe_nothing_forwarded, router_advice_for
from monitor.wan_probe import wan_probe_for


def _tunnel_flag(target):
    return (target.collect_payload or {}).get("tunnel") is True


def _list_row(target):
    return {
        "id": target.pk,
        "host": target.host,
        "kind": target.kind,
        "tunnel": _tunnel_flag(target),
    }


class TargetListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    host = serializers.CharField()
    kind = serializers.CharField()
    tunnel = serializers.BooleanField()


class RouterAdviceSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["tunnel", "not_tunnel", "no_seam"])
    forwarded = serializers.BooleanField()
    finding_id = serializers.IntegerField(allow_null=True)
    title = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)


class TargetDetailSerializer(TargetListSerializer):
    router_advice = RouterAdviceSerializer()
    wan_probe_configured = serializers.BooleanField()


class RouterProbeSerializer(serializers.Serializer):
    """Empty body — Probe router takes no operator fields."""


class RouterProbeResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    target_id = serializers.IntegerField()
    forwarded = serializers.BooleanField()
    finding_id = serializers.IntegerField(allow_null=True)


class TargetListView(APIView):
    permission_classes = [IsAuthenticated, RequireWorkspace]

    @extend_schema(responses={200: TargetListSerializer(many=True)})
    def get(self, request):
        rows = scope_queryset(
            Target.objects.order_by("pk"), request_workspace(request), TARGET_FIELD,
        )
        return Response(TargetListSerializer(
            [_list_row(row) for row in rows], many=True,
        ).data)


class TargetDetailView(APIView):
    permission_classes = [IsAuthenticated, RequireWorkspace]

    @extend_schema(responses={200: TargetDetailSerializer})
    def get(self, request, pk):
        target = scoped_get(request, Target.objects.all(), TARGET_FIELD, pk=pk)
        payload = _list_row(target)
        payload["router_advice"] = router_advice_for(target)
        payload["wan_probe_configured"] = wan_probe_for(target) is not None
        return Response(TargetDetailSerializer(payload).data)


class RouterProbeView(APIView):
    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction]
    action_id = "target.router_probe"
    @extend_schema(
        request=RouterProbeSerializer,
        responses={201: RouterProbeResultSerializer},
    )
    def post(self, request, pk):
        target = scoped_get(request, Target.objects.all(), TARGET_FIELD, pk=pk)
        ser = RouterProbeSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        result = probe_nothing_forwarded(
            target, wan_probe=wan_probe_for(target),
        )
        if result["mode"] == "no_seam":
            return Response(
                {"detail": "wan probe refused"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if result["mode"] == "not_tunnel":
            return Response(
                {"detail": "not tunnel mode"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            RouterProbeResultSerializer({
                "ok": True,
                "target_id": target.pk,
                "forwarded": bool(result.get("forwarded")),
                "finding_id": result.get("finding_id"),
            }).data,
            status=status.HTTP_201_CREATED,
        )

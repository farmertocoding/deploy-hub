"""Authenticated start/cancel for Site adoption."""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Site
from deploys.adopt_service import (
    AdoptHttpError,
    cancel_adopt,
    operation_body,
    start_adopt,
)

_BODY_KEYS = frozenset({"live_compose_path", "cancel"})


class AdoptRequestSerializer(serializers.Serializer):
    live_compose_path = serializers.CharField(
        required=False, allow_blank=False, max_length=4096,
    )
    cancel = serializers.BooleanField(required=False)


class AdoptOperationSerializer(serializers.Serializer):
    checkrun_id = serializers.IntegerField()
    site_id = serializers.IntegerField()
    stage = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    queued = serializers.BooleanField()
    temp_name = serializers.CharField(allow_blank=True)


class SiteAdoptView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AdoptRequestSerializer,
        responses={
            200: AdoptOperationSerializer,
            202: AdoptOperationSerializer,
        },
    )
    def post(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        data = getattr(request, "data", None)
        if not isinstance(data, dict):
            raise serializers.ValidationError({"detail": "body must be an object"})
        extra = set(data.keys()) - _BODY_KEYS
        if extra:
            raise serializers.ValidationError(
                {field: "unknown field" for field in sorted(extra)}
            )
        ser = AdoptRequestSerializer(data=data)
        ser.is_valid(raise_exception=True)
        cancel = bool(ser.validated_data.get("cancel"))
        path = ser.validated_data.get("live_compose_path")
        if cancel and path:
            raise serializers.ValidationError(
                {"cancel": "cancel cannot be combined with live_compose_path"}
            )
        try:
            if cancel:
                op = cancel_adopt(site)
                if op is None:
                    return Response(
                        {"detail": "no adopt operation"},
                        status=status.HTTP_200_OK,
                    )
            else:
                op = start_adopt(site, live_compose_path=path)
        except AdoptHttpError as exc:
            return Response({"detail": exc.detail}, status=exc.status)
        code = (
            status.HTTP_202_ACCEPTED if op.queued else status.HTTP_200_OK
        )
        return Response(AdoptOperationSerializer(operation_body(op)).data, status=code)

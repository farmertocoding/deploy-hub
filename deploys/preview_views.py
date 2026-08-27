"""T2 POST that creates a preview sibling Site."""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Site
from deploys.preview import PreviewError, create_preview
from providers.registry import git_visibility_for


class PreviewCreateSerializer(serializers.Serializer):
    ref = serializers.CharField()
    confirm_name = serializers.CharField()


class PreviewCreateResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    site_id = serializers.IntegerField()
    parent_id = serializers.IntegerField()
    ref = serializers.CharField()


class SitePreviewCreateView(APIView):
    """T2 site.preview_create: type the parent name."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PreviewCreateSerializer,
        responses={201: PreviewCreateResultSerializer},
    )
    def post(self, request, site_id):
        parent = get_object_or_404(Site, pk=site_id)
        raw = getattr(request, "data", None)
        if isinstance(raw, dict) and "visibility" in raw:
            raise serializers.ValidationError(
                {"visibility": "visibility is resolved server-side"}
            )
        ser = PreviewCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != parent.name:
            return Response(
                {"detail": "Type the site name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        provider = git_visibility_for(parent.project)
        visibility = None if provider is None else provider.visibility(
            parent.project.git_url,
        )
        try:
            created = create_preview(
                parent, ser.validated_data["ref"], visibility=visibility,
            )
        except PreviewError as exc:
            return Response(
                {"detail": exc.reason},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            PreviewCreateResultSerializer({
                "ok": True,
                "site_id": created.pk,
                "parent_id": parent.pk,
                "ref": ser.validated_data["ref"],
            }).data,
            status=status.HTTP_201_CREATED,
        )

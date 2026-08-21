"""Site env API: names on GET, values write-only, POST applies steps 4–9."""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Site
from deploys.env import apply_env, list_env_names, merge_env, put_env


class EnvNamesSerializer(serializers.Serializer):
    names = serializers.ListField(child=serializers.CharField())
    config_stale = serializers.BooleanField()


class EnvWriteSerializer(serializers.Serializer):
    env = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        write_only=True,
        help_text="name -> value. Values are write-only and stored in the vault.",
    )


class EnvApplySerializer(serializers.Serializer):
    deployment_id = serializers.IntegerField()


def _names_body(site):
    site.refresh_from_db()
    return EnvNamesSerializer({
        "names": list_env_names(site),
        "config_stale": site.config_stale,
    }).data


class EnvView(APIView):
    """GET names; PUT replaces / PATCH merges values; POST applies the current env."""

    @extend_schema(responses={200: EnvNamesSerializer})
    def get(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        return Response(_names_body(site))

    @extend_schema(request=EnvWriteSerializer, responses={200: EnvNamesSerializer})
    def put(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        payload = EnvWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        put_env(site, payload.validated_data["env"])
        return Response(_names_body(site))

    @extend_schema(request=EnvWriteSerializer, responses={200: EnvNamesSerializer})
    def patch(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        payload = EnvWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        merge_env(site, payload.validated_data["env"])
        return Response(_names_body(site))

    @extend_schema(request=None, responses={201: EnvApplySerializer})
    def post(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        try:
            deployment = apply_env(site)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            EnvApplySerializer({"deployment_id": deployment.pk}).data,
            status=status.HTTP_201_CREATED,
        )

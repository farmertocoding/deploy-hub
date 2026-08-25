"""Backup operator HTTP: Sites-detail list + T2 test-now + T1 restore."""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import audit
from core.models import BackupUnit, Site
from core.permissions import RequireRecentTouch
from provision.backup import (
    RestoreError,
    list_payload,
    persist_backup,
    restore_to_clean,
    transport_for_site,
)


class BackupDumpSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    bytes = serializers.IntegerField()
    digest = serializers.CharField()
    stored_at = serializers.CharField()
    status = serializers.CharField()


class BackupUnitSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    schedule = serializers.CharField()
    dumps = BackupDumpSerializer(many=True)


class BackupListSerializer(serializers.Serializer):
    units = BackupUnitSerializer(many=True)
    restore_command = serializers.CharField()


class BackupRunSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField()
    unit_id = serializers.IntegerField()
    site_id = serializers.IntegerField()
    bytes = serializers.IntegerField()
    digest = serializers.CharField()
    stored_at = serializers.CharField()


class BackupListView(APIView):
    """GET: metadata-only dumps plus the restore command block."""

    @extend_schema(responses={200: BackupListSerializer})
    def get(self, request, site_id):
        site = get_object_or_404(Site, pk=site_id)
        return Response(BackupListSerializer(list_payload(site)).data)


class BackupTestNowView(APIView):
    """POST: seal a dump with BACKUP_KEY, persist Hub-local, return metadata."""

    @extend_schema(request=None, responses={201: BackupRunSerializer})
    def post(self, request, site_id, unit_id):
        site = get_object_or_404(Site, pk=site_id)
        unit = get_object_or_404(BackupUnit, pk=unit_id, site=site)
        try:
            run = persist_backup(unit, transport=transport_for_site(site))
        except Exception:
            return Response(
                {"detail": "backup failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            BackupRunSerializer(run.results).data,
            status=status.HTTP_201_CREATED,
        )


class BackupRestoreSerializer(serializers.Serializer):
    checkrun_pk = serializers.IntegerField()
    confirm_name = serializers.CharField()


class BackupRestoreResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    unit_id = serializers.IntegerField()
    checkrun_pk = serializers.IntegerField()


class BackupRestoreView(APIView):
    """T1: two passkeys + recent WebAuthn touch + type-the-site-name."""

    permission_classes = [IsAuthenticated, RequireRecentTouch]

    @extend_schema(
        request=BackupRestoreSerializer,
        responses={201: BackupRestoreResultSerializer},
    )
    def post(self, request, site_id, unit_id):
        site = get_object_or_404(Site, pk=site_id)
        unit = get_object_or_404(BackupUnit, pk=unit_id, site=site)
        ser = BackupRestoreSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != site.name:
            return Response(
                {"detail": "Type the site name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            restore_to_clean(
                unit, checkrun_pk=ser.validated_data["checkrun_pk"],
            )
        except RestoreError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit(
            "site.backup_restore",
            source="api",
            actor=request.user,
            obj=site,
            severity="security",
        )
        return Response(
            BackupRestoreResultSerializer({
                "ok": True,
                "unit_id": unit.pk,
                "checkrun_pk": ser.validated_data["checkrun_pk"],
            }).data,
            status=status.HTTP_201_CREATED,
        )

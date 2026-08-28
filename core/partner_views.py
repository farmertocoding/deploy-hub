"""Settings Partners API (Task 5): T1 partner.create, never Connect.

POST /api/v1/partners/ — included from core/zone_urls.py (same api/v1/
prefix as AWS connect). Do not hang this off core/urls.py (/api/auth/).

201 returns hubk_* + whsec_ once (Enroll once-panel). GET / list never
echo them. Fake / empty INTAKE_URL / post-create never Connected.
The Ed25519 private key is not a Partner column and is never vaulted.
"""
import base64
import secrets

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import audit
from core.findings import finding
from core.models import (
    AuditEvent,
    Finding,
    Partner,
    PartnerApiFlag,
    PartnerSite,
    Site,
    SiteInstance,
    Target,
    default_workspace,
)
from core.permissions import RequireAction, RequireRecentTouch, RequireSystemAdmin, RequireWorkspace
from core.rbac import SITE_FIELD, TARGET_FIELD, request_workspace, scoped_get
from vault import service as vault_service
from vault.models import Secret
from vault.ssh import generate_ed25519_raw

# nosec B105 — prefixes naming minted material, not credentials.
HUBK_TEST_PREFIX = "hubk_test_"  # nosec B105
HUBK_LIVE_PREFIX = "hubk_live_"  # nosec B105
WHSEC_PREFIX = "whsec_"  # nosec B105


class PartnerCreateSerializer(serializers.Serializer):
    slug = serializers.SlugField(max_length=64)
    name = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default="",
    )
    confirm_name = serializers.CharField()


class PartnerCreateResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    hubk = serializers.CharField()
    whsec = serializers.CharField()


class IntakeStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=("degraded", "error"))
    mode = serializers.ChoiceField(choices=("fake", "configured"))
    configured = serializers.BooleanField()
    as_of = serializers.CharField(allow_null=True, required=False)


class PartnerDestinationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    host = serializers.CharField()
    kind = serializers.CharField()


class CandidateTargetSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    host = serializers.CharField()
    kind = serializers.CharField()
    tunnel = serializers.BooleanField()


class PartnerPublicSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    destination_order = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True,
    )
    destinations = PartnerDestinationSerializer(many=True)
    suspended = serializers.BooleanField()
    site_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True,
    )


class PartnerListSerializer(serializers.Serializer):
    partners = PartnerPublicSerializer(many=True)
    intake = IntakeStatusSerializer()
    api_enabled = serializers.BooleanField()
    candidate_targets = CandidateTargetSerializer(many=True)


class ConfirmNameSerializer(serializers.Serializer):
    confirm_name = serializers.CharField()
    enabled = serializers.BooleanField(required=False)


class DestinationRankSerializer(serializers.Serializer):
    destination_order = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True,
    )


def _mint_hubk():
    private_raw, public_raw = generate_ed25519_raw()
    prefix = (
        HUBK_TEST_PREFIX
        if getattr(settings, "HUB_TEST_MODE", False)
        else HUBK_LIVE_PREFIX
    )
    hubk = prefix + base64.b64encode(private_raw).decode("ascii")
    pubkey = base64.b64encode(public_raw).decode("ascii")
    return hubk, pubkey


def _mint_whsec():
    return WHSEC_PREFIX + base64.b64encode(secrets.token_bytes(24)).decode("ascii")


def _intake_payload():
    from core.models import CheckRun

    url = str(getattr(settings, "INTAKE_URL", "") or "").strip()
    error = Finding.objects.filter(
        workspace=default_workspace(),
        fingerprint="partner-intake-unreachable",
    ).exclude(state=Finding.State.RESOLVED).exists()
    latest = (
        CheckRun.objects.filter(kind=CheckRun.Kind.INTAKE_POLL)
        .order_by("-pk")
        .first()
    )
    last_success = None
    if latest is not None:
        last_success = ((latest.results or {}).get("last_success_at") or None)
    return {
        "status": "error" if error else "degraded",
        "mode": "fake" if not url else "configured",
        "configured": bool(url),
        "as_of": last_success,
    }


def _candidate_targets(workspace=None):
    from core.models import Target
    from core.rbac import scope_queryset

    rows = Target.objects.filter(status=Target.Status.READY).order_by("pk")
    rows = scope_queryset(rows, workspace, TARGET_FIELD)
    out = []
    for row in rows:
        payload = row.collect_payload or {}
        out.append({
            "id": row.pk,
            "host": row.host,
            "kind": row.kind,
            "tunnel": payload.get("tunnel") is True,
        })
    return out


def partner_api_enabled():
    return PartnerApiFlag.is_on()


def set_partner_api_enabled(value):
    PartnerApiFlag.set_on(value)


def transport_for(target):
    """Same factory as deploys.pipeline._default_transport. T1 tests inject Fake."""
    from core.ssh import SshTransport

    return SshTransport(target)


def _container_names(site):
    """Match deploys/steps.py: site-{slug}-{deployment_id} when a Deployment exists."""
    from django.apps import apps

    Deployment = apps.get_model("deploys", "Deployment")
    pks = list(
        Deployment.objects.filter(manifest__site=site).values_list("pk", flat=True)
    )
    if pks:
        return [f"site-{site.name}-{pk}" for pk in pks]
    return [f"site-{site.name}"]


def _container_name(site):
    names = _container_names(site)
    return names[0]


def _route_id(site):
    return f"site-{site.name}"


def site_route_status(site):
    """410 after T2 takedown: every SiteInstance is ABSENT (no process-global set)."""
    qs = SiteInstance.objects.filter(site=site)
    if qs.exists() and not qs.exclude(
        desired_state=SiteInstance.DesiredState.ABSENT,
    ).exists():
        return 410
    return 200


def stop_partner_site(site, transport, *, desired_state=None):
    for name in _container_names(site):
        transport.run(["docker", "stop", name])
    transport.run([
        "curl", "-sf", "-X", "DELETE",
        f"http://127.0.0.1:2019/id/{_route_id(site)}",
    ])
    if desired_state is None:
        desired_state = SiteInstance.DesiredState.STOPPED
    observed = (
        SiteInstance.ObservedState.ABSENT
        if desired_state == SiteInstance.DesiredState.ABSENT
        else SiteInstance.ObservedState.STOPPED
    )
    SiteInstance.objects.filter(site=site).update(
        desired_state=desired_state,
        observed_state=observed,
    )


def _mark_site_absent(site):
    qs = SiteInstance.objects.filter(site=site)
    if qs.exists():
        qs.update(desired_state=SiteInstance.DesiredState.ABSENT)
        return
    if not site.primary_target_id:
        return
    port = 20000 + (int(site.pk) % 9000)
    SiteInstance.objects.create(
        site=site,
        target=site.primary_target,
        desired_state=SiteInstance.DesiredState.ABSENT,
        observed_state=SiteInstance.ObservedState.ABSENT,
        internal_port=port,
    )


def revoke_partner_keys(partner):
    partner.pubkey_current = ""
    partner.pubkey_previous = ""
    partner.suspended = True
    partner.save(update_fields=["pubkey_current", "pubkey_previous", "suspended"])
    return partner


def suspend_partner(partner, *, actor=None, transport_for=None):
    if partner.suspended:
        return partner
    factory = transport_for if transport_for is not None else globals()["transport_for"]
    for ps in partner.partner_sites.select_related("site", "site__primary_target"):
        site = ps.site
        stop_partner_site(site, factory(site.primary_target))
    revoke_partner_keys(partner)
    return partner


def auto_trigger_kill_switch(partner, *, reason="abuse"):
    """CSAM/phishing auto-suspend: overlay-free. Files partner-kill-switch:{pk}."""
    from monitor.alerts import raise_alert

    suspend_partner(partner)
    return raise_alert(
        "partner-kill-switch",
        f"partner:{partner.pk}",
        workspace=default_workspace(),
        fingerprint=f"partner-kill-switch:{partner.pk}",
        source_engine="core.partner",
        title="Partner API kill-switch auto-triggered",
        body=(
            f"Auto-suspend ({reason}) stopped containers, detached routes, "
            "and revoked the Hub-side key."
        ),
        fix_action="Review the partner; unsuspend only after the case is closed.",
    )


def _destinations(partner):
    order = list(partner.destination_order or [])
    if not order:
        return []
    by_id = {row.pk: row for row in Target.objects.filter(pk__in=order)}
    out = []
    for pk in order:
        row = by_id.get(pk)
        if row is None:
            continue
        out.append({"id": row.pk, "host": row.host, "kind": row.kind})
    return out


def _public_partner(partner):
    return {
        "id": partner.pk,
        "slug": partner.slug,
        "name": partner.name,
        "destination_order": list(partner.destination_order or []),
        "destinations": _destinations(partner),
        "suspended": partner.suspended,
        "site_ids": list(
            partner.partner_sites.values_list("site_id", flat=True),
        ),
    }


class PartnerListCreateView(APIView):
    """GET is the operator list (no secrets). POST is T1 partner.create."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "partner.create"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated(), RequireWorkspace()]
        return [IsAuthenticated(), RequireWorkspace(), RequireAction(), RequireRecentTouch()]

    @extend_schema(operation_id="v1_partners_list", responses={200: PartnerListSerializer})
    def get(self, request):
        workspace = request_workspace(request)
        partners = [
            _public_partner(row)
            for row in Partner.objects.filter(workspace=workspace).order_by("pk")
        ]
        return Response(
            PartnerListSerializer(
                {
                    "partners": partners,
                    "intake": _intake_payload(),
                    "api_enabled": partner_api_enabled(),
                    "candidate_targets": _candidate_targets(workspace),
                }
            ).data
        )

    @extend_schema(
        request=PartnerCreateSerializer,
        responses={201: PartnerCreateResultSerializer},
    )
    def post(self, request):
        ser = PartnerCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        slug = ser.validated_data["slug"]
        if ser.validated_data["confirm_name"] != slug:
            return Response(
                {"detail": "Type the partner slug to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = (ser.validated_data.get("name") or "").strip() or slug
        workspace = request_workspace(request)
        if workspace is None:
            return Response(
                {"detail": "Workspace required."}, status=status.HTTP_403_FORBIDDEN,
            )
        if Partner.objects.filter(workspace=workspace, slug=slug).exists():
            return Response(
                {"detail": "Partner slug already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        hubk, pubkey = _mint_hubk()
        whsec = _mint_whsec()
        with transaction.atomic():
            partner = Partner.objects.create(
                workspace=workspace,
                slug=slug,
                name=name,
                pubkey_current=pubkey,
            )
            vault_service.put(
                kind=Secret.Kind.WEBHOOK_SECRET,
                owner_type="partner",
                owner_id=str(partner.pk),
                plaintext=whsec.encode("utf-8"),
                actor=request.user,
            )
            event = audit(
                "partner.create",
                obj=partner,
                actor=request.user,
                source="api",
                severity="security",
                slug=slug,
            )
            AuditEvent.objects.filter(pk=event.pk).update(partner_id=partner.pk)
        body = PartnerCreateResultSerializer(
            {
                "id": partner.pk,
                "slug": partner.slug,
                "name": partner.name,
                "hubk": hubk,
                "whsec": whsec,
            }
        )
        return Response(body.data, status=status.HTTP_201_CREATED)


class PartnerDetailView(APIView):
    """GET never echoes hubk_ or whsec_."""

    permission_classes = [IsAuthenticated, RequireWorkspace]

    @extend_schema(operation_id="v1_partners_retrieve", responses={200: PartnerPublicSerializer})
    def get(self, request, pk):
        partner = scoped_get(request, Partner.objects.all(), pk=pk)
        return Response(PartnerPublicSerializer(_public_partner(partner)).data)


class PartnerSuspendView(APIView):
    """T1 partner.suspend: type the slug, then stop + detach + revoke."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "partner.suspend"

    @extend_schema(request=ConfirmNameSerializer, responses={200: PartnerPublicSerializer})
    def post(self, request, pk):
        partner = scoped_get(request, Partner.objects.all(), pk=pk)
        ser = ConfirmNameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != partner.slug:
            return Response(
                {"detail": "Type the partner slug to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        suspend_partner(partner, actor=request.user)
        partner.refresh_from_db()
        audit(
            "partner.suspend",
            obj=partner,
            actor=request.user,
            source="api",
            severity="security",
            slug=partner.slug,
        )
        return Response(PartnerPublicSerializer(_public_partner(partner)).data)


class PartnerApiKillSwitchView(APIView):
    """T1 partner.api_kill_switch: type partner-api. Explicit enabled, never XOR."""

    permission_classes = [IsAuthenticated, RequireSystemAdmin, RequireRecentTouch]
    action_id = "partner.api_kill_switch"

    @extend_schema(request=ConfirmNameSerializer, responses={200: None})
    def post(self, request):
        ser = ConfirmNameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != "partner-api":
            return Response(
                {"detail": "Type partner-api to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        current = partner_api_enabled()
        if "enabled" in ser.validated_data:
            want = bool(ser.validated_data["enabled"])
        else:
            want = True
        if want == current:
            return Response(
                {
                    "detail": "Partner API is already in that state.",
                    "code": "already_set",
                    "api_enabled": current,
                },
                status=status.HTTP_409_CONFLICT,
            )
        set_partner_api_enabled(want)
        audit(
            "partner.api_kill_switch",
            actor=request.user,
            source="api",
            severity="security",
            enabled=want,
        )
        return Response({"api_enabled": want})


class PartnerSiteTakedownView(APIView):
    """T2 partner.site_takedown: {domain} route → 410."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction]
    action_id = "partner.site_takedown"

    @extend_schema(request=ConfirmNameSerializer, responses={410: None})
    def post(self, request, pk):
        site = scoped_get(request, Site.objects.all(), SITE_FIELD, pk=pk)
        if not PartnerSite.objects.filter(site=site).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = ConfirmNameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != (site.domain or site.name):
            return Response(
                {"detail": "Type the site domain to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _mark_site_absent(site)
        if site.primary_target_id:
            stop_partner_site(
                site,
                transport_for(site.primary_target),
                desired_state=SiteInstance.DesiredState.ABSENT,
            )
        audit(
            "partner.site_takedown",
            obj=site,
            actor=request.user,
            source="api",
            severity="security",
            domain=site.domain,
        )
        if site_route_status(site) != 410:
            return Response({"status": 200, "detail": "takedown queued"})
        return Response({"status": 410}, status=status.HTTP_410_GONE)


class PartnerDestinationRankView(APIView):
    """T2 partner.destination_rank. Own-server without tunnel is a Finding."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction]
    action_id = "partner.destination_rank"

    @extend_schema(
        request=DestinationRankSerializer,
        responses={200: PartnerPublicSerializer},
    )
    def post(self, request, pk):
        partner = scoped_get(request, Partner.objects.all(), pk=pk)
        ser = DestinationRankSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = list(ser.validated_data["destination_order"])
        from core.rbac import scope_queryset

        workspace = request_workspace(request)
        scoped_targets = scope_queryset(
            Target.objects.filter(pk__in=order), workspace, TARGET_FIELD,
        )
        targets = {row.pk: row for row in scoped_targets}
        for target_id in order:
            target = targets.get(target_id)
            if target is None:
                return Response(
                    {"detail": "Unknown destination target."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if target.kind == Target.Kind.SSH:
                payload = target.collect_payload or {}
                if payload.get("tunnel") is not True:
                    finding(
                        "core.partner",
                        f"partner-tunnel-required:{target.pk}",
                        workspace=target.zone.workspace,
                        severity="p2",
                        entity=f"target:{target.host}",
                        title="Own-server partner destination requires a tunnel",
                        body=(
                            "Own-server partner destinations refuse unless "
                            "collect_payload tunnel is true."
                        ),
                        fix_action=(
                            "Enable the tunnel on the own-server target, then rank again."
                        ),
                    )
                    return Response(
                        {"detail": "Own-server partner destination requires a tunnel."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        partner.destination_order = order
        partner.save(update_fields=["destination_order"])
        audit(
            "partner.destination_rank",
            obj=partner,
            actor=request.user,
            source="api",
            severity="security",
            n=len(order),
        )
        return Response(PartnerPublicSerializer(_public_partner(partner)).data)

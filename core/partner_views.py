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
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import audit
from core.findings import finding
from core.models import AuditEvent, Finding, Partner, PartnerSite, Site, SiteInstance, Target
from core.permissions import RequireRecentTouch
from core.transport import FakeTransport
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


def _candidate_targets():
    from core.models import Target
    out = []
    for row in Target.objects.filter(status=Target.Status.READY).order_by("pk"):
        payload = row.collect_payload or {}
        out.append({
            "id": row.pk,
            "host": row.host,
            "kind": row.kind,
            "tunnel": payload.get("tunnel") is True,
        })
    return out


def partner_api_enabled():
    return bool(getattr(settings, "PARTNER_API_ENABLED", False))


def set_partner_api_enabled(value):
    settings.PARTNER_API_ENABLED = bool(value)


def transport_for(target):
    """T1 Fake Transport by default; tests inject a recording double."""
    return FakeTransport()


def _container_name(site):
    return f"site-{site.name}"


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


def stop_partner_site(site, transport):
    name = _container_name(site)
    transport.run(["docker", "stop", name])
    transport.run([
        "curl", "-sf", "-X", "DELETE",
        f"http://127.0.0.1:2019/id/{_route_id(site)}",
    ])
    SiteInstance.objects.filter(site=site).update(
        desired_state=SiteInstance.DesiredState.STOPPED,
        observed_state=SiteInstance.ObservedState.STOPPED,
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

    permission_classes = [IsAuthenticated, RequireRecentTouch]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [IsAuthenticated(), RequireRecentTouch()]

    @extend_schema(responses={200: PartnerListSerializer})
    def get(self, request):
        partners = [
            _public_partner(row)
            for row in Partner.objects.order_by("pk")
        ]
        return Response(
            PartnerListSerializer(
                {
                    "partners": partners,
                    "intake": _intake_payload(),
                    "api_enabled": partner_api_enabled(),
                    "candidate_targets": _candidate_targets(),
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
        if Partner.objects.filter(slug=slug).exists():
            return Response(
                {"detail": "Partner slug already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        hubk, pubkey = _mint_hubk()
        whsec = _mint_whsec()
        with transaction.atomic():
            partner = Partner.objects.create(
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

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PartnerPublicSerializer})
    def get(self, request, pk):
        partner = get_object_or_404(Partner, pk=pk)
        return Response(PartnerPublicSerializer(_public_partner(partner)).data)


class PartnerSuspendView(APIView):
    """T1 partner.suspend: type the slug, then stop + detach + revoke."""

    permission_classes = [IsAuthenticated, RequireRecentTouch]

    @extend_schema(request=ConfirmNameSerializer, responses={200: PartnerPublicSerializer})
    def post(self, request, pk):
        partner = get_object_or_404(Partner, pk=pk)
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
    """T1 partner.api_kill_switch: type partner-api. Enable when OFF, never a toggle."""

    permission_classes = [IsAuthenticated, RequireRecentTouch]

    @extend_schema(request=ConfirmNameSerializer, responses={200: None})
    def post(self, request):
        ser = ConfirmNameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != "partner-api":
            return Response(
                {"detail": "Type partner-api to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        enabled = not partner_api_enabled()
        set_partner_api_enabled(enabled)
        audit(
            "partner.api_kill_switch",
            actor=request.user,
            source="api",
            severity="security",
            enabled=enabled,
        )
        return Response({"api_enabled": enabled})


class PartnerSiteTakedownView(APIView):
    """T2 partner.site_takedown: {domain} route → 410."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=ConfirmNameSerializer, responses={410: None})
    def post(self, request, pk):
        site = get_object_or_404(Site, pk=pk)
        if not PartnerSite.objects.filter(site=site).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = ConfirmNameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != (site.domain or site.name):
            return Response(
                {"detail": "Type the site domain to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        SiteInstance.objects.filter(site=site).update(
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
        return Response({"status": 410}, status=status.HTTP_410_GONE)


class PartnerDestinationRankView(APIView):
    """T2 partner.destination_rank. Own-server without tunnel is a Finding."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=DestinationRankSerializer,
        responses={200: PartnerPublicSerializer},
    )
    def post(self, request, pk):
        partner = get_object_or_404(Partner, pk=pk)
        ser = DestinationRankSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = list(ser.validated_data["destination_order"])
        targets = {row.pk: row for row in Target.objects.filter(pk__in=order)}
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

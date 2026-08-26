"""Hub-central certificate issue for unproxied public sites (D-136).

Default dns01 is refuse-closed (None). Tests inject a callable
``dns01(hostnames, csr, dns)`` that upserts TXT via DnsProvider and
returns ``{certificate, expires_at}``. PEM lands through certs helpers.
This module does not import providers.cloudflare.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from deploys.certs import (
    DEFAULT_VALIDITY_DAYS,
    RENEW_BEFORE_DAYS,
    CertKeyMismatch,
    UnproxiedCertUnsupported,
    _hostnames,
    _refuse_unproxied,
    push_tls_material,
)


class Dns01Error(UnproxiedCertUnsupported):
    """Refuse-closed dns01 seam or a failed Hub-central issue."""


def issue_unproxied(desired, *, dns01=None):
    """Issue a hub_dns01 leaf for an unproxied public site, or refuse."""
    from core.models import Finding, TlsCertificate
    from vault import service as vault_service
    from vault.models import Secret
    from vault.tls import generate_ec_keypair_and_csr, public_keys_match

    site = desired["site"]
    if dns01 is None:
        dns01 = desired.get("dns01")
    dns = desired.get("dns")
    if dns01 is None or dns is None:
        _refuse_unproxied(site)
        raise Dns01Error("dns01 refused")

    slug = desired.get("site_slug") or site.name
    hostnames = _hostnames(desired, site, slug)
    key_pem, csr_pem = generate_ec_keypair_and_csr(hostnames)
    existing = (
        TlsCertificate.objects.filter(site=site)
        .order_by("-pushed_at", "-pk")
        .first()
    )
    key_ref = (
        existing.key_ref if existing and existing.key_ref else f"site-{site.pk}-tls"
    )
    vault_service.put(
        kind=Secret.Kind.TLS_PRIVATE_KEY,
        owner_type="site",
        owner_id=key_ref,
        plaintext=key_pem,
    )
    issued = dns01(hostnames, csr_pem, dns)
    cert_pem = issued["certificate"]
    if isinstance(cert_pem, (bytes, bytearray)):
        cert_pem = cert_pem.decode()
    if not public_keys_match(key_pem, cert_pem):
        raise CertKeyMismatch(
            "certificate public key does not match the vaulted private key"
        )
    expires_at = issued.get("expires_at") or (
        timezone.now() + timedelta(days=DEFAULT_VALIDITY_DAYS)
    )
    result = push_tls_material(
        desired,
        cert_pem,
        key_pem,
        expires_at=expires_at,
        mode=TlsCertificate.Mode.HUB_DNS01,
        key_ref=key_ref,
    )
    row = Finding.objects.filter(
        fingerprint=f"unproxied-cert:{site.pk}",
        state__in=(Finding.State.OPEN, Finding.State.ACKED),
    ).first()
    if row is not None:
        from core.findings import resolve

        resolve(row, source="system")
    return result


def renew_due(*, now=None, issue=None):
    """Reissue hub_dns01 rows inside RENEW_BEFORE_DAYS. Write CheckRun.HUB_DNS01."""
    from core.models import CheckRun, TlsCertificate

    clock = now or timezone.now()
    horizon = clock + timedelta(days=RENEW_BEFORE_DAYS)
    rows = list(
        TlsCertificate.objects.filter(
            mode=TlsCertificate.Mode.HUB_DNS01,
            not_after__lte=horizon,
        ).select_related("site").order_by("pk")
    )
    act = issue if issue is not None else _ensure_row
    renewed = []
    errors = []
    for row in rows:
        try:
            act(row)
        except Dns01Error:
            errors.append(row.pk)
        else:
            renewed.append(row.pk)
    return CheckRun.objects.create(
        kind=CheckRun.Kind.HUB_DNS01,
        status=CheckRun.Status.SUCCEEDED,
        results={"schema_version": 1, "renewed": renewed, "errors": errors},
        started=clock,
        finished=timezone.now(),
    )


def _ensure_row(row):
    from deploys.certs import ensure_site_certificate

    ensure_site_certificate({
        "site": row.site,
        "site_slug": row.site.name,
        "domain": row.site.domain,
        "proxied": getattr(row.site, "proxied", False),
        "manifest_body": {"exposure": getattr(row.site, "exposure", "public")},
        "dns_zone": row.site.dns_zone,
    })

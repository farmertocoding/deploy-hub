"""Process-boundary DNS / Origin-CA construction (phase-exit C1).

execute() / run_deploy / worker_entry (no --fake) call this when the caller
did not inject dns= / cert_issuer=. It uses dns_provider_for and
origin_cert_issuer_for, and fails closed — Finding + refuse — when the
vault refs are missing. Never returns FakeDnsProvider or FakeOriginCertIssuer.
deploys/ does not import providers.cloudflare; the registry hands back the
provider / issuer.
"""
from providers.registry import dns_provider_for, origin_cert_issuer_for


class DeploySeamRefused(RuntimeError):
    """Missing product refs: do not construct a Fake and do not start."""


def resolve_production_seams(site):
    """Return (dns, cert_issuer) for a public site, or (None, None) for mesh_only."""
    if getattr(site, "exposure", None) == "mesh_only":
        return None, None

    zone = getattr(site, "dns_zone", None)
    missing = []
    if zone is None:
        missing.append("dns_zone")
    else:
        account = zone.account
        if not account.dns_token_ref:
            missing.append("dns_token_ref")
        if _needs_origin_cert(site) and not account.origin_ca_key_ref:
            missing.append("origin_ca_key_ref")
    if missing:
        _refuse(site, missing)

    dns = dns_provider_for(zone)
    issuer = origin_cert_issuer_for(zone) if _needs_origin_cert(site) else None
    return dns, issuer


def _needs_origin_cert(site):
    if getattr(site, "exposure", None) == "mesh_only":
        return False
    return bool(getattr(site, "proxied", True))


def _refuse(site, missing):
    from core.findings import finding
    from core.models import Finding

    names = ", ".join(missing)
    finding(
        "deploys",
        f"deploy-seam:{site.pk}",
        severity=Finding.Severity.P2,
        entity=f"site:{getattr(site, 'name', site)}",
        title=f"Deploy refused: missing {names}",
        body=(
            f"Site {getattr(site, 'name', site)} cannot deploy without {names}. "
            "Settings-connect stores a DNS token only; Origin certificates "
            "require origin_ca_key_ref on the DnsAccount (vault). The pipeline "
            "refuses rather than using an in-memory Fake."
        ),
        fix_action=(
            f"Set {names} on the DnsAccount in the vault. "
            "Settings-connect does not accept an Origin CA key."
        ),
    )
    raise DeploySeamRefused(f"missing {names}")

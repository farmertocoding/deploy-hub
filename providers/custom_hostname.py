"""CustomHostname helpers (D-079). No vault token, no Cloudflare HTTP client.

create/status/TXT live on the object ``dns_provider_for`` (or a flagged Fake)
returns. This module never constructs that object.
"""


class CustomHostnameError(RuntimeError):
    """Capability missing, unknown hostname, or partner-base collision."""


def ownership_txt_name(hostname):
    host = str(hostname or "").rstrip(".").lower()
    return f"_cf-custom-hostname.{host}"


def ownership_from_record(record):
    ov = record.get("ownership_verification") or {}
    return {
        "type": str(ov.get("type") or "txt").lower(),
        "name": ov.get("name") or "",
        "value": ov.get("value") or "",
    }


def ownership_txt(hostname, value):
    return {
        "type": "txt",
        "name": ownership_txt_name(hostname),
        "value": value,
    }


def is_verified(status):
    return str(status or "").lower() == "active"


def normalize_custom_hostname(row):
    hostname = row.get("hostname") or ""
    return {
        "id": row.get("id"),
        "hostname": hostname,
        "status": str(row.get("status") or "pending").lower(),
        "ownership_verification": ownership_from_record(row),
    }


def refuse_partner_base_collision(hostname):
    """Partner-base ≠ a non-partner Site domain (C5/C7)."""
    host = str(hostname or "").strip().rstrip(".").lower()
    if not host:
        raise CustomHostnameError("hostname is required")
    from core.models import PartnerSite, Site

    for site in Site.objects.exclude(domain="").filter(domain__iexact=host):
        if not PartnerSite.objects.filter(site=site).exists():
            raise CustomHostnameError(
                f"hostname {host!r} collides with a non-partner site domain"
            )


def caddy_route_for(provider, hostname):
    """Caddy route for a verified custom hostname; unverified is never served."""
    if "custom_hostname" not in provider.capabilities():
        return None
    try:
        status = provider.custom_hostname_status(hostname)
    except CustomHostnameError:
        return None
    if not is_verified(status):
        return None
    host = str(hostname).rstrip(".").lower()
    return {
        "match": [{"host": [host]}],
        "handle": [{"handler": "reverse_proxy"}],
    }

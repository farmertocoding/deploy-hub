"""ensure_site_certificate — Origin CA key lifecycle (D-035).

Vault-first: the private key is a vault row before any byte is put. The
target sees only PEM files written atomically (put temp → chmod 0400 → mv)
into a 0700 root:root ``/srv/sites/{slug}/tls/``. deploys/ never imports
``providers.cloudflare``; issuers come from ``desired["cert_issuer"]`` or
the registry factory.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

DEFAULT_VALIDITY_DAYS = 5475
RENEW_BEFORE_DAYS = 30


class UnproxiedCertUnsupported(RuntimeError):
    """Public site with proxied=false: Hub-central DNS-01 is Phase 3b."""


class CertKeyMismatch(RuntimeError):
    """The issued certificate's public key is not the vaulted private key."""


def tls_dir(slug):
    return f"/srv/sites/{slug}/tls"


def ensure_site_certificate(desired):
    """Probe-then-act Origin-cert ensure. Unproxied public sites refuse."""
    from core.models import TlsCertificate
    from vault import service as vault_service
    from vault.models import Secret

    site = desired.get("site")
    if site is None:
        return {"status": "skipped", "reason": "no_site"}
    if _exposure(desired) == "mesh_only":
        return {"status": "skipped", "reason": "mesh_only"}
    if not _proxied(desired):
        _refuse_unproxied(site)

    existing = (
        TlsCertificate.objects.filter(site=site)
        .order_by("-pushed_at", "-pk")
        .first()
    )
    slug = desired.get("site_slug") or site.name
    directory = tls_dir(slug)
    desired["tls_files"] = {
        "certificate": f"{directory}/cert.pem",
        "key": f"{directory}/key.pem",
    }
    if existing is not None and existing.mode == TlsCertificate.Mode.UPLOADED:
        return {"status": "skipped", "reason": "uploaded"}
    if existing is not None and _still_fresh(existing):
        return {"status": "skipped", "id": existing.pk}

    transport = desired["transport"]
    heartbeat = desired.get("heartbeat")
    hostnames = _hostnames(desired, site, slug)

    from vault.tls import generate_ec_keypair_and_csr, public_keys_match

    key_pem, csr_pem = generate_ec_keypair_and_csr(hostnames)
    key_ref = (existing.key_ref if existing and existing.key_ref else f"site-{site.pk}-tls")
    vault_service.put(
        kind=Secret.Kind.TLS_PRIVATE_KEY,
        owner_type="site",
        owner_id=key_ref,
        plaintext=key_pem,
    )

    issuer = _issuer(desired, site)
    issued = issuer.issue(
        desired.get("dns_zone") or site.dns_zone,
        hostnames,
        validity_days=int(desired.get("validity_days") or DEFAULT_VALIDITY_DAYS),
        csr=csr_pem,
    )
    cert_pem = issued["certificate"]
    if isinstance(cert_pem, (bytes, bytearray)):
        cert_pem = cert_pem.decode()
    if not public_keys_match(key_pem, cert_pem):
        raise CertKeyMismatch(
            "certificate public key does not match the vaulted private key"
        )

    _ensure_tls_dir(transport, directory, heartbeat)
    had_previous = _remote_exists(transport, f"{directory}/cert.pem")
    if had_previous:
        _mv(transport, f"{directory}/cert.pem", f"{directory}/cert.pem.prev", heartbeat)
        _mv(transport, f"{directory}/key.pem", f"{directory}/key.pem.prev", heartbeat)

    try:
        _atomic_write(transport, cert_pem.encode(), f"{directory}/cert.pem", heartbeat)
        _atomic_write(transport, key_pem, f"{directory}/key.pem", heartbeat)
        _reload_caddy(desired)
    except Exception:
        if had_previous:
            _restore_prev(transport, directory, heartbeat)
        raise

    if had_previous:
        _rm(transport, f"{directory}/cert.pem.prev", heartbeat)
        _rm(transport, f"{directory}/key.pem.prev", heartbeat)

    expires_at = issued.get("expires_at") or (
        timezone.now() + timedelta(days=DEFAULT_VALIDITY_DAYS)
    )
    row = TlsCertificate.objects.create(
        site=site,
        mode=TlsCertificate.Mode.ORIGIN_CERT,
        not_after=expires_at,
        fingerprint=hashlib.sha256(cert_pem.encode()).hexdigest(),
        key_ref=key_ref,
        pushed_at=timezone.now(),
    )
    return {"status": "issued", "id": row.pk, "key_ref": key_ref}


def _refuse_unproxied(site):
    from core.findings import finding
    from core.models import Finding

    finding(
        "tls",
        f"unproxied-cert:{site.pk}",
        severity=Finding.Severity.P2,
        entity=f"site:{site.name}",
        title="Unproxied public site cannot get a Hub-issued certificate",
        body=(
            f"{site.domain or site.name} is a public site with proxied=false. "
            "Hub-central DNS-01 is not built this phase (D-035); the pipeline "
            "refuses rather than shipping a DNS token to the target."
        ),
        fix_action=(
            "Enable Cloudflare proxy (proxied=true) for an Origin certificate, "
            "or wait for Phase 3b Hub-central DNS-01."
        ),
    )
    raise UnproxiedCertUnsupported(
        f"unproxied public site {site.name!r} cannot be issued a "
        "certificate this phase"
    )


def _still_fresh(row, now=None):
    now = now or timezone.now()
    if row.not_after is None:
        return False
    return row.not_after - now > timedelta(days=RENEW_BEFORE_DAYS)


def _proxied(desired):
    if "proxied" in desired:
        return bool(desired["proxied"])
    site = desired.get("site")
    if site is not None:
        return bool(getattr(site, "proxied", True))
    return True


def _exposure(desired):
    site = desired.get("site")
    body = desired.get("manifest_body") or {}
    site_exp = getattr(site, "exposure", None) if site is not None else None
    if site_exp == "mesh_only" or body.get("exposure") == "mesh_only":
        return "mesh_only"
    return site_exp or body.get("exposure") or "public"


def _hostnames(desired, site, slug):
    domain = desired.get("domain") or getattr(site, "domain", None) or f"{slug}.local"
    extra = desired.get("hostnames") or []
    names = [domain, *extra]
    return [name for name in names if name]


def _issuer(desired, site):
    issuer = desired.get("cert_issuer")
    if issuer is not None:
        return issuer
    zone = desired.get("dns_zone") or getattr(site, "dns_zone", None)
    if zone is not None:
        from providers.registry import origin_cert_issuer_for

        return origin_cert_issuer_for(zone)
    from providers.fakes import FakeOriginCertIssuer

    return FakeOriginCertIssuer()


def _ensure_tls_dir(transport, directory, heartbeat):
    _run(transport, ["sudo", "mkdir", "-p", directory], heartbeat)
    _relock_tls_dir(transport, directory, heartbeat)


def _relock_tls_dir(transport, directory, heartbeat):
    _run(transport, ["sudo", "chown", "root:root", directory], heartbeat)
    _run(transport, ["sudo", "chmod", "0700", directory], heartbeat)


def _atomic_write(transport, content, final_path, heartbeat):
    tmp = f"{final_path}.tmp"
    parent = str(Path(final_path).parent)
    # Open the 0700 dir just long enough for SFTP put as the deploy user.
    try:
        _run(transport, ["sudo", "chown", "root:deploy", parent], heartbeat)
        _run(transport, ["sudo", "chmod", "0770", parent], heartbeat)
        transport.put(content, tmp, mode=0o400)
        written = transport.get(tmp)
        if written and hashlib.sha256(_as_bytes(written)).digest() != hashlib.sha256(
            _as_bytes(content)
        ).digest():
            raise RuntimeError(f"checksum mismatch after write of {final_path}")
        _run(transport, ["sudo", "chown", "root:root", tmp], heartbeat)
        _run(transport, ["sudo", "chmod", "0400", tmp], heartbeat)
        _run(transport, ["sudo", "mv", tmp, final_path], heartbeat)
    finally:
        _relock_tls_dir(transport, parent, heartbeat)


def _reload_caddy(desired):
    reload = desired.get("caddy_reload")
    if reload is not None:
        result = reload()
        if result is False or (getattr(result, "ok", True) is False):
            raise RuntimeError("caddy reload failed")
        return result
    transport = desired["transport"]
    result = _run(
        transport,
        ["sudo", "systemctl", "reload", "caddy"],
        desired.get("heartbeat"),
    )
    if not result.ok:
        raise RuntimeError(f"caddy reload failed: {result.stderr}")
    return result


def _restore_prev(transport, directory, heartbeat):
    _mv(transport, f"{directory}/cert.pem.prev", f"{directory}/cert.pem", heartbeat)
    _mv(transport, f"{directory}/key.pem.prev", f"{directory}/key.pem", heartbeat)


def _remote_exists(transport, path):
    # The tls dir is 0700 root:root; deploy cannot traverse it without sudo.
    result = transport.probe(["sudo", "test", "-f", path])
    return bool(result.ok)


def _mv(transport, src, dst, heartbeat):
    return _run(transport, ["sudo", "mv", src, dst], heartbeat)


def _rm(transport, path, heartbeat):
    return _run(transport, ["sudo", "rm", "-f", path], heartbeat)


def _run(transport, argv, heartbeat=None):
    if not isinstance(argv, (list, tuple)):
        raise TypeError("argv must be a list — never a shell string (§4.5)")
    argv = list(argv)
    if heartbeat is not None:
        heartbeat()
    return transport.run(argv)


def _as_bytes(value):
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return str(value).encode()

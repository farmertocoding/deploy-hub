"""Input validators that are also security boundaries (§4.5, §B10).

The git URL is the first untrusted, attacker-influenced value the Hub accepts, and the
Hub sits inside the crown-jewel boundary with a cloud metadata endpoint one request
away. Allowlist, never blocklist.
"""
import ipaddress
import re
import socket
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError

ALLOWED_SCHEMES = {"https", "ssh"}
ALLOWED_PORTS = {None, 22, 443}
MAX_URL_LENGTH = 2048

# Hostname suffixes that only ever resolve inside a private network.
BLOCKED_SUFFIXES = (".local", ".internal", ".localdomain", ".home.arpa")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> str | None:
    """Return a reason string if this address must not be reached, else None."""
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        # 169.254.169.254 is the cloud metadata endpoint — the single highest-value
        # SSRF target on any cloud host, and the reason this validator exists.
        return "link-local address (cloud metadata range)"
    if ip.is_private:
        return "private address"
    if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return "reserved, multicast or unspecified address"
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
        return "carrier-grade NAT address"
    return None


def resolve_and_check_host(host: str):
    """Resolve host and reject if ANY returned address is non-public.

    Any, not all: a name resolving to one public and one private address is a
    deliberate attack shape, not a misconfiguration.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationError(
            f"could not resolve host {host!r}", code="unresolvable"
        ) from exc

    addresses = {info[4][0] for info in infos}
    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        reason = _is_blocked_ip(ip)
        if reason:
            raise ValidationError(
                f"host {host!r} resolves to a {reason} ({raw}) and cannot be a "
                f"git source",
                code="blocked_address",
            )
    return addresses


def validate_git_url(value: str, *, resolve=True):
    """Validate a git remote URL.

    KNOWN LIMIT — read before relying on this. Validation happens at submit time, so a
    DNS-rebinding host can resolve differently at clone time. The structural mitigation
    is that per §B1/§M1 the Hub never clones: the clone runs on the build target, which
    already has outbound internet, so a rebind reaches a target rather than the control
    plane. Resolve-and-pin at the target is Phase 2 (D-007). This validator is the
    first of two layers, not the only one.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("a git URL is required", code="required")
    value = value.strip()

    if len(value) > MAX_URL_LENGTH:
        raise ValidationError(
            f"git URL exceeds {MAX_URL_LENGTH} characters", code="too_long"
        )
    if _CONTROL_CHARS.search(value):
        # Newlines and control characters are how a URL becomes two arguments.
        raise ValidationError(
            "git URL contains control characters", code="control_chars"
        )

    # scp-style (git@host:org/repo) is common but ambiguous to parse and offers no
    # capability https/ssh:// lack. Reject with the fix spelled out.
    if "://" not in value:
        if re.match(r"^[^/]+@[^/:]+:", value):
            raise ValidationError(
                "scp-style git URLs are not accepted — use "
                "ssh://git@host/org/repo.git",
                code="scp_syntax",
            )
        raise ValidationError("git URL must include a scheme", code="no_scheme")

    parts = urlsplit(value)
    scheme = "ssh" if parts.scheme == "git+ssh" else parts.scheme

    if scheme not in ALLOWED_SCHEMES:
        raise ValidationError(
            f"scheme {parts.scheme!r} is not allowed — use https or ssh "
            f"(plaintext http and git:// are unauthenticated and tamperable)",
            code="bad_scheme",
        )

    # Scheme-aware, because "userinfo" means two different things:
    #   ssh://git@host/...   -> 'git' is the SSH login. Standard, required, harmless.
    #   https://user:tok@... -> a credential in a URL, which leaks into audit rows,
    #                           logs and error messages.
    # A password is never acceptable in either scheme.
    if parts.password:
        raise ValidationError(
            "passwords must not be embedded in the URL — store credentials in the "
            "vault and reference the key",
            code="embedded_credentials",
        )
    if scheme == "https" and parts.username:
        raise ValidationError(
            "credentials must not be embedded in the URL — store them in the vault "
            "and reference the key",
            code="embedded_credentials",
        )

    host = parts.hostname
    if not host:
        raise ValidationError("git URL has no host", code="no_host")

    lowered = host.lower()
    if lowered in {"localhost"} or lowered.endswith(BLOCKED_SUFFIXES):
        raise ValidationError(
            f"host {host!r} is a private-network name and cannot be a git source",
            code="blocked_host",
        )

    try:
        port = parts.port
    except ValueError as exc:
        raise ValidationError("git URL has an invalid port", code="bad_port") from exc
    if port not in ALLOWED_PORTS:
        raise ValidationError(
            f"port {port} is not allowed — use the default port for https or ssh",
            code="bad_port",
        )

    if not parts.path or parts.path in ("/", ""):
        raise ValidationError("git URL has no repository path", code="no_path")

    # A bare IP literal is checked directly; a name is resolved.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        reason = _is_blocked_ip(literal)
        if reason:
            raise ValidationError(
                f"{host} is a {reason} and cannot be a git source",
                code="blocked_address",
            )
    elif resolve:
        resolve_and_check_host(host)

    return value

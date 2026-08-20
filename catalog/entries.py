"""Versioned catalog entries (§D8). Changed semantics = version bump."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogEntry:
    """One check/fix/rollback triple. `id` is stable; `version` pins semantics."""

    id: str
    version: int
    check: list[str]
    fix: list[str]
    rollback: list[str]
    os_variant: str = "ubuntu"


NTP_CHRONY = CatalogEntry(
    id="ntp-chrony",
    version=1,
    check=["systemctl", "is-active", "chrony"],
    fix=["apt-get", "install", "-y", "chrony"],
    rollback=["systemctl", "disable", "--now", "chrony"],
)

LOG_ROTATION = CatalogEntry(
    id="log-rotation",
    version=2,
    check=["test", "-f", "/etc/logrotate.d/caddy"],
    fix=[
        "install", "-m", "0644",
        "/usr/local/share/hub-catalog/logrotate-caddy",
        "/etc/logrotate.d/caddy",
    ],
    rollback=["rm", "-f", "/etc/logrotate.d/caddy"],
)

DOCKER_DAEMON_JSON = CatalogEntry(
    id="docker-daemon-json",
    version=2,
    check=["test", "-f", "/etc/docker/daemon.json"],
    fix=[
        "install", "-m", "0644",
        "/usr/local/share/hub-catalog/docker-daemon.json",
        "/etc/docker/daemon.json",
    ],
    rollback=["rm", "-f", "/etc/docker/daemon.json"],
)

SSHD_DROPIN = CatalogEntry(
    id="sshd-dropin",
    version=2,
    check=["test", "-f", "/etc/ssh/sshd_config.d/99-hub-hardening.conf"],
    fix=[
        "install", "-m", "0644",
        "/usr/local/share/hub-catalog/99-hub-hardening.conf",
        "/etc/ssh/sshd_config.d/99-hub-hardening.conf",
    ],
    rollback=["rm", "-f", "/etc/ssh/sshd_config.d/99-hub-hardening.conf"],
)

UFW_POSTURE_HUB = CatalogEntry(
    id="ufw-posture-hub",
    version=1,
    check=["ufw", "status", "verbose"],
    fix=["ufw", "allow", "in", "on", "tailscale0"],
    rollback=["ufw", "delete", "allow", "in", "on", "tailscale0"],
)

UFW_POSTURE_TARGET = CatalogEntry(
    id="ufw-posture-target",
    version=1,
    check=["ufw", "status", "verbose"],
    fix=[
        "ufw", "allow", "proto", "tcp", "from", "173.245.48.0/20",
        "to", "any", "port", "80", "443", "comment", "cloudflare-edge",
    ],
    rollback=[
        "ufw", "delete", "allow", "proto", "tcp", "from", "173.245.48.0/20",
        "to", "any", "port", "80", "443",
    ],
)

UFW_POSTURE_INTAKE = CatalogEntry(
    id="ufw-posture-intake",
    version=1,
    check=["systemctl", "is-active", "cloudflared"],
    fix=["ufw", "allow", "in", "on", "tailscale0"],
    rollback=["ufw", "delete", "allow", "in", "on", "tailscale0"],
)

FAIL2BAN_IGNOREIP = CatalogEntry(
    id="fail2ban-ignoreip",
    version=2,
    check=["fail2ban-client", "get", "sshd", "ignoreip"],
    fix=["systemctl", "enable", "--now", "fail2ban"],
    rollback=["systemctl", "disable", "--now", "fail2ban"],
)

CADDY = CatalogEntry(
    id="caddy",
    version=1,
    check=["systemctl", "is-active", "caddy"],
    fix=["apt-get", "install", "-y", "caddy"],
    rollback=["systemctl", "disable", "--now", "caddy"],
)

CATALOG: tuple[CatalogEntry, ...] = (
    NTP_CHRONY,
    LOG_ROTATION,
    DOCKER_DAEMON_JSON,
    SSHD_DROPIN,
    UFW_POSTURE_HUB,
    UFW_POSTURE_TARGET,
    UFW_POSTURE_INTAKE,
    FAIL2BAN_IGNOREIP,
    CADDY,
)

ENTRIES = {entry.id: entry for entry in CATALOG}
